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

## Mapeo de códigos/ids con get_chapters

Usa `map_chapters.py` para reemplazar `categories[].codigo` y `subcategories[].id` con los IDs reales del endpoint `get_chapters`.

1) Copia `config.example.json` a `config.json` y pega tu token Bearer:

```json
{
  "auth": { "token": "TU_TOKEN" },
  "headers": { "Accept": "application/json" }
}
```

2) Ejecuta el mapeo (ya está `requests` en `requirements.txt`):

```powershell
python map_chapters.py --input-dir output_json --output-dir output_json_mapped --config config.json --uris URIS.json
```

Notas:
- También puedes pasar `--auth-token` para sobrescribir el token de `config.json`.
- Para pruebas sin red, usa `--chapters-file sample_chapters.json`.
