# AirSense MX — Copilot Instructions

> Estándar operativo de ingeniería para el ciclo de vida completo del producto de datos.
> Proyecto final Maestría Data Science ITAM. Última revisión: mayo 2026.

---

## Contexto del proyecto

**Proyecto académico:** AirSense MX es el proyecto final de Antonio y Gustavo, Maestría Data Science ITAM. Vale 35% calificación. Presentación: mayo 24, 2026.

**Producto:** Sistema de predicción calidad del aire para ZMVM. Usuario: persona que decide cada mañana si saca al hijo al parque, corre, suspende actividades. El sistema predice próximos 1-7 días, estima riesgo contingencia por zona, genera explicaciones en lenguaje natural via Bedrock (Claude Haiku).

**Fuentes:** RAMA/SIMAT (O3, PM25, PM10, NO2, SO2, CO años 2015-2024), Open-Meteo (meteorología horaria), PCAA (golden set evaluación).

**Normativa del profesor:**
1. Producto de datos reproducible, automatizado — no análisis
2. Código original del equipo. Copilot asiste pero Antonio lo defiende en presentación
3. Declaración honesta del uso de IA
4. NO copy-paste de código sin entender — Copilot explica decisiones técnicas

<context>
  <stack>Python 3.11, uv, Ruff, pytest. Librerías: pandas, pyarrow, requests, boto3, awswrangler, lightgbm, streamlit. AWS: S3, Glue, Athena, SageMaker, EC2 t3.small, Bedrock. Docker.</stack>
  <architecture>Medallion: Bronze (raw) to Silver (normalized) to Gold (predictions Gustavo)</architecture>
  <deployment>Streamlit en EC2 t3.small (Free Tier) preferente o Fargate. SageMaker Studio para training.</deployment>
  <timezone>UTC-6 CDMX sin DST de punta a punta. Nunca UTC salvo ADR explícito.</timezone>
  <responsibility>Antonio: Bronze, Silver RAMA/meteo, Streamlit, Bedrock, deployment. Gustavo: Silver to Gold, features, training.</responsibility>
</context>

---

## Alcance de Desarrollo

**Antonio (SCOPE COPILOT):**
- Bronze: Ingestión SIMAT/RAMA + Open-Meteo (5 zonas x 5 años)
- Silver: normalización observaciones_horarias + meteo_horario
- dim_estaciones.csv: dimensional
- Streamlit: 3+ tabs, visualizaciones, recomendaciones
- Bedrock Haiku: explicaciones NLP
- Deployment: EC2 t3.small o Fargate
- Arquitectura: documento + diagrama draw.io

**Gustavo (FUERA SCOPE):**
- Silver to Gold: feature engineering, rolling, lags
- Training: LightGBM SageMaker, baseline
- Evaluation: métricas PCAA
- Batch: gold.predicciones_diarias
- Modelo: versionado, SHAP

Este proyecto está construido por ingenieros que piensan en productos, no solo en pipelines. Cada decisión de diseño debe poder justificarse con una de las siguientes frases: **"simplifica el mantenimiento"**, **"mejora la experiencia del usuario"** o **"reduce la deuda técnica**.

Los principios que guían todo el desarrollo son:

- **Mantenibilidad sobre cleverness.** Código que cualquier ingeniero senior puede entender en 10 minutos es mejor que código brillante que nadie puede modificar.
- **Reproducibilidad sin excepciones.** Si un experimento o pipeline no puede reproducirse desde cero con un solo comando, está incompleto.
- **Modularidad desde el diseño.** Cada componente tiene una responsabilidad única y puede probarse de forma aislada.
- **Cloud-native, no cloud-dependent.** La lógica de negocio nunca debe acoplarse directamente a SDKs de AWS; usar abstracciones que permitan tests locales.
- **Observabilidad como ciudadano de primera clase.** Los logs, métricas y alertas no son opcionales; se diseñan junto con el feature, no después.
- **Simplicidad antes que complejidad.** No introducir un patrón de diseño avanzado hasta que el problema simple haya fallado dos veces.
- **Arquitectura desacoplada.** La ingestión no sabe nada de la transformación; el modelo no sabe nada de la UI.
- **Orientado al producto de datos.** El código existe para entregar valor al usuario final, no para satisfacer abstracciones técnicas.

---

## 2. Estándares de Python

### Versión y herramientas

Usar Python 3.11+. Gestión de dependencias exclusivamente con `uv`. Linting y formateo con `Ruff` (configuración en `pyproject.toml`). No usar `black`, `isort` ni `flake8` por separado; Ruff los reemplaza a todos.

### Estilo y estructura

Seguir PEP 8 estrictamente. **Type hints son obligatorios** en todas las funciones y métodos públicos. `from __future__ import annotations` al inicio de cada módulo para compatibilidad de tipos en Python 3.11+. Usar `pathlib.Path` en lugar de `os.path` sin excepciones. Preferir `@dataclass(frozen=True)` para estructuras de configuración inmutables; evitar diccionarios sin tipo cuando el schema es conocido.

Las funciones deben ser pequeñas, puras cuando sea posible y con una sola responsabilidad. Si una función supera las 40 líneas, es candidata a refactoring. Evitar lógica monolítica en scripts de notebook-style; todo código reutilizable va en módulos del paquete.

**Serialización de modelos:** usar siempre `joblib` (no `pickle`). Guardar siempre el modelo `.pkl` junto a su metadata `.json` en `artifacts/models/`.

**Operaciones S3/Glue:** usar `awswrangler` como capa de abstracción sobre `boto3`. No escribir S3 directamente con `boto3.client('s3').put_object()` para datasets tabulares.

```python
# ✅ Correcto
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import awswrangler as wr

@dataclass(frozen=True)
class StationReading:
    station_id: str
    pollutant: str
    value: float
    unit: str

def load_model(model_path: Path) -> tuple:
    """Carga modelo y metadatos del JSON adyacente."""
    model = joblib.load(model_path)
    metadata = json.loads(model_path.with_suffix(".json").read_text())
    return model, metadata

# ❌ Incorrecto
def load(p, y, m):
    import os, pickle
    return pickle.load(open(os.path.join(p, "model.pkl"), "rb"))
```

### Configuración centralizada

Todos los valores configurables (rutas, parámetros de modelo, thresholds de contingencia, nombres de buckets) deben residir en `config.py` en la raíz del proyecto, cargado al inicio. **Cero valores hardcodeados** en el código de negocio.

```python
# config.py — raíz del proyecto
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


def find_repo_root(start: Path) -> Path:
    """Encuentra el root del proyecto buscando pyproject.toml y data/.

    Args:
        start: Ruta base (típicamente __file__).

    Returns:
        Ruta al root del proyecto.

    Raises:
        RuntimeError: Si no se encuentra el root.
    """
    current = start.resolve()
    for _ in range(15):
        if (current / "pyproject.toml").exists() and (current / "data").exists():
            return current
        current = current.parent
    raise RuntimeError(
        "No se encontró el root del proyecto (pyproject.toml + data/). "
        "Ejecuta desde dentro del repositorio."
    )


@dataclass(frozen=True)
class PathsConfig:
    """Rutas estándar del proyecto."""

    repo_root: Path
    data_raw: Path
    data_prep: Path
    artifacts_dir: Path
    logs_dir: Path
    models_dir: Path
    predictions_dir: Path
    reports_dir: Path

    @staticmethod
    def from_repo_root(repo_root: Path) -> PathsConfig:
        """Construye la configuración de rutas a partir del root."""
        artifacts_dir = repo_root / "artifacts"
        return PathsConfig(
            repo_root=repo_root,
            data_raw=repo_root / "data" / "raw",
            data_prep=repo_root / "data" / "prep",
            artifacts_dir=artifacts_dir,
            logs_dir=artifacts_dir / "logs",
            models_dir=artifacts_dir / "models",
            predictions_dir=artifacts_dir / "predictions",
            reports_dir=artifacts_dir / "reports",
        )


@dataclass(frozen=True)
class ContaminantConfig:
    """Parámetros de dominio: thresholds PCAA y configuración de features."""

    # Umbrales NOM-172-SEMARNAT-2019 para contingencia fase I
    pm25_threshold_phase1: float = 150.0
    pm10_threshold_phase1: float = 214.0
    o3_threshold_phase1: float = 155.0
    co_threshold_phase1: float = 15.0

    # Split temporal
    train_quantile_cutoff: float = 0.8

    # Features de serie de tiempo
    lags: tuple[int, ...] = (1, 3, 6, 24)
    rolls: tuple[int, ...] = (8, 24)

    # Target y claves
    target_col: str = "contingency_phase"
    time_col: str = "timestamp"
    station_col: str = "station_id"
    pollutant_col: str = "pollutant"

    # Dataset de salida del ETL
    dataset_filename: str = "gold_features.parquet"
```

### Manejo de excepciones

Usar excepciones específicas, nunca `except Exception` genérico en código de producción. Definir excepciones de dominio en `utils/exceptions.py` para errores esperados del negocio (datos faltantes de estación, contingencia no clasificable, etc.). Las excepciones deben incluir el contexto suficiente para depurar sin necesidad de un debugger: estación, contaminante, rango de fechas afectado.

---

## 3. Docstrings y documentación

### Formato obligatorio: Google Style

Todos los módulos, clases y funciones públicas deben tener docstring en formato Google. No hay excepciones para código que llegue a producción.

```python
def compute_aqi_category(pm25_ugm3: float) -> str:
    """Clasifica la categoría de calidad del aire según PM2.5.

    Usa los umbrales del Índice Metropolitano de la Calidad del Aire (IMECA)
    adaptados para la norma NOM-172-SEMARNAT-2019.

    Args:
        pm25_ugm3: Concentración de PM2.5 en microgramos por metro cúbico.
            Debe ser un valor no negativo.

    Returns:
        Categoría de calidad del aire como string:
        'Buena', 'Aceptable', 'Mala', 'Muy mala', 'Extremadamente mala'.

    Raises:
        ValueError: Si `pm25_ugm3` es negativo.

    Example:
        >>> compute_aqi_category(45.0)
        'Aceptable'
        >>> compute_aqi_category(155.0)
        'Muy mala'
    """
```

### Documentación técnica del proyecto

Cada componente principal del sistema debe tener su propio documento en `docs/`:

- `docs/architecture/` — Diagramas draw.io exportados como SVG + descripción narrativa.
- `docs/datasets/` — Data contracts en YAML con schema, descripción de campos, fuente, frecuencia de actualización y SLAs de calidad.
- `docs/runbooks/` — Procedimientos operativos para incidentes comunes (falla de ingestión, drift de modelo, etc.).
- `docs/adr/` — Architecture Decision Records para decisiones técnicas relevantes.

El `README.md` principal debe ser ejecutivo: explicar el producto en dos párrafos, mostrar cómo correr el proyecto localmente en menos de 5 comandos y referenciar la documentación técnica completa.

---

## 4. Logging y observabilidad

### Configuración del logger

Nunca usar `print()` en código de producción. Usar `logging` estructurado configurado centralmente en `utils/logging.py`.

```python
# utils/logging.py
import logging
import sys

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(module)s | %(message)s"
_LOGGER_INITIALIZED = False


def setup_logging(level: int = logging.INFO) -> None:
    """Configura el logger raíz para logging estructurado compatible con CloudWatch."""
    global _LOGGER_INITIALIZED
    if _LOGGER_INITIALIZED:
        return
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    _LOGGER_INITIALIZED = True


def get_logger(name: str | None = None) -> logging.Logger:
    """Obtiene un logger configurado. Llamar setup_logging() en el entry point."""
    return logging.getLogger(name)


# Uso correcto en módulos
from utils.logging import get_logger
logger = get_logger(__name__)

# ✅ Mensajes accionables con contexto
logger.info("Partición Bronze cargada", extra={"year": 2024, "month": 3, "rows": 8420})
logger.warning("Estación Xalostoc sin datos", extra={"station_id": "XAL", "gap_hours": 6})
logger.error("Fallo en escritura a S3", extra={"bucket": "airsense-bronze", "key": key, "error": str(e)})

# ❌ Mensajes inútiles
logger.info("Procesando...")
logger.error("Error")
```

### Trazabilidad en ETLs y pipelines de inferencia

Cada ejecución de pipeline debe loggear: hora de inicio, fuente de datos, número de registros procesados, registros descartados (con razón), hora de fin y estado final. En inferencia, loggear también: versión del modelo, número de predicciones generadas y si algún threshold de contingencia fue superado.

### Métricas operativas

Exponer métricas operativas clave via CloudWatch: latencia del pipeline, frescura de los datos (horas desde último registro), tasa de valores nulos por estación y contaminante, y drift del modelo cuando esté implementada la evaluación continua.

---

## 5. Estándares ETL — Arquitectura Medallion

### Principios generales

Los pipelines ETL son idempotentes por diseño: ejecutar el mismo pipeline dos veces sobre los mismos datos produce el mismo resultado sin duplicados. La separación entre **ingestión** y **transformación** es estricta; no mezclar lógica de descarga con lógica de limpieza en el mismo módulo.

Cada capa ETL (`bronze.py`, `silver.py`, `gold.py`) define una **whitelist explícita** de archivos a procesar. No se carga nada que no esté en la lista. Esto evita cargar datos corruptos o temporales por accidente.

Para datasets grandes, procesar en **chunks** (500K–1M filas) y liberar memoria explícitamente con `del df` + `gc.collect()` entre chunks. El primer chunk usa `mode="overwrite"`, los siguientes `mode="append"`.

Todas las operaciones S3/Glue se hacen con `awswrangler`. No usar `boto3.client('s3').put_object()` para datos tabulares.

```python
# Patrón estándar en bronze.py / silver.py
import gc
import awswrangler as wr

BRONZE_FILES: list[str] = [
    "rama_simat_2024.parquet",
    "open_meteo_2024.parquet",
    "pcaa_2024.parquet",
]

for i, chunk in enumerate(pd.read_parquet(source, chunksize=500_000)):
    mode = "overwrite" if i == 0 else "append"
    wr.s3.to_parquet(
        df=chunk,
        path=s3_path,
        dataset=True,
        database=GLUE_DATABASE,
        table=table_name,
        mode=mode,
    )
    del chunk
    gc.collect()
```

### Bronze — Raw Data Layer

```
s3://airsense-bronze/
  rama_simat/
    year=2024/month=01/rama_simat_2024_01.parquet
    year=2024/month=02/rama_simat_2024_02.parquet
  open_meteo/
    year=2024/month=01/open_meteo_2024_01.parquet
  pcaa/
    year=2024/month=01/pcaa_2024_01.parquet
```

- Datos en formato **Parquet** con compresión Snappy.
- Particionado por `year` y `month`.
- Schema mínimo: todos los campos de la fuente original + `_ingested_at` (timestamp de ingestión) + `_source_file` (nombre del archivo original).
- **No se aplica ninguna transformación**. Si el dato viene malo, se guarda malo y se documenta.
- Conservar schema explícito en `data_contracts/bronze/`.

### Silver — Curated Layer

Timestamps en hora local CDMX (UTC-6 fijo, sin DST), consistentes en toda la cadena. No convertir a UTC salvo que se documente explícitamente.

- Formato **largo** (tidy data): una fila = una medición de un contaminante en una estación en un momento.
- Valores inválidos tratados con política explícita: nulls para lecturas fuera de rango físico, flag `is_imputed` para interpolaciones.
- Schema documentado en `data_contracts/silver/`.
- Validación automática con `pandera` o contratos de datos YAML.

```python
# Política de tratamiento de valores inválidos
INVALID_THRESHOLDS = {
    "O3": (0, 500),    # ppb — fuera de rango físico
    "PM25": (0, 1000), # µg/m³
    "CO": (0, 100),    # ppm
}

def flag_invalid_readings(df: pd.DataFrame) -> pd.DataFrame:
    """Marca lecturas físicamente imposibles como nulas con trazabilidad."""
```

### Gold — Analytics Layer

- Panel analítico diario por estación: promedios, máximos, percentiles, horas de excedencia por contaminante.
- Features de ingeniería para modelos: rolling windows (1h, 3h, 8h, 24h), lags (t-1, t-3, t-6, t-24), features temporales (hora del día, día de semana, mes, es_fin_de_semana, es_festivo_cdmx).
- Features meteorológicas: temperatura, humedad relativa, velocidad y dirección del viento, presión atmosférica.
- Labels de contingencia: `contingency_phase` (0=sin contingencia, 1=fase I, 2=fase II, 3=doble contingencia).
- Listo para consumo directo por el modelo y por Streamlit.

### Naming conventions para columnas

| Tipo | Convención | Ejemplo |
|------|-----------|---------|
| Contaminante crudo | `{contaminante}_raw` | `pm25_raw` |
| Contaminante limpio | `{contaminante}` | `pm25` |
| Feature rolling | `{contaminante}_rolling_{window}h` | `pm25_rolling_24h` |
| Lag | `{contaminante}_lag_{n}h` | `o3_lag_6h` |
| Label | `{target}_label` | `contingency_label` |
| Flag de calidad | `{campo}_is_valid` | `pm25_is_valid` |

---
## 6. Capa de base de datos (RDS)

### ¿Cuándo usar RDS?

La capa Gold en S3/Athena sirve para el pipeline de ML y el histórico. RDS (PostgreSQL) se usa para los datos que la aplicación Streamlit necesita leer con baja latencia: predicciones recientes, métricas de evaluación y alertas activas.

### Schema con SQLAlchemy

Definir todas las tablas en `db/schema.py` usando SQLAlchemy Core (`Table`, `Column`). No usar ORM; las queries se escriben en SQL plano.

```python
# db/schema.py
from __future__ import annotations
from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, MetaData, String, Table

metadata = MetaData()

stations = Table(
    "stations",
    metadata,
    Column("station_id", String(10), primary_key=True),
    Column("station_name", String(200), nullable=False),
    Column("municipality", String(100), nullable=False),
    Column("lat", Float, nullable=True),
    Column("lon", Float, nullable=True),
)

predictions = Table(
    "predictions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("station_id", String(10), ForeignKey("stations.station_id"), nullable=False),
    Column("pollutant", String(10), nullable=False),
    Column("forecast_date", Date, nullable=False),
    Column("predicted_value", Float, nullable=False),
    Column("actual_value", Float, nullable=True),
    Column("contingency_phase", Integer, nullable=True),
    Column("created_at", DateTime, nullable=False),
)

metrics = Table(
    "metrics",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("pollutant", String(10), nullable=False),
    Column("station_id", String(10), nullable=True),
    Column("n_obs", Integer, nullable=False),
    Column("mae", Float, nullable=False),
    Column("rmse", Float, nullable=False),
    Column("mae_naive", Float, nullable=False),
    Column("rmse_naive", Float, nullable=False),
    Column("computed_at", DateTime, nullable=False),
)
```

### Carga idempotente: DELETE → INSERT

Cada loader (`db/load_predictions.py`, `db/load_metrics.py`) sigue el patrón DELETE→INSERT: borra los registros del período y los recarga. Esto garantiza idempotencia sin necesidad de UPSERT.

### Conexión con `@lru_cache`

La creación del engine SQLAlchemy es costosa. Usar `@lru_cache(maxsize=1)` para reutilizarla dentro del proceso.

```python
# data/rds.py
from __future__ import annotations
from functools import lru_cache
from sqlalchemy import create_engine, text

@lru_cache(maxsize=1)
def get_engine():
    """Crea y cachea el engine de SQLAlchemy para RDS."""
    secret = get_secret("airsense/rds")  # via Secrets Manager
    url = f"postgresql+psycopg://{secret['user']}:{secret['password']}@{secret['host']}/{secret['dbname']}"
    return create_engine(url, pool_pre_ping=True)
```

---
## 7. Estándares ML y Forecasting

### Baseline obligatorio

Todo modelo de producción debe superar un baseline antes de ser considerado candidato para despliegue. El baseline para forecasting de contaminantes es el **último valor observado por estación-contaminante** (naive forecast). Los shop-items sin historial en train usan la media global.

Si el modelo no supera el baseline en al menos un 10% relativo en MAE, se descarta y se documenta la razón.

### Firma estándar del pipeline de entrenamiento

```python
# training/train.py
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from config import ContaminantConfig, find_repo_root
from etl.features import build_features, make_modeling_dataset, temporal_split


def _naive_baseline(
    train_df: pd.DataFrame,
    valid_df: pd.DataFrame,
    cfg: ContaminantConfig,
) -> tuple[float, float]:
    """Baseline naive: último valor observado por (station_id, pollutant)."""
    key_cols = [cfg.station_col, cfg.pollutant_col]
    last_train = (
        train_df.sort_values(cfg.time_col)
        .groupby(key_cols)[cfg.target_col]
        .last()
        .reset_index()
        .rename(columns={cfg.target_col: "naive_pred"})
    )
    df_val = valid_df.merge(last_train, on=key_cols, how="left")
    df_val["naive_pred"] = df_val["naive_pred"].fillna(train_df[cfg.target_col].mean())
    mae = float(mean_absolute_error(df_val[cfg.target_col], df_val["naive_pred"]))
    rmse = float(np.sqrt(mean_squared_error(df_val[cfg.target_col], df_val["naive_pred"])))
    return mae, rmse


def train_pipeline(
    input_parquet: Path,
    output_model: Path,
    cfg: ContaminantConfig | None = None,
) -> dict:
    """Entrena LightGBM y retorna métricas + path del modelo.

    Args:
        input_parquet: Ruta al parquet preparado (gold_features.parquet).
        output_model: Ruta donde guardar el modelo serializado (.pkl).
        cfg: Configuración del modelo. Si es None, usa defaults.

    Returns:
        Dict con mae, rmse, mae_naive, rmse_naive, model_path, n_train, n_val.
    """
    if cfg is None:
        cfg = ContaminantConfig()
    if not Path(input_parquet).exists():
        raise FileNotFoundError(
            f"No existe el dataset preparado: {input_parquet}. "
            "Ejecuta primero python -m etl."
        )
    # ... entrenamiento ...
    # Predicciones no negativas (forzar límite físico)
    y_pred = np.clip(model.predict(x_valid), 0.0, None)
    # Persistir modelo + metadata JSON adyacente
    joblib.dump(model, output_model)
    metadata = {
        "features": feature_cols,
        "mae": mae, "rmse": rmse,
        "mae_naive": mae_naive, "rmse_naive": rmse_naive,
        "n_train": len(train_df), "n_val": len(valid_df),
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    output_model.with_suffix(".json").write_text(json.dumps(metadata, indent=2))
    return {**metadata, "model_path": str(output_model)}
```

### Validación temporal — nunca data leakage

Para series temporales, **prohibido usar `train_test_split` aleatorio**. El split se hace por cuantil sobre la columna de tiempo.

```python
# ✅ Split temporal correcto (en etl/features.py)
def temporal_split(
    df_model: pd.DataFrame, cfg: ContaminantConfig
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split temporal por cuantil del tiempo. Sin data leakage."""
    cutoff = df_model[cfg.time_col].quantile(cfg.train_quantile_cutoff)
    train_df = df_model[df_model[cfg.time_col] <= cutoff].copy()
    valid_df = df_model[df_model[cfg.time_col] > cutoff].copy()
    return train_df, valid_df

# Rolling sin leakage: shift(1) ANTES del rolling
df_mi[f"roll_mean_{w}"] = (
    df_mi.groupby(level=[cfg.station_col, cfg.pollutant_col])[cfg.target_col]
    .shift(1)
    .rolling(window=w, min_periods=w)
    .mean()
)

# ❌ Jamás hacer esto en series temporales
from sklearn.model_selection import train_test_split
X_train, X_test = train_test_split(X, test_size=0.2, random_state=42)
```

### Métricas de evaluación

Para regresión: MAE, RMSE comparados siempre contra el naive baseline. Para clasificación: F1 macro, precisión y recall por clase, matriz de confusión.

### Persistencia y versionado de artefactos

```
artifacts/
  models/
    pm25_forecaster_v1.2.0_2024-12-01.pkl
    pm25_forecaster_v1.2.0_2024-12-01.json   # metadata adyacente
  reports/
    evaluation_pm25_v1.2.0.html
  predictions/
    backtest_pm25_2024-12-01.parquet
```

El `.json` de metadata contiene: `features`, `mae`, `rmse`, `mae_naive`, `rmse_naive`, `n_train`, `n_val`, `trained_at`. Nunca commitear archivos `.pkl` al repositorio.

### Feature engineering reproducible

Todo el feature engineering vive en `etl/features.py` y se importa tanto en `training/train.py` como en `inference/predict.py`. La función `load_model()` en inferencia lee el `.pkl` y su `.json` adyacente para conocer exactamente qué features espera el modelo.

---

## 8. Estándares Streamlit

### Arquitectura de la aplicación

Separar estrictamente la lógica de negocio de la UI. Streamlit solo debe orquestar visualizaciones y llamar funciones importadas; nunca debe contener lógica de transformación de datos inline.

```python
# app/main.py
"""Punto de entrada principal de la aplicación Streamlit de AirSense MX."""

import streamlit as st
from utils.logging import get_logger, setup_logging

from app.pages import dashboard, forecast, contingencias, recomendaciones

_PAGES = {
    "Panel de Calidad del Aire": dashboard,
    "Pronósticos a 24/48/72h": forecast,
    "Riesgo de Contingencia": contingencias,
    "Recomendaciones": recomendaciones,
}


def main() -> None:
    """Inicializa la aplicación y maneja la navegación."""
    setup_logging()
    logger = get_logger(__name__)
    logger.info("Iniciando AirSense MX")

    st.set_page_config(
        page_title="AirSense MX",
        page_icon="🌫️",
        layout="wide",
    )
    st.sidebar.title("AirSense MX")
    page = st.sidebar.radio("Menú", list(_PAGES.keys()))
    logger.info("Página seleccionada: %s", page)
    _PAGES[page].render()


if __name__ == "__main__":
    main()
```

Cada página en `app/pages/` expone exclusivamente una función `render() -> None`. La lógica de acceso a datos va en `app/components/db_helpers.py`.

### UX para usuarios no técnicos

El idioma primario de la interfaz es **español mexicano**. Evitar tecnicismos sin explicación. Los valores numéricos deben acompañarse siempre de una categoría comprensible ("Calidad del aire: **Mala** — Se recomienda evitar actividades al aire libre").

Usar colores semáforo consistentes en toda la aplicación:

```python
CONTINGENCY_COLORS = {
    "Buena":                "#2ECC71",  # Verde
    "Aceptable":            "#F1C40F",  # Amarillo
    "Mala":                 "#E67E22",  # Naranja
    "Muy mala":             "#E74C3C",  # Rojo
    "Extremadamente mala":  "#8E44AD",  # Morado
}
```

### Performance y cache

Usar `@st.cache_data(ttl=300)` para toda consulta a RDS desde `app/components/db_helpers.py`. Las funciones de db_helpers siempre devuelven `pd.DataFrame` y loggean el número de filas.

```python
# app/components/db_helpers.py
from utils.logging import get_logger
logger = get_logger(__name__)

@st.cache_data(ttl=300)
def get_latest_readings() -> pd.DataFrame:
    """Retorna las últimas lecturas por estación y contaminante.

    Returns:
        DataFrame con columnas: station_id, pollutant, value, timestamp, category.
    """
    rows = fetch_query(
        "SELECT station_id, pollutant, value, timestamp, category "
        "FROM readings ORDER BY timestamp DESC LIMIT 1000"
    )
    logger.info("get_latest_readings — %d filas", len(rows))
    return pd.DataFrame(rows)
```

### Manejo de errores visual

Nunca mostrar stack traces al usuario final. Capturar excepciones y mostrar mensajes amigables con opción de reportar.

```python
try:
    df = get_latest_readings()
except DataUnavailableError:
    st.warning("⚠️ Los datos de hoy no están disponibles aún. Mostrando último registro disponible.")
    df = load_latest_available_readings()
```

---

## 9. AWS y Cloud Engineering

### Infraestructura como código

Toda la infraestructura se define en **CloudFormation** en `infra/`. No crear recursos manualmente en la consola de AWS; si se crea manualmente para pruebas, debe ser eliminado y replicado en IaC antes del merge.

Estructura mínima:

```
infra/
  stacks/
    s3_data_lake.yaml
    ecs_fargate_app.yaml
    glue_catalog.yaml
    iam_roles.yaml
    cloudwatch_alarms.yaml
  parameters/
    dev.json
    prod.json
```

### Secretos y credenciales

**Cero credenciales en el código.** Sin excepciones. Usar AWS Secrets Manager para toda credencial de aplicación. Usar IAM Roles para servicios AWS (ECS Tasks, Glue Jobs). El archivo `.env` es solo para desarrollo local y está en `.gitignore`.

```python
# ✅ Correcto — leer secreto desde Secrets Manager
import boto3
import json

def get_secret(secret_name: str, region: str = "us-east-1") -> dict:
    client = boto3.client("secretsmanager", region_name=region)
    response = client.get_secret_value(SecretId=secret_name)
    return json.loads(response["SecretString"])

# ❌ Jamás hacer esto
AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
```

### Separación de ambientes

Los ambientes `dev` y `prod` tienen buckets S3 separados, roles IAM separados y stacks CloudFormation separados. Nunca apuntar código de desarrollo a recursos de producción.

### Principio de mínimo privilegio IAM

Cada componente (ECS Task, Glue Job, Lambda) tiene su propio IAM Role con solo los permisos estrictamente necesarios. Documentar en el código IaC la razón de cada permiso otorgado.

---

## 10. Calidad de código

### Herramientas obligatorias

```toml
# pyproject.toml
[tool.ruff]
line-length = 88
target-version = "py311"
fix = true

[tool.ruff.lint]
select = ["E", "F", "I", "B", "C4", "UP", "D"]

[tool.ruff.lint.pydocstyle]
convention = "google"

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.pytest.ini_options]
testpaths = ["etl/test", "tests"]
```

Ruff debe ejecutarse en pre-commit y en CI. Un PR que no pase el linter no puede ser mergeado.

### Cobertura de tests

Cobertura mínima del **80%** para código en los módulos principales. Los módulos críticos (ETL, feature engineering, inferencia) deben tener cobertura mínima del 90%.

### Métricas de calidad

Antes de marcar un PR como "Ready for Review":
- Ruff sin errores ni warnings.
- Todos los tests pasan en verde.
- Cobertura mínima cumplida.
- Sin secrets detectados por `detect-secrets` o `truffleHog`.
- Complexity ciclomática < 10 por función (medida con `radon`).

---

## 11. Testing

### Estructura de tests

Los tests se organizan en dos niveles:

1. **Co-ubicados con el módulo** — tests unitarios que viven junto al código que prueban.
2. **`tests/` de nivel superior** — tests de integración E2E y validación de contratos de datos.

```
# Tests co-ubicados (unitarios, rápidos)
etl/test/test_prep.py
evaluation/test_evaluate.py
inference/test_predict.py
training/test_train.py
app/components/test_db_helpers.py

# Tests de nivel superior (integración, más lentos)
tests/
  __init__.py
  test_etl_e2e.py
  test_data_contracts.py
```

### Tipos de tests y expectativas

**Unit tests** — probar funciones puras de forma aislada con datos sintéticos controlados. No deben tocar S3, bases de datos ni servicios externos. Se ubican junto al módulo (`test_train.py` al lado de `train.py`).

**Integration tests** — probar pipelines completos con datos de muestra. Pueden usar LocalStack o mocks de boto3. Corren en CI pero son más lentos; pueden excluirse del ciclo de desarrollo local con `pytest -m "not integration"`.

**Smoke tests de ETL** — verifican que los archivos de salida del pipeline existen en `data/prep/`. Son rápidos y corren en CI después del paso ETL:

```python
# etl/test/test_prep.py
from __future__ import annotations
from pathlib import Path

_REPO_ROOT: Path = Path(__file__).resolve().parents[2]
_DATA_PREP: Path = _REPO_ROOT / "data" / "prep"

_EXPECTED_FILES: list[str] = [
    "gold_features.parquet",
    "silver_readings.parquet",
]

def test_prep_files_exist() -> None:
    """Verifica que los archivos de salida del ETL existan en data/prep/."""
    missing = [f for f in _EXPECTED_FILES if not (_DATA_PREP / f).exists()]
    assert not missing, (
        f"Missing {len(missing)} file(s) in {_DATA_PREP}:\n"
        + "\n".join(f"  - {f}" for f in missing)
        + "\nRun the ETL pipeline first."
    )
```

**Smoke tests de training** — verifican la firma y contrato de retorno del pipeline, sin depender de los datos si no están disponibles:

```python
# training/test_train.py
import inspect
import pytest
from pathlib import Path

def test_train_pipeline_importable():
    from training.train import train_pipeline  # noqa: F401

def test_train_pipeline_signature():
    from training.train import train_pipeline
    sig = inspect.signature(train_pipeline)
    assert list(sig.parameters.keys()) == ["input_parquet", "output_model", "cfg"]

def test_train_pipeline_returns_expected_keys(tmp_path):
    from training.train import train_pipeline
    from config import ContaminantConfig, PathsConfig, find_repo_root

    repo_root = find_repo_root(Path(__file__))
    paths = PathsConfig.from_repo_root(repo_root)
    cfg = ContaminantConfig()

    input_parquet = paths.data_prep / cfg.dataset_filename
    if not input_parquet.exists():
        pytest.skip(f"Dataset no disponible: {input_parquet}")

    output_model = tmp_path / "model.pkl"
    result = train_pipeline(input_parquet, output_model, cfg)

    expected = {"mae", "rmse", "mae_naive", "rmse_naive", "model_path", "n_train", "n_val"}
    assert expected == set(result.keys())
    assert output_model.exists()
```

**Unit tests de features** — tests basados en clases con fixtures, verifican lógica pura sin I/O:

```python
# tests/test_features.py
from __future__ import annotations
import pandas as pd
import pytest
from config import ContaminantConfig
from etl.features import build_features, temporal_split


@pytest.fixture
def cfg() -> ContaminantConfig:
    return ContaminantConfig()

@pytest.fixture
def sample_df() -> pd.DataFrame:
    """DataFrame mínimo con 24 horas para una sola (estación, contaminante)."""
    timestamps = pd.date_range("2024-01-01", periods=24, freq="h")
    return pd.DataFrame({
        "station_id": "XAL",
        "pollutant": "pm25",
        "timestamp": timestamps,
        "contingency_phase": range(24),
        "pm25": [float(i) for i in range(24)],
    })


class TestBuildFeatures:
    def test_lag_columns_created(self, sample_df, cfg):
        result = build_features(sample_df, cfg)
        for lag in cfg.lags:
            assert f"pm25_lag_{lag}h" in result.columns

    def test_no_data_leakage_in_rolling(self, sample_df, cfg):
        """Rolling mean debe usar shift(1) — no incluye el valor actual."""
        result = build_features(sample_df, cfg)
        # El rolling de la primera fila válida no puede incluir su propio valor
        assert result["pm25_rolling_8h"].iloc[0] != result["pm25"].iloc[0]
```

**Validación de modelos** — tests que verifican que el modelo cargado desde artefactos supera el baseline antes de ser usado en producción (smoke test de inferencia).

**Tests de base de datos** — `db/test_smoke.py` verifica que todas las tablas del schema pueden crearse; `db/test_loaders.py` verifica que los transformadores de carga producen el schema correcto.

---

## 12. Governance y AI-Assisted Development

### Uso responsable de IA generativa

GitHub Copilot y otras herramientas de IA son asistentes de desarrollo, no autores. Todo código generado por IA debe ser:

1. **Revisado** línea por línea por el autor del PR.
2. **Comprendido** — si el autor no puede explicar por qué funciona, no puede mergearse.
3. **Testeado** — el código generado por IA no está exento de cobertura de tests.
4. **Auditado para seguridad** — especialmente en código que maneja credenciales, acceso a datos o inputs del usuario.

### Prompts reutilizables

Mantener una biblioteca de prompts efectivos para tareas recurrentes en `.github/prompts/`. Ejemplos:

- `etl_module.prompt.md` — genera la estructura de un módulo ETL Bronze→Silver.
- `test_coverage.prompt.md` — genera tests unitarios para una función dada.
- `data_contract.prompt.md` — genera un contrato de datos YAML para un nuevo dataset.

### PR Governance

Todo PR debe:

- Referenciar un issue o ticket.
- Incluir descripción de los cambios en español.
- Pasar todos los checks de CI (lint, tests, seguridad).
- Tener al menos 1 review aprobatorio de otro miembro del equipo.
- No contener más de 400 líneas de cambio neto (PRs grandes se dividen).

### Architecture Governance

Los cambios que afecten la arquitectura del sistema (nueva capa de datos, nuevo servicio AWS, cambio de stack de modelo) requieren un **Architecture Decision Record (ADR)** en `docs/adr/` antes de ser implementados. Un ADR documenta: el contexto, las opciones consideradas, la decisión tomada y las consecuencias esperadas.

---

## 13. Estructura estándar del repositorio

La estructura sigue un diseño **plano y pragmático**: cada directorio es un módulo ejecutable independiente con sus propios tests co-ubicados. No existe un directorio `src/` monolítico; el código compartido vive en `utils/` y la configuración en `config.py` en la raíz.

```
airsense_mx/
├── .github/
│   ├── copilot-instructions.md     # Este archivo
│   ├── prompts/                    # Prompts reutilizables para Copilot
│   └── workflows/                  # CI/CD con GitHub Actions
├── .streamlit/
│   └── config.toml                 # Tema y configuración de Streamlit
├── app/                            # Aplicación Streamlit
│   ├── __init__.py
│   ├── main.py                     # Entry point, navegación
│   ├── components/
│   │   ├── __init__.py
│   │   └── db_helpers.py           # Helpers de acceso a datos para la UI
│   └── pages/
│       ├── 01_dashboard.py         # Panel principal de contaminantes
│       ├── 02_forecast.py          # Predicciones a 24/48/72 horas
│       ├── 03_contingencias.py     # Riesgo de contingencia ambiental
│       └── 04_recomendaciones.py   # Recomendaciones por grupo vulnerable
├── artifacts/                      # Salidas del pipeline (gitignore binarios grandes)
│   ├── logs/
│   ├── models/
│   ├── predictions/
│   └── reports/
├── data/
│   ├── raw/                        # Datos originales sin modificar
│   ├── prep/                       # Datos procesados listos para modelado
│   ├── inference/                  # Inputs/outputs del pipeline de inferencia
│   └── rds.py                      # Engine SQLAlchemy con @lru_cache
├── etl/                            # Pipelines Bronze → Silver → Gold
│   ├── __init__.py
│   ├── __main__.py                 # python -m etl
│   ├── bronze.py                   # Ingestión RAMA/SIMAT y Open-Meteo a S3
│   ├── silver.py                   # Normalización y validación de lecturas
│   ├── gold.py                     # Panel diario, features y labels
│   ├── features.py                 # Feature engineering (rolling, lags, temporales)
│   ├── etl.py                      # Orquestador del pipeline completo
│   └── test/
│       └── test_prep.py
├── evaluation/                     # Evaluación de modelos
│   ├── __init__.py
│   ├── __main__.py
│   ├── evaluate.py
│   └── test_evaluate.py
├── inference/                      # Scoring y predicción en producción
│   ├── __init__.py
│   ├── __main__.py
│   ├── predict.py
│   └── test_predict.py
├── training/                       # Entrenamiento y selección de modelos
│   ├── __init__.py
│   ├── __main__.py
│   ├── train.py
│   └── test_train.py
├── utils/                          # Código compartido
│   ├── logging.py                  # Configuración centralizada de logging
│   └── exceptions.py              # Excepciones de dominio
├── db/                             # Capa de base de datos (RDS)
│   ├── __init__.py
│   ├── __main__.py                 # python -m db
│   ├── schema.py                   # Definiciones SQLAlchemy Core
│   ├── init_db.py                  # CREATE tablas
│   ├── load_all.py                 # Orquestador: catalogs + predictions + metrics
│   ├── load_catalogs.py            # Carga estaciones y contaminantes
│   ├── load_predictions.py         # DELETE→INSERT predicciones
│   ├── load_metrics.py             # DELETE→INSERT métricas de evaluación
│   ├── test_smoke.py               # Verifica que tablas pueden crearse
│   └── test_loaders.py             # Verifica schema de transformadores
├── tests/                          # Tests de integración y contratos de datos
│   ├── __init__.py
│   ├── test_etl_e2e.py
│   └── test_data_contracts.py
├── docs/                           # Documentación técnica
│   ├── arquitectura.drawio
│   ├── arquitectura.md
│   ├── adr/
│   └── runbooks/
├── infra/
│   └── core.yaml                   # CloudFormation: S3, ECS, Glue, IAM, CloudWatch
├── notebooks/                      # Exploración y análisis (no producción)
├── scripts/                        # Utilidades operativas (one-off, diagnóstico)
│   └── check_connections.py
├── config.py                       # PathsConfig + ContaminantConfig
├── .env.example
├── .gitignore
├── Dockerfile
├── uv.lock
├── pyproject.toml
└── README.md
```

### Principios de la estructura

- Cada módulo ejecutable (`etl`, `training`, `evaluation`, `inference`, `db`) tiene su propio `__main__.py` para poder correr como `python -m etl`, `python -m training`, etc.
- Los tests co-ubicados cubren la lógica interna del módulo. El directorio `tests/` de nivel superior contiene únicamente tests de integración E2E y validación de contratos de datos.
- `config.py` en la raíz es el único lugar donde viven rutas, constantes y parámetros configurables. Todos los módulos lo importan.
- `infra/core.yaml` es un único stack CloudFormation que define todos los recursos AWS del proyecto. Si el proyecto escala, se divide en stacks específicos con nombres explícitos.

---

## 14. Naming Conventions

### Archivos y módulos Python

`snake_case` para todos los archivos Python. Nombres semánticos y explícitos que comuniquen propósito, no implementación.

```
# ✅ Correcto
ingest_rama_simat.py
normalize_pollutant_readings.py
engineer_temporal_features.py
evaluate_pm25_forecaster.py

# ❌ Incorrecto
utils2.py
etl_v3_final.py
model_new.py
data.py
```

### Variables y funciones

- Variables: `snake_case`, nombres descriptivos. `station_readings` en lugar de `df` o `data`.
- Constantes: `UPPER_SNAKE_CASE`. `PM25_THRESHOLD_PHASE1 = 150.0`.
- Clases: `PascalCase`. `ContaminantReading`, `ContingencyEvaluator`.
- Funciones: verbos en infinitivo + objeto. `load_bronze_partition()`, `compute_rolling_average()`, `predict_next_24h()`.

### Columnas y campos de datos

Usar nombres en español para columnas que representan conceptos de dominio del negocio en la capa Gold (los que verá el usuario final). Usar inglés para campos técnicos internos.

```python
# Columnas de dominio (Gold, visibles en app)
"estacion", "contaminante", "valor", "unidad", "categoria_calidad", "fase_contingencia"

# Campos técnicos (internal)
"station_id", "pollutant_code", "raw_value", "is_valid", "ingested_at"
```

---

## 15. Estándares de Producto de Datos

### Orientado al usuario, no al dato

El producto no existe para mostrar datos; existe para ayudar a tomar decisiones. Cada visualización debe responder una pregunta concreta de un usuario específico. Antes de construir cualquier feature de la aplicación, definir:

- **¿Quién es el usuario?** (persona vulnerable, ciudadano, tomador de decisión, epidemiólogo).
- **¿Qué decisión necesita tomar?** (¿salgo a correr? ¿cierro las escuelas? ¿activo protocolo de emergencia?).
- **¿Qué información mínima necesita para tomarla?**

### Métricas de negocio sobre métricas técnicas

El modelo no es bueno porque tiene MAE=3.2; es bueno porque detecta el **95% de las contingencias reales con 6 horas de anticipación**. Traducir siempre las métricas técnicas a impacto de negocio en los reportes de evaluación.

### Explicabilidad

Para modelos de alto impacto (predicción de contingencias), incluir explicaciones basadas en SHAP values. El usuario de la app no ve los SHAP values directamente, pero la interfaz debe comunicar: "La calidad del aire empeorará mañana principalmente por altas concentraciones de ozono y viento en calma".

### Outputs accionables

Cada predicción debe acompañarse de una recomendación accionable diferenciada por grupo de usuario:

```python
RECOMMENDATIONS = {
    "Buena": {
        "general": "Condiciones óptimas para actividades al aire libre.",
        "vulnerable": "Sin restricciones adicionales.",
        "deportistas": "Condiciones ideales para ejercicio intenso.",
    },
    "Muy mala": {
        "general": "Evitar actividades físicas prolongadas al aire libre.",
        "vulnerable": "Permanecer en interiores. Consulte a su médico si presenta síntomas.",
        "deportistas": "Suspender entrenamientos al aire libre.",
    },
}
```

### Storytelling de datos

Los dashboards deben guiar al usuario a través de la narrativa del dato, no solo presentar tablas. El orden natural de lectura es: estado actual → tendencia reciente → predicción → recomendación.

---

## Apéndice: Comandos del proyecto

```bash
# Configurar entorno
uv sync

# Lint y formato
uv run ruff check .
uv run ruff format .

# Ejecutar todos los tests
uv run pytest

# Solo tests unitarios (rápido, sin integración)
uv run pytest etl/test/ evaluation/ inference/ training/ -m "not integration"

# Ejecutar módulos individuales
python -m etl
python -m training
python -m evaluation
python -m inference
python -m db

# Construir imagen Docker
docker build -t airsense-mx:local .

# Ejecutar app localmente
uv run streamlit run app/main.py

# Desplegar infraestructura
aws cloudformation deploy \
  --template-file infra/core.yaml \
  --stack-name airsense-dev \
  --capabilities CAPABILITY_NAMED_IAM
```

### Dockerfile de referencia

```dockerfile
# syntax=docker/dockerfile:1.4
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_NO_CACHE_DIR=on

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# uv para resolución determinista de dependencias
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Instalar dependencias desde lockfile (reproducible)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-editable

COPY .streamlit/ .streamlit/
COPY app/ app/
COPY config.py config.py
COPY utils/ utils/
COPY data/ data/

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["uv", "run", "streamlit", "run", "app/main.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
```

---

*Este documento es el estándar de referencia del proyecto. Cualquier desviación debe documentarse y justificarse en el PR correspondiente. Las excepciones no documentadas son deuda técnica.*
