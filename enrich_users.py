import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def normalize_digits(x: Any) -> str:
    s = "" if x is None else str(x)
    return re.sub(r"\D+", "", s)


def load_uris(uris_path: Path) -> Dict[str, Any]:
    return load_json(uris_path)


def load_config(config_path: Path) -> Dict[str, Any]:
    if not config_path.exists():
        return {}
    return load_json(config_path)


def fetch_get_users(uris: Dict[str, Any], *, token: Optional[str] = None, extra_headers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
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
    # Esperamos { items: [...] }
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return items
    # Alternativa: si retorna lista directamente
    if isinstance(data, list):
        return data
    raise RuntimeError("Respuesta inesperada del endpoint get_users")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Enriquece JSONs mapeados con budget_id e id desde get_users, emparejando por cédula.")
    p.add_argument("--mapped-dir", default="output_json_mapped", help="Carpeta con JSONs mapeados a actualizar (por defecto: output_json_mapped)")
    p.add_argument("--uris", default="URIS.json", help="Ruta a URIS.json (por defecto: URIS.json)")
    p.add_argument("--config", default="config.json", help="Ruta a config.json (por defecto: config.json)")
    p.add_argument("--auth-token", default=None, help="Token Bearer (prioriza sobre config)")
    p.add_argument("--users-file", default=None, help="Archivo JSON local con respuesta de get_users para modo offline")
    p.add_argument("--output-dir", default=None, help="Carpeta de salida; si no se especifica, sobreescribe en mapped-dir")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    mapped_dir = Path(args.mapped_dir)
    if not mapped_dir.exists():
        print(f"[ERROR] Carpeta no encontrada: {mapped_dir.resolve()}")
        return

    uris = load_uris(Path(args.uris))
    config = load_config(Path(args.config))
    cfg_auth = config.get("auth") if isinstance(config, dict) else None
    cfg_token = None
    if isinstance(cfg_auth, dict):
        t = cfg_auth.get("token")
        if isinstance(t, str) and t.strip():
            cfg_token = t.strip()
    token = args.auth_token or cfg_token
    cfg_headers = config.get("headers") if isinstance(config, dict) else None
    extra_headers = {str(k): str(v) for k, v in cfg_headers.items()} if isinstance(cfg_headers, dict) else None

    # Obtener usuarios
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

    # Construir mapa por cédula (document_number)
    user_map: Dict[str, Dict[str, Any]] = {}
    for u in users:
        doc = normalize_digits(u.get("document_number"))
        if not doc:
            continue
        user_map[doc] = {
            "budget_id": u.get("budget_id"),
            "id": u.get("id"),
        }

    out_dir = Path(args.output_dir) if args.output_dir else mapped_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    updated = 0
    for p in sorted(mapped_dir.glob("*.json")):
        try:
            data = load_json(p)
        except Exception as e:
            print(f"[WARN] No se pudo leer '{p.name}': {e}")
            continue

        # Renombrar 'cedula' -> 'beneficiary_document' como string
        if "cedula" in data and "beneficiary_document" not in data:
            try:
                data["beneficiary_document"] = str(data.get("cedula") or "")
                del data["cedula"]
            except Exception:
                data["beneficiary_document"] = str(data.get("cedula"))
                data.pop("cedula", None)

        ced = normalize_digits(data.get("beneficiary_document")) or normalize_digits(data.get("cedula"))
        info = user_map.get(ced)

        # Asegurar llaves presentes; si no hay match, se establecen en null
        if info:
            data["budget_id"] = info.get("budget_id")
            data["id"] = info.get("id")
            data["exist"] = True
        else:
            data.setdefault("budget_id", None)
            data.setdefault("id", None)
            data["exist"] = False

    out_path = out_dir / p.name
    save_json(out_path, data)
    print(f"[OK] Actualizado -> {out_path}")
    updated += 1

    print(f"[RESUMEN] Archivos actualizados: {updated} en '{out_dir.resolve()}'")


if __name__ == "__main__":
    main()
