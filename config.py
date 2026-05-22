"""AirSense MX — Configuración centralizada del proyecto.

Define rutas del repositorio, parámetros de modelo y umbrales de dominio.
Todos los módulos importan esta configuración en lugar de hardcodear valores.

Uso:
    from config import (
        PathsConfig, ContaminantConfig, S3Config,
        calcular_semaforo, find_repo_root,
    )

    repo_root = find_repo_root(Path(__file__))
    paths = PathsConfig.from_repo_root(repo_root)
    cfg = ContaminantConfig()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


# =============================================================================
# RESOLUCIÓN DEL ROOT DEL REPOSITORIO
# =============================================================================

def find_repo_root(start: Path) -> Path:
    """Encuentra el root del proyecto buscando pyproject.toml y data/.

    Args:
        start: Ruta base (típicamente __file__).

    Returns:
        Ruta al root del proyecto.

    Raises:
        RuntimeError: Si no se encuentra el root después de 15 directorios.
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


# =============================================================================
# RUTAS LOCALES DEL PROYECTO
# =============================================================================

@dataclass(frozen=True)
class PathsConfig:
    """Rutas estándar locales del proyecto (inmutable)."""

    repo_root: Path
    data_raw: Path
    data_prep: Path
    data_inference: Path
    artifacts_dir: Path
    logs_dir: Path
    models_dir: Path
    predictions_dir: Path
    reports_dir: Path

    @staticmethod
    def from_repo_root(repo_root: Path) -> PathsConfig:
        """Construye la configuración de rutas a partir del root.

        Args:
            repo_root: Ruta al root del proyecto.

        Returns:
            PathsConfig con todas las rutas configuradas.
        """
        artifacts_dir = repo_root / "artifacts"
        return PathsConfig(
            repo_root=repo_root,
            data_raw=repo_root / "data" / "raw",
            data_prep=repo_root / "data" / "prep",
            data_inference=repo_root / "data" / "inference",
            artifacts_dir=artifacts_dir,
            logs_dir=artifacts_dir / "logs",
            models_dir=artifacts_dir / "models",
            predictions_dir=artifacts_dir / "predictions",
            reports_dir=artifacts_dir / "reports",
        )


# =============================================================================
# RUTAS S3 (DATA LAKE MEDALLION)
# =============================================================================

@dataclass(frozen=True)
class S3Config:
    """Rutas del data lake en S3 con arquitectura Medallion.

    Bronze: archivos crudos (RAMA wide, JSONs Open-Meteo, PDFs PCAA)
    Silver: tablas normalizadas en Parquet
    Gold: predicciones del modelo listas para Streamlit/Athena
    """

    bucket: str = "airsense-mx"

    @property
    def bronze_rama(self) -> str:
        return f"s3://{self.bucket}/bronze/rama/"

    @property
    def bronze_openmeteo(self) -> str:
        return f"s3://{self.bucket}/bronze/openmeteo/"

    @property
    def bronze_pcaa(self) -> str:
        return f"s3://{self.bucket}/bronze/pcaa/"

    @property
    def silver_obs(self) -> str:
        return f"s3://{self.bucket}/silver/observaciones_horarias/"

    @property
    def silver_meteo(self) -> str:
        return f"s3://{self.bucket}/silver/meteo_horario/"

    @property
    def gold_predicciones(self) -> str:
        return f"s3://{self.bucket}/gold/predicciones_diarias/"

    @property
    def dim_estaciones(self) -> str:
        return f"s3://{self.bucket}/dim/dim_estaciones.csv"

    @property
    def models(self) -> str:
        return f"s3://{self.bucket}/models/"


# Catálogo Glue
GLUE_DATABASES = {
    "silver": "airsense_silver",
    "gold": "airsense_gold",
}


# =============================================================================
# PARÁMETROS DE DOMINIO: UMBRALES Y FEATURES
# =============================================================================

@dataclass(frozen=True)
class ContaminantConfig:
    """Parámetros de dominio: umbrales PCAA y configuración de features.

    Umbrales del Programa de Contingencias Ambientales Atmosféricas (PCAA)
    de la Zona Metropolitana del Valle de México, publicados por la
    Secretaría del Medio Ambiente de la CDMX.

    IMPORTANTE: estos NO son los umbrales de la NOM-172-SEMARNAT-2019
    (que es la norma federal de información a población general). El PCAA
    usa umbrales más estrictos para activar contingencias en la ZMVM.

    Fuente: tabla oficial PCAA-SEDEMA (Umbral 1 Actualizado).
    """

    # -------- Umbrales PCAA para contingencia Fase I --------
    # Ozono: pico horario máximo del día
    o3_threshold_ppb: float = 140.0       # max 1h
    # Dióxido de nitrógeno: pico horario máximo del día
    no2_threshold_ppb: float = 188.0      # max 1h
    # Dióxido de azufre: pico horario máximo del día
    so2_threshold_ppb: float = 185.0      # max 1h
    # PM2.5: promedio móvil 24 horas
    pm25_threshold_ugm3: float = 79.0     # avg 24h
    # PM10: promedio móvil 24 horas
    pm10_threshold_ugm3: float = 146.0    # avg 24h
    # CO: no aplica para contingencia PCAA

    # -------- Split temporal para train/valid --------
    train_quantile_cutoff: float = 0.8

    # -------- Features de serie de tiempo (granularidad diaria) --------
    # Lags útiles para predecir el pico/promedio diario del próximo día.
    # NOTA: estos son lags en DÍAS, no en horas. Gold es diario.
    lags_dias: tuple[int, ...] = (1, 3, 7, 14)
    # Ventanas para rolling means y rolling stds, también en días.
    rolls_dias: tuple[int, ...] = (7, 30)

    # -------- Nombres de columnas estándar --------
    target_col: str = "contingency_phase"
    time_col: str = "timestamp"
    date_col: str = "fecha"
    station_col: str = "station_id"
    zone_col: str = "zone"
    pollutant_col: str = "contaminante"

    # -------- Dataset de salida del ETL --------
    dataset_filename: str = "gold_features.parquet"


# =============================================================================
# CATÁLOGO DE UMBRALES (para uso programático)
# =============================================================================

# Diccionario de umbrales con metadata, útil para iterar sobre contaminantes
# y construir labels o features sin hardcodear valores.
UMBRALES_PCAA = {
    "O3":   {"valor": 140.0, "unidad": "ppb",   "ventana": "max_1h"},
    "NO2":  {"valor": 188.0, "unidad": "ppb",   "ventana": "max_1h"},
    "SO2":  {"valor": 185.0, "unidad": "ppb",   "ventana": "max_1h"},
    "PM25": {"valor":  79.0, "unidad": "ug/m3", "ventana": "avg_24h"},
    "PM10": {"valor": 146.0, "unidad": "ug/m3", "ventana": "avg_24h"},
}

# Contaminantes para los que GENERAMOS predicciones en Gold (v1.0)
CONTAMINANTES_PREDECIBLES = ["O3", "PM25", "PM10"]

# Todos los contaminantes que ingerimos en Silver (incluye los que solo son features)
CONTAMINANTES_INGESTADOS = ["O3", "NO2", "SO2", "PM10", "PM25", "CO"]


# =============================================================================
# ZONAS OFICIALES DE LA ZMVM
# =============================================================================

ZONAS_VALIDAS = frozenset({"NO", "NE", "SE", "SO", "CE"})

ZONA_NOMBRES = {
    "NO": "Noroeste",
    "NE": "Noreste",
    "SE": "Sureste",
    "SO": "Suroeste",
    "CE": "Centro",
}


# =============================================================================
# FUNCIÓN OFICIAL DE SEMÁFORO
# =============================================================================

def calcular_semaforo(valor_predicho: float, umbral: float) -> str:
    """Devuelve el nivel de alerta según el valor predicho vs umbral.

    Esta es la única autoridad sobre cómo se calcula el semáforo en el
    proyecto. Tanto el modelo (al escribir gold.predicciones_diarias) como
    Streamlit (al colorear el mapa) importan esta función.

    Args:
        valor_predicho: valor del contaminante en su unidad nativa.
        umbral: umbral de contingencia PCAA para ese contaminante.

    Returns:
        Una de: "verde", "amarillo", "naranja", "rojo", "desconocido".

    Reglas:
        verde:    valor < 50% del umbral  → calidad buena
        amarillo: 50%  ≤ valor < 75%       → calidad moderada
        naranja:  75%  ≤ valor < 100%      → mala (cerca de umbral)
        rojo:     valor ≥ 100%             → contingencia (cruzó umbral)
    """
    if valor_predicho is None or umbral is None or umbral <= 0:
        return "desconocido"
    ratio = valor_predicho / umbral
    if ratio < 0.50:
        return "verde"
    elif ratio < 0.75:
        return "amarillo"
    elif ratio < 1.00:
        return "naranja"
    else:
        return "rojo"


# =============================================================================
# TIMEZONE
# =============================================================================
# Toda la cadena del proyecto opera en hora local CDMX (UTC-6, sin DST).
# Razón: los umbrales del PCAA y las decisiones del usuario operan en hora local.

TIMEZONE = "America/Mexico_City"
TIMEZONE_OFFSET_HOURS = -6
