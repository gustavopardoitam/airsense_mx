# AirSense MX
**Predicción de calidad del aire 

> Proyecto final Maestría Data Science ITAM | Mayo 2026 | 35% de la nota final

**Autores:** José Antonio Esparza · Gustavo Pardo  
**Repositorio:** https://github.com/gustavopardoitam/airsense_mxc
**App en producción:** 

---

## Descripción Ejecutiva

AirSense MX es un sistema de predicción probabilística de contaminantes atmosféricos (O₃, PM₂.₅, PM₁₀) para la Zona Metropolitana del Valle de México, diseñado para anticipar episodios de contingencia ambiental y facilitar decisiones de salud pública.

**Componentes clave:**
- **Ingesta**: 40+ estaciones SIMAT/RAMA (histórico 2015–2024) + 5 centroides meteorológicos Open-Meteo
- **Predicción**: LightGBM con features meteorológicos y lag autorregresivos (horizonte 1–7 días)
- **Exposición**: Dashboard Streamlit + API Bedrock Haiku para explicaciones NLP
- **Infraestructura**: AWS (S3, Glue, Athena, SageMaker, EC2 t3.small)

---

## Problema de Negocio

La contaminación atmosférica en la ZMVM causa ~13,000 muertes prematuras anuales (OMS). Las contingencias ambientales se declaran reactivamente, *después* de que la contaminación ya es crítica.

**Gap actual:**
- Pronósticos disponibles solo 24–48 horas antes (limitado)
- Sin desglose por zona geográfica (CE, NO, NE, SO, SE)
- Sin APIs accesibles para apps de salud de terceros

**Solución:** Predicciones horarias 7 días adelante, por zona, con explicaciones contextuales.

---

## Usuario Final

1. **Personas vulnerables** (asma, EPOC): Planificar actividades al aire libre
2. **Corredores/deportistas**: Alertas de calidad antes de entrenamientos
3. **Padres de familia**: Decisiones sobre transporte y actividades escolares
4. **Tomadores de decisión** (SEDEMA, PROAIRE): Anticipar contingencias; optimizar medidas de restricción vehicular

---

## Arquitectura del Producto

### Flujo de datos (Medallion Architecture)

```
┌─────────────────────────────────────────────────────────────┐
│ FUENTES                                                     │
├─────────────────────────────────────────────────────────────┤
│ SIMAT/RAMA                 Open-Meteo            PCAA       │
│ (Excel wide, 2015-2024)    (API archive, 2020+) (validación)│
└────────────┬──────────────────┬──────────────────┬──────────┘
             │                  │                  │
             ▼                  ▼                  ▼
┌────────────────────────────────────────────────────────────┐
│ BRONZE                                                    │
│ (Raw JSON/Parquet particionado)                            │
│ s3://airsense-mx/bronze/                                  │
│ ├─ simat/station_id=XXX/year=YYYY/                       │
│ └─ open_meteo/zone=ZZ/year=YYYY/                         │
└────────────────────────┬─────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────┐
│ SILVER                                                    │
│ (Normalizado, timestamps UTC-6, long format)             │
│ s3://airsense-mx/silver/                                 │
│ ├─ contaminantes_horario/ (O3, PM2.5, PM10, NO2, SO2, CO)│
│ └─ meteo_horario/ (temp, humedad, presión, viento, etc) │
└────────────────────────┬─────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────┐
│ GOLD                                                      │
│ (Features + predicciones batch)                           │
│ s3://airsense-mx/gold/                                   │
│ ├─ features_1h/                                          │
│ ├─ predicciones_batch/                                   │
│ └─ shap_explanations/                                    │
└────────────────────────┬─────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────┐
│ APLICACIÓN (Streamlit + Bedrock)                         │
│ ec2-t3-small.compute.amazonaws.com:8501                  │
└────────────────────────────────────────────────────────────┘
```

---

## Stack Tecnológico

| Capa | Herramientas |
|------|-------------|
| **Data** | pandas, pyarrow, awswrangler, sqlalchemy |
| **ML** | lightgbm, scikit-learn, joblib, shap |
| **App** | streamlit, requests, boto3 |
| **Cloud** | AWS S3, Glue, Athena, SageMaker, Bedrock, EC2 |
| **DevOps** | Docker, uv (Python 3.11), pytest, ruff |
| **Config** | YAML, pathlib, frozen dataclasses |

---

## Estructura del Repositorio

```
airsense_mx/
├── README.md                          # este archivo
├── pyproject.toml                     # dependencias uv (determinísticas)
├── uv.lock                            # lock file
├── .github/
│   └── copilot-instructions.md        # estándares de código
├── config.py                          # configuración centralizada (Paths, Thresholds)
├── data/
│   ├── dim_estaciones.csv             # catálogo de estaciones SIMAT (40+)
│   ├── raw/
│   │   ├── openmeteo/                 # Bronze JSON raw
│   │   │   └── station_id=BJU/year=2023/openmeteo_BJU_2023.json
│   │   └── simat/                     # SIMAT Excel
│   ├── processed/                     # Silver parquet
│   └── models/                        # artifacts locales
├── etl/
│   ├── __init__.py
│   ├── __main__.py                    # orchestrator principal
│   ├── openmeteo_bronze.py            # Bronze: ingesta Open-Meteo (por estación/año)
│   ├── bronze.py                      # Bronze: ingesta SIMAT
│   ├── silver.py                      # Silver: normalización, denormalizaciones
│   ├── gold.py                        # Gold: features para ML
│   ├── features.py                    # feature engineering
│   └── test/
│       ├── test_openmeteo_bronze.py   # unit tests, mocks totales
│       ├── test_bronze_open_meteo.py  # legacy tests
│       └── test_prep.py
├── db/
│   ├── __init__.py
│   ├── __main__.py
│   ├── schema.py                      # DDL RDS
│   └── init_db.py                     # init scripts
├── training/
│   ├── __init__.py
│   ├── __main__.py
│   └── train.py                       # LightGBM, temporal split
├── inference/
│   ├── __init__.py
│   ├── __main__.py
│   └── predict.py                     # batch predictions
├── evaluation/
│   ├── __init__.py
│   ├── __main__.py
│   └── evaluate.py                    # validación vs PCAA, SHAP
├── app/
│   ├── main.py                        # entry point Streamlit
│   ├── pages/                         # tabs de navegación
│   └── components/                    # funciones reutilizables
├── utils/
│   ├── logging.py                     # setup centralizado
│   ├── exceptions.py                  # excepciones del dominio
│   └── __init__.py
├── tests/
│   ├── test_smoke.py                  # E2E mínimo
│   └── __init__.py
└── docs/
    ├── architecture/                  # diagramas, ADRs
    ├── datasets/                      # data contracts YAML
    └── runbooks/                      # procedimientos operativos
```

---

## Flujo Medallion

### Bronze: Raw → Structured

**Propósito**: Ingesta cruda, cero transformaciones, máxima trazabilidad.

**Características:**
- Datos particionados por `station_id=XXX/year=YYYY/`
- JSON raw para SIMAT/Open-Meteo, Parquet para validación PCAA
- Metadata envelope: `_metadata` con timestamps, URLs, coordenadas originales vs. snapped
- Idempotente: verifica existencia en S3 antes de sobrescribir

**Ejecución:**
```bash
# RAMA/SIMAT (Excel histórico de contaminantes 2021-presente)
uv run python -m etl.rama_bronze \
  --output-dir data/raw/rama \
  --start-year 2021 \
  --pollutants O3 PM25 PM10 NO2 SO2 CO

# Open-Meteo (JSON meteorológico por estación 2021-presente)
uv run python -m etl.openmeteo_bronze \
  --stations-path data/dim_estaciones.csv \
  --output-dir data/raw/openmeteo \
  --start-year 2021
```

### Silver: Estructura → Semantics

**Propósito**: Normalización, denormalizaciones, validación de NULL.

**Transformaciones:**
- Timestamps UTC-6 consistentes (sin DST)
- Long format: `station_id`, `zone`, `timestamp`, `contaminante`, `valor`
- Denormalización con `dim_estaciones` (lat/lon, municipio, altitud)
- NULL nativo (nunca -99, NaN string, -1)
- Outliers marcados pero conservados (auditoria)

**Schema ejemplo:**
```
contaminantes_horario (Silver)
├── station_id: string (PK)
├── timestamp: timestamp (PK, UTC-6)
├── zone: string
├── contaminante: enum(O3, PM2.5, PM10, NO2, SO2, CO)
├── valor_ppb_o_ugm3: float
├── is_valid: boolean
├── metodo_medicion: string
└── fecha_ingesta: timestamp
```

### Gold: Features → Predictions

**Propósito**: Features ML-ready, predicciones batch, explicaciones.

**Artefactos:**
- Features: lags (6h, 12h, 24h, 48h, 72h), rolling means (12h, 24h)
- Predicciones: `timestamp_prediccion`, `estacion`, `horizon_horas`, `contaminante`, `pred_mean`, `pred_p5`, `pred_p95`
- SHAP values: contribuciones por feature para top-10 features

---

## Ingesta Open-Meteo: Cómo Funciona

### Por Qué Open-Meteo

Open-Meteo provee datos meteorológicos horarios históricos (libre de costos, sin key):
- Cobertura global, grilla ECMWF 9km (~40 km² por celda)
- Variables: temperatura, humedad, presión, viento, radiación, precipitación
- Laguna histórica: 2021-presente
- Complementa SIMAT (que mide contaminantes, no meteorología directa)

### Catálogo de Estaciones: `dim_estaciones.csv`

Central de referencia que vincula estaciones SIMAT con coordenadas:

```
station_id,latitude,longitude,zone,is_active,station_name,municipality
BJU,19.3705,-99.1596,CE,TRUE,Benito Juárez,Benito Juárez
XAL,19.5300,-99.0700,NE,TRUE,Xalostoc,Ecatepec
FES,19.3270,-99.1800,SO,TRUE,FES Acatlán,Cuajimalpa
...
```

**Lógica:**
1. Lee CSV, filtra `is_active = TRUE`
2. Para cada estación + cada año (2021-2026):
   - Extrae `latitude`, `longitude` del CSV
   - Construye llamada Open-Meteo: `https://archive-api.open-meteo.com/v1/archive?latitude=...&longitude=...&start_date=2023-01-01&end_date=2023-12-31&hourly=temperature_2m,humidity_2m,...`
   - Guarda respuesta JSON en: `data/raw/openmeteo/station_id=BJU/year=2023/openmeteo_BJU_2023.json`

### Detalles Técnicos

**Coordenadas: Solicitadas vs. Reales**

Open-Meteo usa grilla ECMWF de 9km. Cuando solicitas (19.3705, -99.1596), se snappea al punto más cercano, p.ej. (19.37, -99.16). Ambas se preservan en metadata:

```json
{
  "_metadata": {
    "_ingested_at": "2025-05-22T14:32:10Z",
    "_zone": "CE",
    "_year": 2023,
    "_latitude_requested": 19.3705,
    "_longitude_requested": -99.1596,
    "_latitude_actual": 19.37,    // snap
    "_longitude_actual": -99.16    // snap
  },
  "latitude": 19.37,
  "longitude": -99.16,
  "hourly": {
    "time": ["2023-01-01T00:00", "2023-01-01T01:00", ...],
    "temperature_2m": [15.2, 14.8, ...]
  }
}
```

**Idempotencia**

Si `data/raw/openmeteo/station_id=BJU/year=2023/openmeteo_BJU_2023.json` ya existe:
- Por defecto: **salta** la descarga (estatus: "skipped")
- Con flag `--overwrite`: descarga nuevamente

Seguro ejecutar múltiples veces sin duplicar datos.

**Manejo de errores**

- Reintentos automáticos con backoff exponencial (3 intentos, 5s entre intentos)
- Si timeout (>60s): log de error, continúa con siguiente zona/año
- Si HTTP 4xx o 5xx: log + estadística de fallo, no aborta pipeline

**Variables descargadas**

```python
HOURLY_VARIABLES = [
    "temperature_2m",              # °C
    "relative_humidity_2m",        # %
    "dewpoint_2m",                 # °C
    "surface_pressure",            # hPa
    "precipitation",               # mm
    "cloud_cover",                 # %
    "shortwave_radiation",         # W/m²
    "wind_speed_10m",              # m/s
    "wind_direction_10m",          # °
    "wind_gusts_10m",              # m/s
]
```

---

## Cómo Correr Localmente

### Requisitos

- **macOS/Linux** (se testing en macOS 13.6+)
- **Python 3.11** (recomendado vía `pyenv`)
- **uv** (gestor de dependencias determinístico)
- **AWS credentials** (`~/.aws/credentials` con permisos S3) — **solo para ETL a cloud**

### Setup Inicial

```bash
# 1. Clonar
git clone https://github.com/airsense-mx/airsense_mx.git
cd airsense_mx

# 2. Instalar dependencias (determinísticas vía uv.lock)
uv sync

# 3. Verificar setup
uv run python --version
uv run which python
```

### Verificación del Ambiente

```bash
# Tests unitarios (debe pasar)
uv run pytest tests/ etl/test/ --cov=etl --cov=utils -v

# Lint
uv run ruff check . && uv run ruff format .

# Type hints (si tienes pyright instalado)
uv run pyright config.py etl/
```

---

## Cómo Correr el ETL Open-Meteo

Descarga datos meteorológicos de Open-Meteo para todas las estaciones activas:

```bash
uv run python -m etl.openmeteo_bronze \
  --stations-path data/dim_estaciones.csv \
  --output-dir data/raw/openmeteo \
  --start-year 2021
```

**Flags opcionales:**
- `--end-year 2024`: Año final (por defecto: año actual)
- `--overwrite`: Fuerza reingesta si ya existen archivos
- `--dry-run`: Descarga sin guardar a disk

**Output esperado:**
```
✓ Descargadas estaciones × años = JSON files
✓ Ubicados en data/raw/openmeteo/station_id=*/year=*/
✓ Metadata incluye coordenadas solicitadas y snap grid ECMWF
✓ Idempotencia: re-ejecutar no duplica datos (skip)
```

---

## Estructura Esperada de Salida

### Local (disk)

```
data/raw/openmeteo/
├── station_id=BJU/
│   ├── year=2021/
│   │   └── openmeteo_BJU_2021.json      (~450 KB, 8760 filas)
│   ├── year=2022/
│   │   └── openmeteo_BJU_2022.json
│   └── year=2023/
│       └── openmeteo_BJU_2023.json
├── station_id=XAL/
│   ├── year=2021/
│   │   └── openmeteo_XAL_2021.json
│   └── ...
└── ...
```

### Cada JSON contiene

```json
{
  "_metadata": {
    "_ingested_at": "2025-05-22T14:32:10+00:00",
    "_source_url": "https://archive-api.open-meteo.com/v1/archive",
    "_zone": "CE",
    "_year": 2023,
    "_hourly_variables": [
      "temperature_2m", "relative_humidity_2m", ...
    ],
    "_latitude_requested": 19.3705,
    "_longitude_requested": -99.1596,
    "_latitude_actual": 19.37,
    "_longitude_actual": -99.16
  },
  "latitude": 19.37,
  "longitude": -99.16,
  "elevation": 2250,
  "generationtime_ms": 42,
  "hourly": {
    "time": [
      "2023-01-01T00:00", "2023-01-01T01:00", ...
    ],
    "temperature_2m": [15.2, 14.8, 14.5, ...],
    "relative_humidity_2m": [72, 75, 78, ...],
    ...
  },
  "hourly_units": {
    "temperature_2m": "°C",
    "relative_humidity_2m": "%",
    ...
  }
}
```

---

## Testing

### Unit Tests (sin I/O real)

```bash
# Todos los tests (mocks totales, sin API, sin S3)
uv run pytest etl/test/ tests/ -v --tb=short

# Test específico
uv run pytest etl/test/test_openmeteo_bronze.py::TestLoadActiveStations -v

# Con cobertura
uv run pytest etl/test/ --cov=etl --cov-report=term-missing
```

**Tests incluyen:**
- Lectura CSV (`load_active_stations`)
- Construcción URLs (`build_openmeteo_url`)
- Manejo de retries
- Idempotencia (skip si existe)
- Validación de coordenadas (requested vs. actual)

### Integration Tests

```bash
# E2E local (requiere data/dim_estaciones.csv existente)
uv run pytest tests/test_smoke.py -v

# Valida:
# - dim_estaciones.csv legible
# - config.py cargable
# - rutas existentes
```

---

## Calidad de Código

### Estándares

Vea [.github/copilot-instructions.md](.github/copilot-instructions.md) para detalles completos.

**Resumen:**
- **Type hints** obligatorios (PEP 484)
- **Google docstrings** en español
- **Ruff** para linting + format (line-length=88)
- **80% cobertura mín** en tests
- **Funciones ≤40 líneas**, responsabilidad única
- **Pathlib**, no `os.path`
- **Dataclasses congeladas** para config

### Comandos

```bash
# Lint
uv run ruff check . --select=E,F,I,B,C4,UP,D

# Format
uv run ruff format . --line-length=88

# Type check (si pyright disponible)
uv run pyright

# Tests + cobertura
uv run pytest --cov=etl --cov=utils --cov-report=html
```

---

## Roadmap

### Fase 1: Bronze ✅ (En progreso)

- [x] Ingesta Open-Meteo (estaciones, 2020-2024)
- [ ] Ingesta SIMAT/RAMA (Excel wide, 2015-2024)
- [ ] Ingesta PCAA (validación)

### Fase 2: Silver (2–3 semanas)

- [ ] Normalización timestamps (UTC-6)
- [ ] Denormalización con `dim_estaciones`
- [ ] Validación de NULL, outliers
- [ ] Tests E2E

### Fase 3: Gold + Predicción (3–4 semanas)

- [ ] Feature engineering (lags, rolling, calendar features)
- [ ] LightGBM baseline + SHAP
- [ ] Evaluación vs. PCAA
- [ ] Batch predictions (6-hourly)

### Fase 4: App + Deployment (2–3 semanas)

- [ ] Dashboard Streamlit (3 tabs: monitoring, forecast, contingency)
- [ ] Bedrock NLP (explicaciones para mortales)
- [ ] Docker image + push ECR
- [ ] Deploy EC2 t3.small + scheduled batch jobs (Glue)

### Fase 5: Producción (Final)

- [ ] CI/CD GitHub Actions
- [ ] Data contracts YAML
- [ ] Runbooks operacionales
- [ ] ADRs (Architecture Decision Records)
- [ ] Documentación técnica completa

---

## Declaración de Uso de IA

Este proyecto fue desarrollado por **humanos**, con **IA asistiendo en tareas específicas**:

✅ **IA usada para:**
- Traducción de docstrings al español (estilo/tono humano)
- Revisión de code style y consistency
- Generación de estructura de README (basado en patrón académico)

❌ **IA NO usada para:**
- Lógica de algoritmos core (ETL, ML)
- Decisiones arquitectónicas
- Código de ingesta/predicción
- Especificaciones de datos

**Principio:** Todo código es original, auditable, y cualquier IA fue solo asistente editorial.

---

## Autores

| Rol | Nombre | Responsabilidad |
|-----|--------|-----------------|
| Lead Data Engineering | Antonio Esparza | Bronze/Silver, Streamlit, Bedrock, Deploy |
| Lead Data Science | Gustavo Robledo | Features, LightGBM, SHAP, Evaluation |

**Advisor:** Dr. [Profesor ITAM]

**Institución:** Instituto Tecnológico Autónomo de México (ITAM)  
**Programa:** Maestría en Data Science  
**Proyecto Final:** Mayo 2026  

---



---

**Last Updated:** 22 de mayo de 2026  
**Status:** 🟡 En desarrollo (Fase 1 completada, Fase 2 en progreso)
