# Automatizacion de presupuestos

Pipeline Python para convertir presupuestos Excel en payloads JSON y, opcionalmente, enviarlos a la API.

## Requisitos

- Python 3.10 o superior
- Dependencias de `requirements.txt`

Instalacion:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

En Windows:

```bat
.venv\Scripts\pip install -r requirements.txt
```

## Flujo completo

El comando principal extrae los XLSX, mapea capitulos, enriquece beneficiarios y construye payloads. Por seguridad, no envia datos a la API salvo que se indique `--submit`:

```bash
python3 run_all.py
```

Para enviar payloads despues de revisar los resultados:

```bash
python3 run_all.py --submit --clean-output --log-file logs/ejecucion.log
```

Para una ejecucion offline de prueba, proporciona archivos locales para las tres respuestas de API y evita el envio:

```bash
python3 run_all.py \
  --chapters-file sample_chapters.json \
  --users-file sample_users.json \
  --beneficiary-file sample_beneficiary.json \
  --no-submit
```

Opciones utiles:

- `--input-dir`: carpeta de entrada de XLSX.
- `--json-dir`: carpeta de JSON intermedios y payloads finales.
- `--chapters-file`, `--users-file`, `--beneficiary-file`: modo offline.
- `--no-submit`: no realizar solicitudes POST/PUT.
- `--submit`: habilitar explicitamente el envio a la API.
- `--budget-map`: asignar `budget_id` por nombre de archivo.
- `--final-dir`: carpeta separada para payloads finales; por defecto `output_payloads/`.
- `--clean-output`: limpiar salidas JSON antes de iniciar; no se ejecuta implicitamente.
- `--log-file`: guardar eventos de ejecución en un archivo.

## Comandos individuales

```bash
python3 main.py
python3 map_chapters.py --chapters-file sample_chapters.json
python3 enrich_users.py --users-file sample_users.json
python3 build_payloads.py --beneficiary-file sample_beneficiary.json
```

## Configuracion y seguridad

- Copia `config.example.json` a `config.json` y agrega el token localmente.
- Tambien puedes usar la variable de entorno `NAOWEE_AUTH_TOKEN`; tiene prioridad sobre `config.json`.
- `config.json` esta excluido de Git; nunca guardes tokens en el repositorio.
- Si un token fue expuesto, revocalo y genera uno nuevo antes de volver a ejecutar el pipeline.
- Revisa `URIS.json` antes de habilitar el envio. El envio solo se activa con `--submit`; usa `--no-submit` para dejar clara una ejecucion de prueba.

Los archivos de entrada se leen desde `input_xlsx/`. Los JSON intermedios se conservan en `output_json/` y `output_json_mapped/`; los payloads finales se dejan en `output_payloads/`.
