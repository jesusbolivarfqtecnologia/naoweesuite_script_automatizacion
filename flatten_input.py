import argparse
import os
import shutil
from pathlib import Path


def is_temp_excel(name: str) -> bool:
    # Archivos temporales de Excel suelen empezar por ~$
    return name.startswith("~$")


def unique_destination(dir_path: Path, file_name: str) -> Path:
    """Devuelve una ruta única en dir_path para file_name, agregando sufijos _1, _2... si hay colisión."""
    base = Path(file_name).stem
    ext = Path(file_name).suffix
    candidate = dir_path / f"{base}{ext}"
    idx = 1
    while candidate.exists():
        candidate = dir_path / f"{base}_{idx}{ext}"
        idx += 1
    return candidate


def move_excels_to_root(input_root: Path) -> int:
    """Mueve todos los .xlsx de subcarpetas a input_root. Devuelve la cantidad movida."""
    if not input_root.exists():
        print(f"[INFO] La carpeta '{input_root}' no existe. Creándola...")
        input_root.mkdir(parents=True, exist_ok=True)
        return 0

    moved = 0
    # Recorremos recursivamente, pero ignoramos los que ya están en la raíz
    for p in input_root.rglob("*.xlsx"):
        if is_temp_excel(p.name):
            continue
        if p.parent == input_root:
            continue
        dest = unique_destination(input_root, p.name)
        print(f"[MOVE] {p.relative_to(input_root)} -> {dest.name}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(dest))
        moved += 1

    return moved


def remove_empty_dirs(input_root: Path) -> int:
    """Elimina directorios vacíos bajo input_root. Devuelve cuántos borró."""
    removed = 0
    # Caminar de abajo hacia arriba
    for root, dirs, files in os.walk(input_root, topdown=False):
        path_obj = Path(root)
        if path_obj == input_root:
            continue
        # Si no quedan archivos ni subdirectorios
        if not dirs and not files:
            try:
                path_obj.rmdir()
                print(f"[RMDIR] {path_obj.relative_to(input_root)}")
                removed += 1
            except OSError:
                # Si no está vacío por algún motivo, ignorar
                pass
    return removed


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Aplana la estructura de 'input_xlsx', moviendo .xlsx desde subcarpetas a la raíz y borrando carpetas vacías."
        )
    )
    parser.add_argument(
        "--input-dir",
        default="input_xlsx",
        help="Directorio raíz donde se buscarán .xlsx y se moverán a su raíz (por defecto: input_xlsx)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    input_root = Path(args.input_dir)

    moved = move_excels_to_root(input_root)
    removed = remove_empty_dirs(input_root)

    print(f"[RESUMEN] Movidos: {moved} .xlsx | Directorios eliminados: {removed}")


if __name__ == "__main__":
    main()
