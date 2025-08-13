import argparse
import copy
import re
import json
from pathlib import Path
from typing import Any, Dict, Optional

import requests


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_uris(uris_path: Path) -> Dict[str, Any]:
    return load_json(uris_path)


def load_config(config_path: Path) -> Dict[str, Any]:
    if not config_path.exists():
        return {}
    return load_json(config_path)


def fetch_get_beneficiary(uris: Dict[str, Any], user_id: Any, *, token: Optional[str] = None, extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    ep = uris.get("endpoints", {}).get("get_beneficiary")
    if not ep:
        raise RuntimeError("Endpoint 'get_beneficiary' no encontrado en URIS.json")
    raw_url = ep.get("uri")
    method = (ep.get("method") or "GET").upper()
    if method != "GET":
        raise RuntimeError("El endpoint get_beneficiary debe ser GET")

    url = str(raw_url).replace("{{user_id}}", str(user_id))

    headers: Dict[str, str] = {}
    cfg_headers = ep.get("headers")
    if isinstance(cfg_headers, dict):
        headers.update({str(k): str(v) for k, v in cfg_headers.items()})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra_headers:
        headers.update(extra_headers)

    resp = requests.get(url, headers=headers or None, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict):
        return data
    raise RuntimeError("Respuesta inesperada del endpoint get_beneficiary (se esperaba objeto)")


def normalize_digits(x: Any) -> str:
    s = "" if x is None else str(x)
    return re.sub(r"\D+", "", s)


def fetch_get_users(uris: Dict[str, Any], *, token: Optional[str] = None, extra_headers: Optional[Dict[str, str]] = None):
    ep = uris.get("endpoints", {}).get("get_users")
    if not ep:
        raise RuntimeError("Endpoint 'get_users' no encontrado en URIS.json")
    url = ep.get("uri")
    method = (ep.get("method") or "GET").upper()
    if method != "GET":
        raise RuntimeError("El endpoint get_users debe ser GET")
    headers: Dict[str, str] = {}
    cfg_headers = ep.get("headers")
    if isinstance(cfg_headers, dict):
        headers.update({str(k): str(v) for k, v in cfg_headers.items()})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra_headers:
        headers.update(extra_headers)

    resp = requests.get(url, headers=headers or None, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return items
    if isinstance(data, list):
        return data
    raise RuntimeError("Respuesta inesperada del endpoint get_users")


def get_payload_reference(uris: Dict[str, Any], template_name: str) -> Dict[str, Any]:
    templates = uris.get("payload_templates", {})
    if not isinstance(templates, dict):
        raise RuntimeError("'payload_templates' inválido en URIS.json")
    tpl = templates.get(template_name)
    if not isinstance(tpl, dict):
        raise RuntimeError(f"Plantilla '{template_name}' no encontrada en URIS.json")
    ref = tpl.get("reference")
    if not isinstance(ref, dict):
        raise RuntimeError(f"'reference' inválido en plantilla '{template_name}'")
    return copy.deepcopy(ref)


def build_payload(reference: Dict[str, Any], mapped: Dict[str, Any], beneficiary: Dict[str, Any]) -> Dict[str, Any]:
    # Copia profunda para no mutar el template
    payload = json.loads(json.dumps(reference))

    # Valores desde JSON mapeado
    beneficiary_id = mapped.get("id")
    categories = mapped.get("categories") or []
    budget_id = mapped.get("budget_id")
    # Documento del beneficiario como string; aceptar ya renombrado o 'cedula'
    raw_doc = mapped.get("beneficiary_document") if isinstance(mapped, dict) else None
    if not raw_doc:
        raw_doc = mapped.get("cedula") if isinstance(mapped, dict) else None
    beneficiary_document = "" if raw_doc is None else str(raw_doc)

    # Valores desde beneficiary (endpoint)
    contractor_id = None
    contract_id = None
    department_id = None
    municipality_id = None

    contractor = beneficiary.get("contractor") if isinstance(beneficiary, dict) else None
    contract = beneficiary.get("contract") if isinstance(beneficiary, dict) else None
    department = beneficiary.get("department") if isinstance(beneficiary, dict) else None
    municipality = beneficiary.get("municipality") if isinstance(beneficiary, dict) else None

    if isinstance(contractor, dict):
        contractor_id = contractor.get("id")
    if isinstance(contract, dict):
        contract_id = contract.get("id")
    if isinstance(department, dict):
        department_id = department.get("id")
    if isinstance(municipality, dict):
        municipality_id = municipality.get("id")

    # Reemplazar placeholders del template por valores con el tipo correcto
    payload["beneficiary_id"] = beneficiary_id
    payload["contractor_id"] = contractor_id
    payload["contract_id"] = contract_id
    payload["department_id"] = department_id
    payload["municipality_id"] = municipality_id
    payload["categories"] = categories
    payload["update_aiu"] = bool(budget_id is not None)
    # Añadir beneficiary_document para trazabilidad según solicitud
    payload["beneficiary_document"] = beneficiary_document

    return payload


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Construye payloads por archivo usando get_beneficiary y JSONs mapeados.")
    p.add_argument("--mapped-dir", default="output_json_mapped", help="Carpeta con JSONs mapeados (por defecto: output_json_mapped)")
    p.add_argument("--payload-dir", default=None, help="Carpeta de salida de payloads; por defecto se sobreescribe en mapped-dir")
    p.add_argument("--uris", default="URIS.json", help="Ruta a URIS.json (por defecto: URIS.json)")
    p.add_argument("--config", default="config.json", help="Ruta a config.json (por defecto: config.json)")
    p.add_argument("--auth-token", default=None, help="Token Bearer (prioriza sobre config)")
    p.add_argument("--beneficiary-file", default=None, help="Archivo JSON local con un beneficiary para modo offline")
    # Enriquecimiento opcional (uno solo comando)
    p.add_argument("--enrich-users", action="store_true", help="Enriquece con get_users antes de construir payloads")
    p.add_argument("--users-file", default=None, help="Archivo JSON local de get_users para modo offline")
    p.add_argument("--template", default="budget_payload", help="Nombre de la plantilla en URIS.json (por defecto: budget_payload)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    mapped_dir = Path(args.mapped_dir)
    if not mapped_dir.exists():
        print(f"[ERROR] Carpeta no encontrada: {mapped_dir.resolve()}")
        return

    uris = load_uris(Path(args.uris))
    config = load_config(Path(args.config))

    # Token y headers
    cfg_auth = config.get("auth") if isinstance(config, dict) else None
    cfg_token = None
    if isinstance(cfg_auth, dict):
        t = cfg_auth.get("token")
        if isinstance(t, str) and t.strip():
            cfg_token = t.strip()
    token = args.auth_token or cfg_token
    cfg_headers = config.get("headers") if isinstance(config, dict) else None
    extra_headers = {str(k): str(v) for k, v in cfg_headers.items()} if isinstance(cfg_headers, dict) else None

    # Cargar template de referencia
    reference = get_payload_reference(uris, args.template)

    # Cargar beneficiary offline si aplica
    beneficiary_offline: Optional[Dict[str, Any]] = None
    if args.beneficiary_file:
        try:
            beneficiary_offline = load_json(Path(args.beneficiary_file))
            if not isinstance(beneficiary_offline, dict):
                raise RuntimeError("El beneficiary-file debe contener un objeto JSON")
            print(f"[INFO] Usando beneficiary desde archivo local: {args.beneficiary_file}")
        except Exception as e:
            print(f"[ERROR] No se pudo leer beneficiary-file: {e}")
            return

    out_dir = Path(args.payload_dir) if args.payload_dir else mapped_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Si se solicita, preparar mapa de usuarios (get_users) para enriquecer
    user_map: Optional[Dict[str, Dict[str, Any]]] = None
    if args.enrich_users:
        try:
            if args.users_file:
                users_raw = load_json(Path(args.users_file))
                if isinstance(users_raw, dict):
                    users = users_raw.get("items", []) or []
                elif isinstance(users_raw, list):
                    users = users_raw
                else:
                    raise RuntimeError("Formato inválido en users-file")
                print(f"[INFO] Usuarios desde archivo local: {len(users)}")
            else:
                print("[INFO] Consultando endpoint get_users...")
                users = fetch_get_users(uris, token=token, extra_headers=extra_headers)
                print(f"[INFO] Usuarios recibidos: {len(users)}")
            m: Dict[str, Dict[str, Any]] = {}
            for u in users:
                doc = normalize_digits(u.get("document_number"))
                if not doc:
                    continue
                m[doc] = {"budget_id": u.get("budget_id"), "id": u.get("id")}
            user_map = m
        except Exception as e:
            print(f"[WARN] No se pudo preparar el mapa de usuarios: {e}")
            user_map = None

    built = 0
    for p in sorted(mapped_dir.glob("*.json")):
        try:
            mapped = load_json(p)
        except Exception as e:
            print(f"[WARN] No se pudo leer '{p.name}': {e}")
            continue

        # Enriquecimiento por archivo (si aplica): renombrar cedula y setear id/budget_id/exist
        if user_map is not None:
            if "cedula" in mapped and "beneficiary_document" not in mapped:
                try:
                    mapped["beneficiary_document"] = str(mapped.get("cedula") or "")
                    del mapped["cedula"]
                except Exception:
                    mapped["beneficiary_document"] = str(mapped.get("cedula"))
                    mapped.pop("cedula", None)
            ced = normalize_digits(mapped.get("beneficiary_document")) or normalize_digits(mapped.get("cedula"))
            info = user_map.get(ced) if ced else None
            if info:
                mapped["budget_id"] = info.get("budget_id")
                mapped["id"] = info.get("id")
                mapped["exist"] = True
            else:
                mapped.setdefault("budget_id", None)
                mapped.setdefault("id", None)
                mapped["exist"] = False

        # Si no existe el usuario (exist=false), no construir payload
        if mapped.get("exist") is False:
            print(f"[INFO] '{p.name}' exist=false; se omite payload")
            continue

        user_id = mapped.get("id")
        if user_id is None and not beneficiary_offline:
            print(f"[WARN] '{p.name}' no tiene 'id' y no hay beneficiary offline; se omite")
            continue

        # Obtener beneficiary por archivo (online u offline)
        try:
            if beneficiary_offline is not None:
                ben = beneficiary_offline
            else:
                ben = fetch_get_beneficiary(uris, user_id, token=token, extra_headers=extra_headers)
        except Exception as e:
            print(f"[WARN] No se pudo obtener beneficiary para '{p.name}': {e}")
            continue

        payload = build_payload(reference, mapped, ben)
        out_path = out_dir / p.name
        save_json(out_path, payload)
        print(f"[OK] Payload -> {out_path}")
        built += 1

    print(f"[RESUMEN] Payloads generados: {built} en '{out_dir.resolve()}'")


if __name__ == "__main__":
    main()
