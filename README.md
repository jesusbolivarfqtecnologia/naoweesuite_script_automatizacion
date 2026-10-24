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

El comando principal extrae los XLSX, mapea capitulos, enriquece beneficiarios, construye payloads y los envia:

```bash
python3 run_all.py
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
- `--budget-map`: asignar `budget_id` por nombre de archivo.

## Comandos individuales

```bash
python3 main.py
python3 map_chapters.py --chapters-file sample_chapters.json
python3 enrich_users.py --users-file sample_users.json
python3 build_payloads.py --beneficiary-file sample_beneficiary.json
```

## Configuracion y seguridad

- Copia `config.example.json` a `config.json` y agrega el token localmente.
- `config.json` esta excluido de Git; nunca guardes tokens en el repositorio.
- Si un token fue expuesto, revocalo y genera uno nuevo antes de volver a ejecutar el pipeline.
- Revisa `URIS.json` antes de habilitar el envio. El envio esta activo por defecto en `run_all.py`; usa `--no-submit` para pruebas.

Los archivos de entrada se leen desde `input_xlsx/`. Los payloads finales se dejan en `output_json/`.
