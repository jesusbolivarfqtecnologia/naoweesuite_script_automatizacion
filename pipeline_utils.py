import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


LOGGER = logging.getLogger("presupuestos")


def configure_logging(log_file: Optional[Path] = None, verbose: bool = False) -> None:
    """Configura salida de consola y, opcionalmente, un archivo de log."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def resolve_auth(config: Dict[str, Any], cli_token: Optional[str]) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
    auth = config.get("auth") if isinstance(config, dict) else None
    config_token = auth.get("token") if isinstance(auth, dict) else None
    token = cli_token.strip() if isinstance(cli_token, str) and cli_token.strip() else None
    if token is None:
        environment_token = os.getenv("NAOWEE_AUTH_TOKEN")
        token = environment_token.strip() if environment_token and environment_token.strip() else None
    if token is None and isinstance(config_token, str) and config_token.strip():
        token = config_token.strip()

    configured_headers = config.get("headers") if isinstance(config, dict) else None
    headers = None
    if isinstance(configured_headers, dict):
        headers = {str(key): str(value) for key, value in configured_headers.items()}
    return token, headers


def merge_headers(endpoint: Dict[str, Any], token: Optional[str], extra_headers: Optional[Dict[str, str]]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    endpoint_headers = endpoint.get("headers")
    if isinstance(endpoint_headers, dict):
        headers.update({str(key): str(value) for key, value in endpoint_headers.items()})
    if extra_headers:
        headers.update(extra_headers)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def clear_json_files(directory: Path) -> int:
    removed = 0
    if not directory.exists():
        return removed
    for path in directory.glob("*.json"):
        if path.is_file() or path.is_symlink():
            path.unlink()
            removed += 1
    return removed
