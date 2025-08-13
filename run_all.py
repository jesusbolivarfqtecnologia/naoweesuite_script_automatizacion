import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

# Reusar funciones de los módulos existentes
import main as extractor
import map_chapters as mapper
import build_payloads as payloads


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _resolve_auth(config: Dict[str, Any], cli_token: Optional[str]) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
    cfg_auth = config.get("auth") if isinstance(config, dict) else None
    cfg_token = None
    if isinstance(cfg_auth, dict):
        t = cfg_auth.get("token")
        if isinstance(t, str) and t.strip():
            cfg_token = t.strip()
    token = cli_token or cfg_token
    cfg_headers = config.get("headers") if isinstance(config, dict) else None
    extra_headers = {str(k): str(v) for k, v in cfg_headers.items()} if isinstance(cfg_headers, dict) else None
    return token, extra_headers


def step_extract_xlsx_to_json(input_dir: Path, output_dir: Path, args) -> List[Path]:
    # Buscar .xlsx recursivamente (excluye temporales ~) en todo input_dir
    if not input_dir.exists():
        input_dir.mkdir(parents=True, exist_ok=True)
    excels = [p for p in input_dir.rglob("*.xlsx") if not p.name.startswith("~$")]
    if not excels:
        print(f"[INFO] No hay .xlsx en '{input_dir.resolve()}'. Se omite extracción.")
        return []
    print(f"[STEP] Extrayendo XLSX -> JSON ({len(excels)})...")
    produced: List[Path] = []
    for xlsx in sorted(excels):
        data = extractor.procesar_archivo(
            xlsx,
            letra_celda_codigo=args.code_col,
            numero_celda_codigo=args.code_row_start,
            letra_celda_inicio_elementos=args.elem_col_start,
            numero_celda_inicio_elementos=args.elem_row_start,
            letra_celda_fin_elementos=args.elem_col_end,
            numero_celda_fin_elementos=args.elem_row_end,
            steps=args.steps,
        )
        if data is None:
            continue
        out = extractor.guardar_json_con_consecutivo(output_dir, data)
        print(f"[OK] JSON: {out}")
        produced.append(out)
    print(f"[RESUMEN] XLSX->JSON: {len(produced)} archivos en '{output_dir.resolve()}'")
    return produced


def step_map_chapters(json_input_dir: Path, mapped_dir: Path, uris: Dict[str, Any], token: Optional[str], extra_headers: Optional[Dict[str, str]], chapters_file: Optional[Path], budget_id: Optional[int], budget_map: Dict[str, Any]) -> int:
    # Cargar chapters
    if chapters_file:
        raw = _load_json(chapters_file)
        if isinstance(raw, dict):
            chapters = [raw]
        elif isinstance(raw, list):
            chapters = raw
        else:
            raise RuntimeError("Formato inválido en chapters-file")
        print(f"[INFO] Chapters desde archivo local: {chapters_file}")
    else:
        print("[INFO] Consultando get_chapters...")
        chapters = mapper.fetch_get_chapters(uris, token=token, extra_headers=extra_headers)

    apu_to_subcat_id, code_to_category_id = mapper.build_mappings(chapters)
    print(f"[STEP] Mapeando códigos/ids (apu:{len(apu_to_subcat_id)}, cat:{len(code_to_category_id)})...")

    mapped_dir.mkdir(parents=True, exist_ok=True)
    files = mapper.list_json_files(json_input_dir)
    count = 0
    for p in files:
        try:
            data = _load_json(p)
        except Exception as e:
            print(f"[WARN] No se pudo leer '{p.name}': {e}")
            continue

        new_data = mapper.transform_budget_json(data, apu_to_subcat_id, code_to_category_id)

        # Resolver budget_id
        if p.name in budget_map:
            resolved_budget_id = budget_map.get(p.name)
        elif budget_id is not None:
            resolved_budget_id = budget_id
        else:
            resolved_budget_id = data.get("budget_id")
        new_data["budget_id"] = resolved_budget_id if resolved_budget_id is not None else None

        # Renombrar cedula -> beneficiary_document (string) ya en esta etapa (evita hacerlo luego)
        if "cedula" in new_data and "beneficiary_document" not in new_data:
            try:
                new_data["beneficiary_document"] = str(new_data.get("cedula") or "")
                del new_data["cedula"]
            except Exception:
                new_data["beneficiary_document"] = str(new_data.get("cedula"))
                new_data.pop("cedula", None)

        out_path = mapped_dir / p.name
        _save_json(out_path, new_data)
        print(f"[OK] Mapeado: {out_path}")
        count += 1
    print(f"[RESUMEN] Mapeados: {count} archivos en '{mapped_dir.resolve()}'")
    return count


def step_enrich_and_build(mapped_dir: Path, uris: Dict[str, Any], token: Optional[str], extra_headers: Optional[Dict[str, str]], users_file: Optional[Path], beneficiary_file: Optional[Path], template_name: str) -> int:
    # Preparar user_map
    user_map: Dict[str, Dict[str, Any]] = {}
    try:
        if users_file:
            users_raw = _load_json(users_file)
            if isinstance(users_raw, dict):
                users = users_raw.get("items", []) or []
            elif isinstance(users_raw, list):
                users = users_raw
            else:
                raise RuntimeError("Formato inválido en users-file")
            print(f"[INFO] Usuarios desde archivo local: {len(users)}")
        else:
            print("[INFO] Consultando get_users...")
            users = payloads.fetch_get_users(uris, token=token, extra_headers=extra_headers)
            print(f"[INFO] Usuarios recibidos: {len(users)}")
        for u in users:
            doc = payloads.normalize_digits(u.get("document_number"))
            if not doc:
                continue
            user_map[doc] = {"budget_id": u.get("budget_id"), "id": u.get("id")}
    except Exception as e:
        print(f"[WARN] No se pudo obtener users: {e}")
        user_map = {}

    reference = payloads.get_payload_reference(uris, template_name)
    beneficiary_offline: Optional[Dict[str, Any]] = None
    if beneficiary_file:
        beneficiary_offline = _load_json(beneficiary_file)
        if not isinstance(beneficiary_offline, dict):
            raise RuntimeError("El beneficiary-file debe ser un objeto JSON")
        print(f"[INFO] Beneficiary desde archivo local: {beneficiary_file}")

    built = 0
    for p in sorted(mapped_dir.glob("*.json")):
        try:
            data = _load_json(p)
        except Exception as e:
            print(f"[WARN] No se pudo leer '{p.name}': {e}")
            continue

        # Enriquecer con id/budget_id/exist
        ced = payloads.normalize_digits(data.get("beneficiary_document")) or payloads.normalize_digits(data.get("cedula"))
        info = user_map.get(ced) if ced else None
        if info:
            data["budget_id"] = info.get("budget_id")
            data["id"] = info.get("id")
            data["exist"] = True
        else:
            data.setdefault("budget_id", None)
            data.setdefault("id", None)
            data["exist"] = False

        # Si no existe el usuario (exist=false), no construir payload
        if data.get("exist") is False:
            print(f"[INFO] '{p.name}' exist=false; se omite payload")
            continue

        user_id = data.get("id")
        if user_id is None and not beneficiary_offline:
            print(f"[WARN] '{p.name}' no tiene 'id' y no hay beneficiary offline; se omite payload")
            continue

        # Obtener beneficiary
        try:
            ben = beneficiary_offline if beneficiary_offline is not None else payloads.fetch_get_beneficiary(uris, user_id, token=token, extra_headers=extra_headers)
        except Exception as e:
            print(f"[WARN] No se pudo obtener beneficiary para '{p.name}': {e}")
            continue

        # Construir payload y escribir in-place
        pay = payloads.build_payload(reference, data, ben)
        _save_json(p, pay)
        print(f"[OK] Payload (in-place): {p}")
        built += 1

    print(f"[RESUMEN] Payloads generados: {built} en '{mapped_dir.resolve()}'")
    return built


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Pipeline completo: XLSX->JSON, mapeo, enriquecimiento y payload in-place en un solo comando.")
    # Entrada/Salida
    p.add_argument("--input-dir", default="input_xlsx", help="Carpeta con .xlsx (por defecto: input_xlsx)")
    p.add_argument("--json-dir", default="output_json", help="Carpeta para JSON intermedios (por defecto: output_json)")
    p.add_argument("--mapped-dir", default="output_json_mapped", help="Carpeta para JSON mapeados/payload (por defecto: output_json_mapped)")
    # Extractor parámetros (por si requieren ajustes)
    p.add_argument("--steps", type=int, default=33)
    p.add_argument("--code-col", default="B")
    p.add_argument("--code-row-start", type=int, default=9)
    p.add_argument("--elem-col-start", default="F")
    p.add_argument("--elem-row-start", type=int, default=12)
    p.add_argument("--elem-col-end", default="S")
    p.add_argument("--elem-row-end", type=int, default=27)
    # Config y endpoints
    p.add_argument("--uris", default="URIS.json")
    p.add_argument("--config", default="config.json")
    p.add_argument("--auth-token", default=None)
    # Offline / opcionales
    p.add_argument("--chapters-file", default=None)
    p.add_argument("--users-file", default=None)
    p.add_argument("--beneficiary-file", default=None)
    p.add_argument("--budget-id", type=int, default=None)
    p.add_argument("--budget-map", default=None, help="Ruta a JSON {\"<archivo.json>\": budget_id}")
    p.add_argument("--template", default="budget_payload")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir)
    json_dir = Path(args.json_dir)
    mapped_dir = Path(args.mapped_dir)

    uris = mapper.load_uris(Path(args.uris))
    config = mapper.load_config(Path(args.config))
    token, extra_headers = _resolve_auth(config, args.auth_token)

    # Paso 1: XLSX -> JSON
    step_extract_xlsx_to_json(input_dir, json_dir, args)

    # Paso 2: Mapeo capítulos/actividades -> JSON mapeados
    budget_map: Dict[str, Any] = {}
    if args.budget_map:
        try:
            budget_map = mapper.load_budget_map(args.budget_map)
        except Exception:
            budget_map = {}
    chapters_file = Path(args.chapters_file) if args.chapters_file else None
    step_map_chapters(json_dir, mapped_dir, uris, token, extra_headers, chapters_file, args.budget_id, budget_map)

    # Paso 3 y 4: Enriquecer + Payload in-place
    users_file = Path(args.users_file) if args.users_file else None
    beneficiary_file = Path(args.beneficiary_file) if args.beneficiary_file else None
    step_enrich_and_build(mapped_dir, uris, token, extra_headers, users_file, beneficiary_file, args.template)

    # Paso final: Reemplazar output_json con el contenido final de mapped_dir
    try:
        json_dir.mkdir(parents=True, exist_ok=True)
        # Limpiar JSON existentes
        removed = 0
        for p in json_dir.glob("*.json"):
            try:
                p.unlink()
                removed += 1
            except Exception:
                pass
        # Copiar finales
        copied = 0
        for m in mapped_dir.glob("*.json"):
            dest = json_dir / m.name
            shutil.copy2(m, dest)
            copied += 1
        print(f"[FINAL] Reemplazado '{json_dir.name}': quitados {removed}, copiados {copied} desde '{mapped_dir.name}'")
    except Exception as e:
        print(f"[WARN] No se pudo reemplazar '{json_dir}': {e}")

    # Limpiar carpeta mapped_dir
    try:
        if mapped_dir.exists():
            for p in mapped_dir.glob("*"):
                try:
                    if p.is_file() or p.is_symlink():
                        p.unlink(missing_ok=True)
                except Exception:
                    pass
            # Eliminar directorio vacío
            mapped_dir.rmdir()
            print(f"[CLEANUP] Eliminada carpeta '{mapped_dir.name}'")
    except Exception as e:
        print(f"[WARN] No se pudo eliminar '{mapped_dir}': {e}")


if __name__ == "__main__":
    main()
