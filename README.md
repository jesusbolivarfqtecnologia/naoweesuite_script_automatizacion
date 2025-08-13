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

## Enriquecer JSONs con budget_id e id (get_users)

Usa `enrich_users.py` para cruzar por cédula contra `get_users` y actualizar `budget_id`, `id` y la bandera `exist`.

```powershell
python enrich_users.py --mapped-dir output_json_mapped --config config.json --uris URIS.json
# Modo offline
python enrich_users.py --mapped-dir output_json_mapped --users-file sample_users.json
```

Salida: sobreescribe por defecto en `output_json_mapped`. Puedes especificar `--output-dir`.

## Construcción de payloads (get_beneficiary)

Usa `build_payloads.py` para crear un payload por archivo (por defecto sobreescribe en `output_json_mapped`) tomando la plantilla `payload_templates.budget_payload.reference` de `URIS.json`.

Reglas de llenado:
- `beneficiary_id` = `id` del JSON mapeado (proveniente de `get_users`).
- `contractor_id`, `contract_id`, `department_id`, `municipality_id` se obtienen de `get_beneficiary({{user_id}})` donde `{{user_id}}` se reemplaza por el `id` del JSON.
- `categories` se toma del propio JSON mapeado.
- `update_aiu` = `true` si `budget_id` no es null, en caso contrario `false`.
- Si `exist` es `false` (no hubo match de usuario), no se genera payload para ese archivo.

Ejemplos:

```powershell
# Por defecto escribe en la misma carpeta mapped (in-place)
python build_payloads.py --mapped-dir output_json_mapped --config config.json --uris URIS.json
# Modo offline usando un beneficiary de ejemplo
python build_payloads.py --mapped-dir output_json_mapped --beneficiary-file sample_beneficiary.json
# Opcional: enviar a otra carpeta
python build_payloads.py --mapped-dir output_json_mapped --payload-dir output_payloads
```

Notas:
- El campo `cedula` se renombra automáticamente a `beneficiary_document` (string) en los JSON mapeados y se incluye en el payload resultante para trazabilidad.
