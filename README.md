# Extractor de Excel a JSON

Este script procesa múltiples archivos `.xlsx` en una carpeta, leyendo:
- Cédula desde `APU!L6`.
- En la hoja siguiente a `APU`, extrae pares `{codigo, elementos}`:
  - `codigo` en la columna B iniciando en fila 9, y cada 33 filas.
  - `elementos` en el rango `F12:S27`, desplazándose también cada 33 filas.

Los resultados se exportan como archivos JSON numerados consecutivamente en `output_json/`.

## Uso rápido (PowerShell en Windows)

1) Activar el entorno e instalar dependencias:

```powershell
.\mejoramiento\Scripts\activate
python -m pip install -r requirements.txt
```

2) (Opcional) Aplanar la carpeta de entrada si hay subcarpetas con .xlsx:

```powershell
python flatten_input.py --input-dir input_xlsx
```

3) Coloca tus `.xlsx` en `input_xlsx/` (si no lo hiciste en el paso anterior).

4) Ejecutar el extractor:

```powershell
python main.py --input-dir input_xlsx --output-dir output_json
```

Parámetros principales (opcionales):
- `--input-dir` (por defecto `input_xlsx`)
- `--output-dir` (por defecto `output_json`)
- `--steps` (por defecto `33`)
- `--code-col` (por defecto `B`) y `--code-row-start` (por defecto `9`)
- `--elem-col-start` (por defecto `F`) y `--elem-row-start` (por defecto `12`)
- `--elem-col-end` (por defecto `S`) y `--elem-row-end` (por defecto `27`)

Parámetros principales (opcionales) del extractor:
- `--input-dir` (por defecto `input_xlsx`)
- `--output-dir` (por defecto `output_json`)
- `--steps` (por defecto `33`) [solo se usa como respaldo si no se detecta el encabezado]
- `--code-col` (por defecto `B`) y `--code-row-start` (por defecto `9`)
- `--elem-col-start` (por defecto `F`) y `--elem-row-start` (por defecto `12`)
- `--elem-col-end` (por defecto `S`) y `--elem-row-end` (por defecto `27`)
