import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string


def leer_cedula(ws_apu) -> Any:
	"""Lee la cédula desde la hoja 'APU' en la celda L6."""
	return ws_apu["L6"].value


def extraer_datos_hoja(
	ws,
	*,
	letra_celda_codigo: str = "B",
	numero_celda_codigo: int = 9,
	letra_celda_inicio_elementos: str = "F",
	numero_celda_inicio_elementos: int = 12,
	letra_celda_fin_elementos: str = "S",
	numero_celda_fin_elementos: int = 27,
	steps: int = 33,
) -> List[Dict[str, Any]]:
	"""
	Recorre la hoja para extraer pares {codigo, elementos}.

	- El primer código está en B9 y los siguientes cada `steps` filas.
	- El primer bloque de elementos está en F12:S27 y los siguientes desplazados `steps` filas.
	Detiene cuando el código en la fila correspondiente es vacío/None.
	"""

	cod_col = letra_celda_codigo.upper()
	elem_c1 = letra_celda_inicio_elementos.upper()
	elem_c2 = letra_celda_fin_elementos.upper()

	elem_c1_idx = column_index_from_string(elem_c1)
	elem_c2_idx = column_index_from_string(elem_c2)

	resultados: List[Dict[str, Any]] = []
	i = 0
	while True:
		code_row = numero_celda_codigo + i * steps
		code_cell = f"{cod_col}{code_row}"
		codigo = ws[code_cell].value

		# Parada: si el código está vacío/None o es una cadena vacía
		if codigo is None or (isinstance(codigo, str) and codigo.strip() == ""):
			break

		elem_r1 = numero_celda_inicio_elementos + i * steps
		elem_r2 = numero_celda_fin_elementos + i * steps

		elementos_bloque = [
			list(row)
			for row in ws.iter_rows(
				min_row=elem_r1,
				max_row=elem_r2,
				min_col=elem_c1_idx,
				max_col=elem_c2_idx,
				values_only=True,
			)
		]

		resultados.append({"codigo": codigo, "elementos": elementos_bloque})
		i += 1

	return resultados


def procesar_archivo(
	xlsx_path: Path,
	*,
	letra_celda_codigo: str,
	numero_celda_codigo: int,
	letra_celda_inicio_elementos: str,
	numero_celda_inicio_elementos: int,
	letra_celda_fin_elementos: str,
	numero_celda_fin_elementos: int,
	steps: int,
) -> Optional[Dict[str, Any]]:
	"""Procesa un archivo .xlsx y devuelve un dict listo para exportar a JSON.

	Estructura devuelta:
	{
	  "archivo": nombre_base.xlsx,
	  "cedula": valor_de_APU_L6,
	  "datos": [ {"codigo": ..., "elementos": [[...], ...]}, ... ]
	}
	"""
	try:
		wb = load_workbook(filename=str(xlsx_path), data_only=True)
	except Exception as exc:
		print(f"[ERROR] No se pudo abrir '{xlsx_path.name}': {exc}")
		return None

	if "APU" not in wb.sheetnames:
		print(f"[ADVERTENCIA] Hoja 'APU' no encontrada en '{xlsx_path.name}'. Se omite.")
		return None

	apu_index = wb.sheetnames.index("APU")
	apu_ws = wb["APU"]
	cedula = leer_cedula(apu_ws)

	# Hoja siguiente a APU
	next_index = apu_index + 1
	if next_index >= len(wb.sheetnames):
		print(f"[ADVERTENCIA] No existe hoja siguiente a 'APU' en '{xlsx_path.name}'. Se omite.")
		return None

	next_sheet_name = wb.sheetnames[next_index]
	ws_target = wb[next_sheet_name]

	datos = extraer_datos_hoja(
		ws_target,
		letra_celda_codigo=letra_celda_codigo,
		numero_celda_codigo=numero_celda_codigo,
		letra_celda_inicio_elementos=letra_celda_inicio_elementos,
		numero_celda_inicio_elementos=numero_celda_inicio_elementos,
		letra_celda_fin_elementos=letra_celda_fin_elementos,
		numero_celda_fin_elementos=numero_celda_fin_elementos,
		steps=steps,
	)

	return {
		"archivo": xlsx_path.name,
		"hoja_objetivo": next_sheet_name,
		"cedula": cedula,
		"datos": datos,
	}


def siguiente_consecutivo(output_dir: Path) -> int:
	"""Calcula el siguiente consecutivo basado en archivos N.json existentes."""
	max_n = 0
	for p in output_dir.glob("*.json"):
		name = p.stem
		if name.isdigit():
			n = int(name)
			if n > max_n:
				max_n = n
	return max_n + 1


def guardar_json_con_consecutivo(output_dir: Path, data: Dict[str, Any]) -> Path:
	output_dir.mkdir(parents=True, exist_ok=True)
	n = siguiente_consecutivo(output_dir)
	out_path = output_dir / f"{n}.json"
	with out_path.open("w", encoding="utf-8") as f:
		json.dump(data, f, ensure_ascii=False, indent=2)
	return out_path


def listar_excels(input_dir: Path) -> List[Path]:
	"""Lista archivos .xlsx válidos (excluye temporales ~) en input_dir."""
	if not input_dir.exists():
		input_dir.mkdir(parents=True, exist_ok=True)
	return [p for p in input_dir.glob("*.xlsx") if not p.name.startswith("~$")]


def parse_args():
	parser = argparse.ArgumentParser(
		description=(
			"Extrae cédula de APU!L6 y pares {código, elementos} de la hoja siguiente a APU, "
			"para múltiples .xlsx y exporta JSON consecutivos."
		)
	)
	parser.add_argument(
		"--input-dir",
		default="input_xlsx",
		help="Carpeta con los .xlsx a procesar (por defecto: input_xlsx)",
	)
	parser.add_argument(
		"--output-dir",
		default="output_json",
		help="Carpeta donde se guardarán los JSON (por defecto: output_json)",
	)
	parser.add_argument("--steps", type=int, default=33, help="Número de filas entre bloques (por defecto: 33)")
	parser.add_argument("--code-col", default="B", help="Columna del código (por defecto: B)")
	parser.add_argument("--code-row-start", type=int, default=9, help="Fila inicial del código (por defecto: 9)")
	parser.add_argument("--elem-col-start", default="F", help="Columna inicial del rango de elementos (por defecto: F)")
	parser.add_argument("--elem-row-start", type=int, default=12, help="Fila inicial del rango de elementos (por defecto: 12)")
	parser.add_argument("--elem-col-end", default="S", help="Columna final del rango de elementos (por defecto: S)")
	parser.add_argument("--elem-row-end", type=int, default=27, help="Fila final del rango de elementos (por defecto: 27)")
	return parser.parse_args()


def main():
	args = parse_args()

	input_dir = Path(args.input_dir)
	output_dir = Path(args.output_dir)

	excels = listar_excels(input_dir)
	if not excels:
		print(
			f"[INFO] No se encontraron .xlsx en '{input_dir.resolve()}'. "
			f"Coloca tus archivos allí y vuelve a ejecutar."
		)
		return

	print(f"[INFO] Archivos a procesar: {len(excels)} en '{input_dir.resolve()}'")

	procesados = 0
	for xlsx in sorted(excels):
		print(f"[INFO] Procesando: {xlsx.name}")

		data = procesar_archivo(
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

		out_path = guardar_json_con_consecutivo(output_dir, data)
		print(f"[OK] Exportado: {out_path}")
		procesados += 1

	print(f"[RESUMEN] Exportados {procesados} JSON en '{output_dir.resolve()}'")


if __name__ == "__main__":
	main()

