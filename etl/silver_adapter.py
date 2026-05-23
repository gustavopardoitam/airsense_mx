"""Adapter Silver → contrato v1.1 para AirSense MX.
 
Antonio escribe Silver con los nombres nativos de las fuentes (Open-Meteo y
SIMAT en inglés). El contrato v1.1 acordado por el equipo usa nombres en
español. Este módulo es la capa de adaptación entre ambos universos.
 
POR QUÉ EXISTE
==============
Cuando Antonio terminó el ETL, su Silver salió con:
    - 'value' en lugar de 'valor'
    - 'pollutant' en lugar de 'contaminante'
    - 'datetime_local' en lugar de 'timestamp'
    - 'temperature_2m' en lugar de 'temp_2m'
    - 'relative_humidity_2m' en lugar de 'humidity_2m'
    - Sin las columnas denormalizadas zone, municipality
    - Sin ingestion_timestamp
 
En vez de regenerar Silver (1+ hora), construimos este adapter que normaliza
los nombres y enriquece con la información de la dim antes de pasar a Gold.
 
Este es un patrón de producción legítimo: equipos de ETL y consumidores de
datos suelen estar desacoplados, y los adapters se documentan como una capa
explícita en la arquitectura.
 
USO
===
    from etl.silver_adapter import adaptar_silver_completo
    obs_raw = wr.s3.read_parquet("s3://.../silver/observaciones_horarias/")
    meteo_raw = wr.s3.read_parquet("s3://.../silver/meteo_horario/")
    dim = pd.read_csv("data/dim_estaciones.csv")
 
    obs, meteo = adaptar_silver_completo(obs_raw, meteo_raw, dim)
 
    # A partir de aquí, obs y meteo cumplen el contrato v1.1
    # y pueden alimentar construir_gold() sin cambios.
"""
 
from __future__ import annotations
 
import logging
from typing import Optional
 
import numpy as np
import pandas as pd
 
 
logger = logging.getLogger(__name__)
 
 
# =============================================================================
# MAPEOS DE COLUMNAS (raw → contrato)
# =============================================================================
 
# Schema crudo de Antonio en silver.observaciones_horarias:
#   station_id, datetime_local, value, pollutant, latitude, longitude,
#   day, hour
COLUMN_MAPPING_OBS = {
    "value": "valor",
    "pollutant": "contaminante",
    "datetime_local": "timestamp",
}
 
# Schema crudo de Antonio en silver.meteo_horario:
#   station_id, datetime_local, temperature_2m, relative_humidity_2m,
#   dewpoint_2m, surface_pressure, precipitation, cloud_cover,
#   shortwave_radiation, wind_speed_10m, wind_direction_10m, wind_gusts_10m,
#   latitude, longitude, day, hour
COLUMN_MAPPING_METEO = {
    "datetime_local": "timestamp",
    "temperature_2m": "temp_2m",
    "relative_humidity_2m": "humidity_2m",
}
 
# Columnas que el contrato espera y deben terminar presentes
COLS_OBS_CONTRATO = [
    "timestamp", "station_id", "zone", "contaminante", "valor",
    "latitude", "longitude", "municipality", "ingestion_timestamp",
]
 
COLS_METEO_CONTRATO = [
    "timestamp", "station_id", "temp_2m", "humidity_2m", "dewpoint_2m",
    "surface_pressure", "precipitation", "cloud_cover", "shortwave_radiation",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
    "latitude", "longitude", "ingestion_timestamp",
]
 
 
# =============================================================================
# ADAPTADOR DE OBSERVACIONES
# =============================================================================
 
def adaptar_observaciones(
    obs_raw: pd.DataFrame,
    dim: pd.DataFrame,
) -> pd.DataFrame:
    """Adapta observaciones de Antonio al schema del contrato.
 
    Pasos:
        1. Rename: value → valor, pollutant → contaminante,
                   datetime_local → timestamp
        2. Enriquecer con zone y municipality (join con dim por station_id)
        3. Agregar ingestion_timestamp si falta
        4. Validar y reordenar columnas al schema del contrato
 
    Args:
        obs_raw: DataFrame leído directamente del Silver de Antonio.
        dim: DataFrame de dim_estaciones con al menos station_id, zone, municipality.
 
    Returns:
        DataFrame con el schema exacto del contrato v1.1.
    """
    logger.info(f"Adaptando {len(obs_raw):,} observaciones al contrato")
    df = obs_raw.copy()
 
    # 1. Renames
    df = df.rename(columns=COLUMN_MAPPING_OBS)
 
    # 2. Garantizar tipo timestamp
    df["timestamp"] = pd.to_datetime(df["timestamp"])
 
    # 3. Normalizar contaminante a mayúsculas (PM2.5 → PM25, etc.)
    # Acepta variantes comunes y las normaliza al estándar del contrato.
    df["contaminante"] = (
        df["contaminante"]
        .str.upper()
        .replace({"PM2.5": "PM25", "PM_25": "PM25", "PM-25": "PM25"})
    )
 
    # 4. Enriquecer con zone y municipality desde la dim
    dim_subset = dim[["station_id", "zone", "municipality"]].drop_duplicates(
        subset=["station_id"]
    )
    df = df.merge(dim_subset, on="station_id", how="left")
 
    # Bandera de calidad: stations sin match con la dim
    n_sin_zone = df["zone"].isna().sum()
    if n_sin_zone > 0:
        stations_huerfanas = df.loc[df["zone"].isna(), "station_id"].unique()
        logger.warning(
            f"{n_sin_zone:,} filas con station_id NO presente en dim "
            f"(stations huérfanas: {list(stations_huerfanas)})"
        )
 
    # 5. ingestion_timestamp si falta
    if "ingestion_timestamp" not in df.columns:
        df["ingestion_timestamp"] = pd.Timestamp.now()
 
    # 6. Validar que -99 ya esté convertido a NaN (si Antonio lo olvidó, lo arreglamos)
    n_minus99 = (df["valor"] == -99).sum()
    if n_minus99 > 0:
        logger.warning(f"Encontrados {n_minus99:,} valores -99, convirtiéndolos a NaN")
        df.loc[df["valor"] == -99, "valor"] = np.nan
 
    # 7. Reordenar columnas al schema del contrato
    # (deja columnas extras como day, hour fuera del output)
    df = df[COLS_OBS_CONTRATO]
 
    logger.info(
        f"✓ Observaciones adaptadas: {len(df):,} filas, "
        f"{df['station_id'].nunique()} stations, "
        f"{df['contaminante'].nunique()} contaminantes"
    )
    return df
 
 
# =============================================================================
# ADAPTADOR DE METEO
# =============================================================================
 
def adaptar_meteo(meteo_raw: pd.DataFrame) -> pd.DataFrame:
    """Adapta meteo de Antonio al schema del contrato.
 
    Pasos:
        1. Rename: datetime_local → timestamp, temperature_2m → temp_2m,
                   relative_humidity_2m → humidity_2m
        2. Garantizar tipo timestamp
        3. Agregar ingestion_timestamp si falta
        4. Reordenar columnas al schema del contrato
 
    Args:
        meteo_raw: DataFrame leído directamente del Silver meteo de Antonio.
 
    Returns:
        DataFrame con el schema exacto del contrato v1.1.
    """
    logger.info(f"Adaptando {len(meteo_raw):,} registros meteorológicos al contrato")
    df = meteo_raw.copy()
 
    # 1. Renames
    df = df.rename(columns=COLUMN_MAPPING_METEO)
 
    # 2. Tipo timestamp
    df["timestamp"] = pd.to_datetime(df["timestamp"])
 
    # 3. ingestion_timestamp si falta
    if "ingestion_timestamp" not in df.columns:
        df["ingestion_timestamp"] = pd.Timestamp.now()
 
    # 4. Validar columnas críticas presentes
    faltantes = [c for c in COLS_METEO_CONTRATO if c not in df.columns]
    if faltantes:
        logger.warning(
            f"Columnas de contrato no presentes en meteo: {faltantes}. "
            f"Se incluirán como NaN."
        )
        for c in faltantes:
            df[c] = np.nan
 
    # 5. Reordenar al schema del contrato
    df = df[COLS_METEO_CONTRATO]
 
    logger.info(
        f"✓ Meteo adaptado: {len(df):,} filas, "
        f"{df['station_id'].nunique()} stations"
    )
    return df
 
 
# =============================================================================
# API PRINCIPAL
# =============================================================================
 
def adaptar_silver_completo(
    obs_raw: pd.DataFrame,
    meteo_raw: pd.DataFrame,
    dim: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aplica el adapter completo a obs y meteo en una sola llamada.
 
    Args:
        obs_raw: silver.observaciones_horarias de Antonio.
        meteo_raw: silver.meteo_horario de Antonio.
        dim: dim_estaciones completa.
 
    Returns:
        (obs_adaptado, meteo_adaptado) cumpliendo el contrato v1.1, listos
        para alimentar construir_gold().
    """
    obs = adaptar_observaciones(obs_raw, dim)
    meteo = adaptar_meteo(meteo_raw)
    return obs, meteo