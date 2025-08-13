import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

import requests


def load_uris(uris_path: Path) -> Dict[str, Any]:
    with uris_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_config(config_path: Path) -> Dict[str, Any]:
    """Carga un archivo de configuración opcional. Si no existe, devuelve {}."""
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def fetch_get_chapters(uris: Dict[str, Any], *, token: Optional[str] = None, extra_headers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Obtiene los datos del endpoint get_chapters.

    Devuelve una lista de objetos con llaves: category, id (posible id interno), region, subcategory[].
    Tolera que el endpoint responda un objeto único o una lista de objetos.
    """
    ep = uris.get("endpoints", {}).get("get_chapters")
    if not ep:
        raise RuntimeError("Endpoint 'get_chapters' no encontrado en URIS.json")
    url = ep.get("uri")
    method = (ep.get("method") or "GET").upper()
    if method != "GET":
        raise RuntimeError("El endpoint get_chapters debe ser GET")

    # Headers opcionales
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
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    raise RuntimeError("Respuesta inesperada del endpoint get_chapters")


def build_mappings(chapters: List[Dict[str, Any]]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Construye diccionarios de mapeo.

    - apu_to_subcat_id: '1.10' -> '285865'
    - code_to_category_id: '1' -> '1' (id de category.id en el payload del endpoint)

    Se normalizan los valores de destino a str para mantener el tipo de datos de la estructura original.
    """
    apu_to_subcat_id: Dict[str, str] = {}
    code_to_category_id: Dict[str, str] = {}

    for item in chapters:
        # id externo del item (no confundir con category.id)
        outer_id = item.get("id")
        subcats = item.get("subcategory") or []
        # Deducir el prefijo de código a partir del apu de cualquier subcategoría
        for sc in subcats:
            apu = sc.get("apu")
            sc_id = sc.get("id")
            if apu:
                apu_to_subcat_id[str(apu)] = str(sc_id) if sc_id is not None else None  # type: ignore
                # Prefijo antes del punto
                code_prefix = str(apu).split(".")[0]
                if outer_id is not None:
                    code_to_category_id[code_prefix] = str(outer_id)

    return apu_to_subcat_id, code_to_category_id


def transform_budget_json(data: Dict[str, Any], apu_to_subcat_id: Dict[str, str], code_to_category_id: Dict[str, str]) -> Dict[str, Any]:
    """Aplica el mapeo a la estructura del JSON manteniendo la forma original.

    - categories[*].codigo => reemplazar por code_to_category_id[codigo] si existe (como str)
    - categories[*].subcategories[*].id => reemplazar por apu_to_subcat_id[id] si existe (como str)
    """
    result = json.loads(json.dumps(data))  # copia profunda segura
    categories = result.get("categories") or []
    for cat in categories:
        codigo = cat.get("codigo")
        if codigo is not None:
            mapped = code_to_category_id.get(str(codigo))
            if mapped:
                cat["codigo"] = mapped

        subcats = cat.get("subcategories") or []
        for sc in subcats:
            sc_id = sc.get("id")
            if sc_id is not None:
                mapped_id = apu_to_subcat_id.get(str(sc_id))
                if mapped_id:
                    sc["id"] = mapped_id
    return result


def list_json_files(input_dir: Path) -> List[Path]:
    return sorted([p for p in input_dir.glob("*.json") if p.is_file()])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mapea 'codigo' e 'id' en JSONs generados usando el endpoint get_chapters y escribe a una carpeta nueva."
    )
    parser.add_argument("--input-dir", default="output_json", help="Carpeta con los JSON originales (por defecto: output_json)")
    parser.add_argument(
        "--output-dir",
        default="output_json_mapped",
        help="Carpeta destino para los JSON transformados (por defecto: output_json_mapped)",
    )
    parser.add_argument("--uris", default="URIS.json", help="Ruta al archivo URIS.json (por defecto: URIS.json)")
    parser.add_argument("--config", default="config.json", help="Ruta a archivo de configuración (por defecto: config.json)")
    parser.add_argument("--auth-token", default=None, help="Token para Authorization: Bearer <token> (prioriza sobre config)")
    parser.add_argument("--chapters-file", default=None, help="Ruta a JSON local con la respuesta de get_chapters (modo offline)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    uris_path = Path(args.uris)

    if not input_dir.exists():
        print(f"[ERROR] Carpeta de entrada no existe: {input_dir.resolve()}")
        return

    uris = load_uris(uris_path)
    config_path = Path(args.config)
    config = load_config(config_path)

    # Resolver token y headers (precedencia: CLI > config)
    cfg_auth = config.get("auth") if isinstance(config, dict) else None
    cfg_token: Optional[str] = None
    if isinstance(cfg_auth, dict):
        t = cfg_auth.get("token")
        if isinstance(t, str) and t.strip():
            cfg_token = t.strip()
    token = args.auth_token or cfg_token
    cfg_headers = config.get("headers") if isinstance(config, dict) else None
    extra_headers: Optional[Dict[str, str]] = None
    if isinstance(cfg_headers, dict):
        extra_headers = {str(k): str(v) for k, v in cfg_headers.items()}

    # Modo offline si se provee archivo local
    chapters: List[Dict[str, Any]]
    if args.chapters_file:
        cf = Path(args.chapters_file)
        with cf.open("r", encoding="utf-8") as f:
            raw = json.load(f)
            if isinstance(raw, dict):
                chapters = [raw]
            elif isinstance(raw, list):
                chapters = raw
            else:
                raise RuntimeError("Formato inválido en chapters-file")
        print(f"[INFO] Usando chapters desde archivo local: {cf}")
    else:
        print("[INFO] Consultando endpoint get_chapters...")
        chapters = fetch_get_chapters(uris, token=token, extra_headers=extra_headers)

    apu_to_subcat_id, code_to_category_id = build_mappings(chapters)
    print(f"[INFO] Mapeos: apu->id={len(apu_to_subcat_id)}, code->category_id={len(code_to_category_id)}")

    output_dir.mkdir(parents=True, exist_ok=True)
    files = list_json_files(input_dir)
    if not files:
        print(f"[INFO] No se encontraron JSON en {input_dir.resolve()}")
        return

    transformed = 0
    for p in files:
        try:
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[WARN] No se pudo leer '{p.name}': {e}")
            continue

        new_data = transform_budget_json(data, apu_to_subcat_id, code_to_category_id)
        out_path = output_dir / p.name
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(new_data, f, ensure_ascii=False, indent=2)
        print(f"[OK] Transformado -> {out_path}")
        transformed += 1

    print(f"[RESUMEN] Transformados {transformed} archivos en '{output_dir.resolve()}'")


if __name__ == "__main__":
    main()
