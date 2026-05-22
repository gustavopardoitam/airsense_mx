# AirSense MX — Copilot Instructions

> Proyecto final Maestría Data Science ITAM, mayo 2026.
> Sistema de predicción de calidad del aire para ZMVM.

---

## Contexto

**Producto:** Predicción de contaminantes (O3, PM2.5, PM10, NO2, SO2, CO) próximos 1-7 días para ZMVM.

**Datos:** SIMAT/RAMA (2015-2024), Open-Meteo (5 centroides x zona), PCAA (validación).

**Equipo:** Antonio (Bronze/Silver/Streamlit/Bedrock), Gustavo (Features/Training/Gold).

**Estándares:** Reproducible + automatizado, código original, IA documentada, sin copy-paste. 



## Scope

**Antonio:**
- Bronze: SIMAT + Open-Meteo → JSON/Parquet (5 zonas, 5 años)
- Silver: Normalizar timestamps (UTC-6), long format, validar
- Streamlit: 3+ tabs (dashboard, forecast, contingencias)
- Bedrock: NLP explicaciones
- Deployment: EC2 t3.small

**Gustavo:**
- Features + training
- LightGBM + SHAP
- Gold batch predictions


## Stack

- **Python 3.11** con `uv` (lock file determinístico)
- **Linting:** Ruff (type hints obligatorios, Google docstrings, line-length=88)
- **Testing:** pytest + mock (80% cobertura mín)
- **Data:** pandas, pyarrow, awswrangler, sqlalchemy
- **ML:** lightgbm, scikit-learn, joblib
- **App:** streamlit, requests
- **AWS:** S3, Glue, Athena, SageMaker, EC2 t3.small, Bedrock, RDS
- **Deployment:** Docker

## Python — Obligatorio

- **Type hints** en todas las funciones públicas
- **`from __future__ import annotations`** en cada módulo
- **Google docstrings** para funciones, clases, módulos públicos
- **`pathlib.Path`** no `os.path`
- **Dataclasses congeladas** para config: `@dataclass(frozen=True)`
- **joblib** para modelos, **awswrangler** para S3
- Funciones pequeñas (máx 40 líneas), puras, responsabilidad única
- PEP 8 estricto, sin lógica en notebooks


## Configuración centralizada

Todo en `config.py`: rutas, constantes, PCAA thresholds. Cero hardcodeado.

```python
@dataclass(frozen=True)
class PathsConfig:
    data_raw: Path
    data_prep: Path

@dataclass(frozen=True)
class ContaminantConfig:
    pm25_threshold_phase1: float = 150.0
```

---

## Logging y Observabilidad

Centralizado en `utils/logging.py`. Nunca `print()` en producción.

```python
from utils.logging import get_logger
logger = get_logger(__name__)
logger.info("Datos cargados", extra={"rows": 1000, "zone": "CE"})
```

**Principio:** Logs con contexto suficiente para depurar sin debugger. Loggear: inicio de pipeline, registros procesados, descartados (razón), fin, estado.

## ETL — Medallion

Bronze → Silver → Gold

- **Bronze:** Raw JSON/Parquet, particionado año/mes
- **Silver:** Limpio, timestamps UTC-6, long format, NULL válido
- **Gold:** Features + predicciones (Gustavo)

**Idempotencia:** Bronze skip si existe, Silver DELETE+INSERT período

**Timezone:** UTC-6 CDMX sin DST. Nunca UTC.

**Datos:** Parquet + Snappy. NULL nativo (no -99, NaN, "")

## Testing

- **Unit:** Junto al módulo (`etl/test/test_*.py`), mocks totales
- **Integration:** `tests/` nivel superior
- **Cobertura:** 80% mín, críticos 90%

```bash
uv run pytest                    # todos
uv run ruff check . && uv run ruff format .  # lint
```

## ML + Inference

- **Baseline:** Naive (último valor). Modelo debe +10% sobre baseline
- **Split:** Temporal por cuantil (nunca aleatorio)
- **Métricas:** MAE, RMSE vs naive
- **Artefactos:** `artifacts/models/{nombre}_v{version}.pkl` + `.json` metadata adyacente

## Documentación Técnica

Cada componente principal debe tener su propio documento en `docs/`:

- `docs/architecture/` — Diagramas draw.io + narrativa
- `docs/datasets/` — Data contracts YAML: schema, campos, fuente, SLAs
- `docs/runbooks/` — Procedimientos operativos (falla ingestión, drift modelo)
- `docs/adr/` — Architecture Decision Records

`README.md`: ejecutivo (2 párrafos), setup en <5 comandos, link a docs.

## Naming Conventions

**Columnas:**
| Tipo | Convención | Ejemplo |
|------|-----------|---------|
| Contaminante crudo | `{contaminante}_raw` | `pm25_raw` |
| Contaminante limpio | `{contaminante}` | `pm25` |
| Feature rolling | `{contaminante}_rolling_{window}h` | `pm25_rolling_24h` |
| Lag | `{contaminante}_lag_{n}h` | `o3_lag_6h` |
| Label | `{target}_label` | `contingency_label` |
| Flag validez | `{campo}_is_valid` | `pm25_is_valid` |

**Variables/Funciones:** `snake_case` descriptivo. Constantes: `UPPER_SNAKE_CASE`. Clases: `PascalCase`.

## Estructura del Proyecto

- Módulos ejecutables (`etl`, `training`, `inference`, `db`) con `__main__.py`: `python -m etl`
- Tests co-ubicados (`etl/test/`, `training/test_*.py`) para unitarios
- `tests/` nivel superior: integración E2E + contratos
- `config.py` raíz: único lugar para rutas, constantes, parámetros
- `utils/`: código compartido (logging, excepciones)
- `infra/core.yaml`: CloudFormation único (escalar = dividir en stacks)

## Streamlit

**Idioma primario:** Español mexicano. Evitar tecnicismos. Valores + categoría: "Calidad: **Mala** — Evitar actividades al aire libre".

**Colores semáforo:**
```python
{
    "Buena": "#2ECC71", "Aceptable": "#F1C40F", "Mala": "#E67E22",
    "Muy mala": "#E74C3C", "Extremadamente mala": "#8E44AD",
}
```

**Arquitectura:** `app/main.py` → `app/pages/` (cada página con `render()`). Lógica en `app/components/` + `data/`. Cache: `@st.cache_data(ttl=300)`. Errores: mensajes amigables, nunca stack traces.

## Comandos

```bash
uv sync                              # install deps
uv run pytest                        # run tests
uv run ruff check . && uv run ruff format .  # lint
python -m etl                        # run Bronze→Silver→Gold
uv run streamlit run app/main.py     # dev app
```

