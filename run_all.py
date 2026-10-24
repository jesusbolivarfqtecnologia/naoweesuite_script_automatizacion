import argparse
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

# Reusar funciones de los módulos existentes
import main as extractor
import map_chapters as mapper
import build_payloads as payloads
from pipeline_utils import clear_json_files, configure_logging, load_json, merge_headers, resolve_auth, save_json


LOGGER = logging.getLogger("presupuestos")


def _resolve_auth(config: Dict[str, Any], cli_token: Optional[str]) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
    return resolve_auth(config, cli_token)


def _preflight_auth_or_exit(uris: Dict[str, Any], token: Optional[str], extra_headers: Optional[Dict[str, str]], *, need_online: bool) -> bool:
    """Valida el token antes de iniciar el pipeline. Devuelve True si todo OK; False si se debe abortar.
    Solo valida si need_online=True (es decir, se usará al menos un endpoint online).
    """
    if not need_online:
        return True
    if not token:
        print("[ERROR] No hay token de autenticación y se requieren endpoints online. Agrega el token en config.json o usa --auth-token.")
        return False
    # Usar get_users como verificación rápida
    ep = uris.get("endpoints", {}).get("get_users")
    if not ep:
        # Si no hay endpoint de users, no podemos validar aquí; continuar.
        return True
    url = ep.get("uri")
    method = (ep.get("method") or "GET").upper()
    if method != "GET":
        return True
    headers = merge_headers(ep, token, extra_headers)
    try:
        resp = requests.get(url, headers=headers or None, timeout=10)
    except Exception as e:
        print(f"[WARN] No se pudo validar el token (red): {e}. Se continuará, pero podría fallar luego.")
        return True
    # Si el servidor responde con error explícito de token inválido, abortar
    try:
        data = resp.json()
    except Exception:
        data = None
    if isinstance(data, dict) and str(data.get("error", "")).lower() == "invalid token":
        print("[ERROR] Token inválido. Reemplaza el token en config.json o pasa --auth-token=<TOKEN>. Se aborta antes de procesar XLSX.")
        return False
    if resp.status_code == 401:
        print("[ERROR] Autenticación fallida (401). Reemplaza el token en config.json o pasa --auth-token=<TOKEN>. Se aborta antes de procesar XLSX.")
        return False
    return True


def step_submit_payloads(mapped_dir: Path, uris: Dict[str, Any], token: Optional[str], extra_headers: Optional[Dict[str, str]]) -> tuple[int, int]:
    """Envía los payloads generados en mapped_dir usando create/update según update_aiu.
    No muta los archivos; remueve budget_id solo del cuerpo enviado.
    Devuelve (enviados_ok, fallidos).
    """
    ep_create = uris.get("endpoints", {}).get("create_budget") or {}
    ep_update = uris.get("endpoints", {}).get("update_budget") or {}

    sent_ok = 0
    failed = 0
    for p in sorted(mapped_dir.glob("*.json")):
        try:
            obj = load_json(p)
        except Exception as e:
            print(f"[WARN] No se pudo leer '{p.name}' para envío: {e}")
            failed += 1
            continue
        if not (isinstance(obj, dict) and "beneficiary_id" in obj):
            # No es un payload
            continue

        update_aiu = bool(obj.get("update_aiu"))
        budget_id = obj.get("budget_id")
        # Preparar body sin budget_id
        try:
            body = json.loads(json.dumps(obj))
        except Exception:
            body = obj.copy()
        body.pop("budget_id", None)

        if update_aiu:
            # update -> requiere budget_id en path
            if budget_id is None:
                print(f"[WARN] '{p.name}' update_aiu=true pero sin budget_id; se omite envío")
                failed += 1
                continue
            url = str(ep_update.get("uri", "")).replace("{{budget_id}}", str(budget_id))
            method = (ep_update.get("method") or "PUT").upper()
            ep_headers = ep_update.get("headers") if isinstance(ep_update.get("headers"), dict) else {}
        else:
            # create -> nunca enviar budget_id en el body
            url = str(ep_create.get("uri", ""))
            method = (ep_create.get("method") or "POST").upper()
            ep_headers = ep_create.get("headers") if isinstance(ep_create.get("headers"), dict) else {}

        if not url:
            print(f"[WARN] '{p.name}' sin URL configurada para el endpoint correspondiente; se omite")
            failed += 1
            continue

        headers = merge_headers({"headers": ep_headers}, token, extra_headers)
        # content-type json por defecto
        headers.setdefault("Content-Type", "application/json")

        try:
            if method == "POST":
                r = requests.post(url, headers=headers, json=body, timeout=30)
            elif method == "PUT":
                r = requests.put(url, headers=headers, json=body, timeout=30)
            else:
                print(f"[WARN] Método no soportado para envío: {method}")
                failed += 1
                continue
        except Exception as e:
            print(f"[ERROR] Envío fallido para '{p.name}': {e}")
            failed += 1
            continue

        # Interpretar resultado
        if 200 <= r.status_code < 300:
            print(f"[SENT] {method} {url} <- {p.name} [{r.status_code}]")
            sent_ok += 1
        else:
            try:
                err = r.json()
            except Exception:
                err = r.text
            print(f"[FAIL] {method} {url} <- {p.name} [{r.status_code}]: {err}")
            failed += 1

    print(f"[RESUMEN] Envíos: OK={sent_ok}, FAIL={failed}")
    return sent_ok, failed


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
        raw = load_json(chapters_file)
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

    apu_to_subcat_id, code_to_category_id, apu_to_meta = mapper.build_mappings(chapters)
    print(f"[STEP] Mapeando códigos/ids (apu:{len(apu_to_subcat_id)}, cat:{len(code_to_category_id)}), con metadatos apu({len(apu_to_meta)})...")

    mapped_dir.mkdir(parents=True, exist_ok=True)
    files = mapper.list_json_files(json_input_dir)
    count = 0
    for p in files:
        try:
            data = load_json(p)
        except Exception as e:
            print(f"[WARN] No se pudo leer '{p.name}': {e}")
            continue
        if not isinstance(data, dict):
            print(f"[WARN] '{p.name}' no contiene un objeto JSON; se omite")
            continue

        new_data = mapper.transform_budget_json(data, apu_to_subcat_id, code_to_category_id, apu_to_meta)

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
        save_json(out_path, new_data)
        print(f"[OK] Mapeado: {out_path}")
        count += 1
    print(f"[RESUMEN] Mapeados: {count} archivos en '{mapped_dir.resolve()}'")
    return count


def step_enrich_and_build(mapped_dir: Path, uris: Dict[str, Any], token: Optional[str], extra_headers: Optional[Dict[str, str]], users_file: Optional[Path], beneficiary_file: Optional[Path], template_name: str) -> tuple[int, list[dict]]:
    # Preparar user_map
    user_map: Dict[str, Dict[str, Any]] = {}
    try:
        if users_file:
            users_raw = load_json(users_file)
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
            if not isinstance(u, dict):
                continue
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
        beneficiary_offline = load_json(beneficiary_file)
        if not isinstance(beneficiary_offline, dict):
            raise RuntimeError("El beneficiary-file debe ser un objeto JSON")
        print(f"[INFO] Beneficiary desde archivo local: {beneficiary_file}")

    built = 0
    skipped_false: list[dict] = []
    for p in sorted(mapped_dir.glob("*.json")):
        try:
            data = load_json(p)
        except Exception as e:
            print(f"[WARN] No se pudo leer '{p.name}': {e}")
            continue
        if not isinstance(data, dict):
            print(f"[WARN] '{p.name}' no contiene un objeto JSON; se omite")
            continue
        if not isinstance(data.get("categories"), list):
            print(f"[WARN] '{p.name}' no contiene una lista 'categories'; se omite")
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
            skipped_false.append({
                "file": p.name,
                "beneficiary_document": payloads.normalize_digits(data.get("beneficiary_document")) or "",
            })
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
        save_json(p, pay)
        print(f"[OK] Payload (in-place): {p}")
        built += 1

    print(f"[RESUMEN] Payloads generados: {built} en '{mapped_dir.resolve()}'")
    return built, skipped_false


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
    submit = p.add_mutually_exclusive_group()
    submit.add_argument("--submit", action="store_true", help="Enviar payloads a la API")
    submit.add_argument("--no-submit", action="store_true", help="No enviar payloads (opción de compatibilidad)")
    p.add_argument("--final-dir", default="output_payloads", help="Carpeta para payloads finales (por defecto: output_payloads)")
    p.add_argument("--clean-output", action="store_true", help="Limpiar JSON de trabajo y finales antes de iniciar")
    p.add_argument("--log-file", default=None, help="Archivo opcional para registrar la ejecución")
    p.add_argument("--verbose", action="store_true", help="Activar logging detallado")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    input_dir = Path(args.input_dir)
    json_dir = Path(args.json_dir)
    mapped_dir = Path(args.mapped_dir)
    final_dir = Path(args.final_dir)

    configure_logging(Path(args.log_file) if args.log_file else None, args.verbose)
    LOGGER.info("Iniciando pipeline")

    offline_paths = {
        "chapters": Path(args.chapters_file) if args.chapters_file else None,
        "users": Path(args.users_file) if args.users_file else None,
        "beneficiary": Path(args.beneficiary_file) if args.beneficiary_file else None,
    }
    provided_offline = [name for name, path in offline_paths.items() if path is not None]
    if provided_offline and len(provided_offline) != len(offline_paths):
        missing = ", ".join(name for name, path in offline_paths.items() if path is None)
        LOGGER.error("Modo offline incompleto; faltan archivos: %s", missing)
        return 1
    if provided_offline:
        missing_files = [str(path) for path in offline_paths.values() if path is not None and not path.is_file()]
        if missing_files:
            LOGGER.error("No existen los archivos offline: %s", ", ".join(missing_files))
            return 1
        try:
            chapters_data = load_json(offline_paths["chapters"])
            users_data = load_json(offline_paths["users"])
            beneficiary_data = load_json(offline_paths["beneficiary"])
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.error("No se pudo leer la entrada offline: %s", exc)
            return 1
        if not isinstance(chapters_data, (dict, list)) or not chapters_data:
            LOGGER.error("El archivo offline de chapters debe contener un objeto o lista no vacía")
            return 1
        if not isinstance(users_data, (dict, list)) or not users_data:
            LOGGER.error("El archivo offline de users debe contener un objeto o lista no vacía")
            return 1
        if not isinstance(beneficiary_data, dict):
            LOGGER.error("El archivo offline de beneficiary debe contener un objeto JSON")
            return 1

    if args.clean_output:
        removed = sum(clear_json_files(directory) for directory in (json_dir, mapped_dir, final_dir))
        LOGGER.info("Limpieza solicitada: %s JSON eliminado(s)", removed)

    uris = mapper.load_uris(Path(args.uris))
    config = mapper.load_config(Path(args.config))
    token, extra_headers = _resolve_auth(config, args.auth_token)

    # Pre-chequeo de token antes de cualquier procesamiento costoso
    offline_ready = bool(provided_offline)
    submit_enabled = bool(args.submit)
    need_online = (not offline_ready) or submit_enabled
    if not _preflight_auth_or_exit(uris, token, extra_headers, need_online=need_online):
        return 1

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
    built, skipped_false = step_enrich_and_build(mapped_dir, uris, token, extra_headers, users_file, beneficiary_file, args.template)

    # Paso 4.5: Envío solo si se solicita explícitamente con --submit
    if submit_enabled:
        # Revalidación rápida (por si se corrió en modo 100% offline sin token)
        if not _preflight_auth_or_exit(uris, token, extra_headers, need_online=True):
            return 1
        _, failed = step_submit_payloads(mapped_dir, uris, token, extra_headers)
        if failed:
            LOGGER.error("El envío terminó con %s fallo(s)", failed)

    # Paso final: copiar solo payloads a una carpeta separada, preservando intermedios
    try:
        final_dir.mkdir(parents=True, exist_ok=True)
        # Copiar solo payloads (archivos que tienen 'beneficiary_id' en el root)
        copied = 0
        skipped = 0
        for m in mapped_dir.glob("*.json"):
            try:
                obj = load_json(m)
            except Exception:
                skipped += 1
                continue
            if isinstance(obj, dict) and "beneficiary_id" in obj:
                dest = final_dir / m.name
                shutil.copy2(m, dest)
                copied += 1
            else:
                skipped += 1
        print(f"[FINAL] '{final_dir.name}': copiados {copied} payload(s), omitidos {skipped}")
    except Exception as e:
        print(f"[WARN] No se pudo escribir '{final_dir}': {e}")

    LOGGER.info("Intermedios preservados en '%s' y '%s'", json_dir, mapped_dir)
    return 1 if submit_enabled and failed else 0


if __name__ == "__main__":
    sys.exit(main())
