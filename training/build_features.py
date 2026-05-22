"""Preparación de features y targets desde Gold para entrenamiento e inferencia.

Toma la tabla Gold (panel diario por estación) y produce los DataFrames X, y
listos para alimentar LightGBM. Centraliza la lógica de:
    - Qué columnas son features vs targets vs metadata
    - Construcción del target con horizonte (predecir día t+horizonte)
    - Split temporal en train/val/test
    - Manejo de categóricas (station_id, zone)

Este módulo es compartido entre training (que lo usa para entrenar) e inference
(que lo usa para preparar batches de predicción). Centralizarlo evita drift.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


logger = logging.getLogger(__name__)


# =============================================================================
# CATÁLOGO DE COLUMNAS
# =============================================================================

# Columnas que identifican unívocamente una fila (no son features)
COLS_IDENTIFICADORAS = ["fecha", "station_id", "zone"]

# Columnas de metadata que no entran al modelo
COLS_METADATA = [
    "ingestion_timestamp",
    "pipeline_version",
]

# Columnas de cobertura/conteo (son metadata, no features de entrada típicas)
COLS_COBERTURA = [
    "o3_n_horas", "no2_n_horas", "so2_n_horas",
    "pm10_n_horas", "pm25_n_horas", "co_n_horas",
    "n_horas_meteo",
]

# Labels binarias derivadas (no son features ni targets de regresión)
COLS_LABELS = [
    "contingencia_o3", "contingencia_pm25", "contingencia_pm10", "contingencia_any",
]

# Targets posibles (uno por modelo)
TARGETS = {
    "O3":   "o3_max_1h",
    "PM25": "pm25_avg_24h",
    "PM10": "pm10_avg_24h",
}

# Flags de calidad: útiles como features secundarias
COLS_CALIDAD = ["dias_validos_30d", "cobertura_30d"]

# Columnas categóricas para LightGBM (se le pasan como categorical_feature)
COLS_CATEGORICAS = ["station_id", "zone", "mes", "dia_semana"]


# =============================================================================
# CONSTRUCCIÓN DE TARGET CON HORIZONTE
# =============================================================================

def construir_target_con_horizonte(
    df: pd.DataFrame,
    target_col: str,
    horizonte: int,
) -> pd.DataFrame:
    """Agrega columna `y` con el target adelantado N días por estación.

    El día t recibe como target el valor del contaminante en el día t+horizonte
    para esa misma estación. Esto es la formulación estándar de pronóstico:
    "dado lo que se hasta hoy, predice el día siguiente".

    Filas para las que no existe el día t+horizonte (final de serie) quedan
    con y=NaN y se eliminan al construir el dataset.

    Args:
        df: panel Gold ordenado por (station_id, fecha).
        target_col: nombre de la columna a usar como target (ej. 'o3_max_1h').
        horizonte: número de días hacia adelante.

    Returns:
        DataFrame con la nueva columna 'y'.
    """
    if target_col not in df.columns:
        raise ValueError(f"Columna target '{target_col}' no existe en el panel")

    df = df.sort_values(["station_id", "fecha"]).copy()
    df["y"] = df.groupby("station_id")[target_col].shift(-horizonte)
    return df


# =============================================================================
# SELECCIÓN DE FEATURES
# =============================================================================

def seleccionar_features(
    df: pd.DataFrame,
    contaminante: str,
    horizonte: Optional[int] = None,
    excluir_otros_targets: bool = True,
) -> list[str]:
    """Determina la lista de columnas a usar como features.

    Excluye:
        - Identificadores no informativos (fecha)
        - Metadata e ingestion_timestamp
        - Labels binarias (son derivadas de los targets, sería leakage)
        - El target del modelo actual (ya está en y)
        - Otros targets si excluir_otros_targets=True (recomendado para evitar
          que el modelo use el valor de hoy de PM25 para predecir O3 de mañana,
          lo cual asume disponibilidad de datos no realista en serving)

    Incluye:
        - station_id y zone (categóricas, LightGBM las maneja)
        - Todas las features meteorológicas
        - Lags y rolling stats
        - Features de calendario
        - Flags de calidad
        - Horizonte (si se pasa, se asume que ya fue agregado al df)

    Args:
        df: DataFrame que debe contener las features y opcionalmente y.
        contaminante: O3, PM25 o PM10. Determina el target a excluir.
        horizonte: si no None, se asume que existe la columna `horizon_dias`
                   en df y se incluye como feature.
        excluir_otros_targets: si True, no usa los otros contaminantes como features.

    Returns:
        Lista de nombres de columnas a usar como features.
    """
    if contaminante not in TARGETS:
        raise ValueError(f"Contaminante no soportado: {contaminante}")

    target_actual = TARGETS[contaminante]

    a_excluir = set(COLS_IDENTIFICADORAS) | set(COLS_METADATA) | set(COLS_LABELS)
    a_excluir.add("fecha")
    a_excluir.add("y")
    a_excluir.add(target_actual)

    if excluir_otros_targets:
        for cont, col in TARGETS.items():
            if cont != contaminante:
                a_excluir.add(col)

    features = [c for c in df.columns if c not in a_excluir]
    return features


# =============================================================================
# SPLIT TEMPORAL
# =============================================================================

@dataclass
class SplitTemporal:
    """Configuración de split temporal estricto (sin shuffle)."""

    train_inicio: str = "2021-01-01"
    train_fin: str = "2024-12-31"
    val_inicio: str = "2025-01-01"
    val_fin: str = "2025-09-30"
    test_inicio: str = "2025-10-01"
    test_fin: str = "2026-02-28"


def aplicar_split_temporal(
    df: pd.DataFrame,
    split: Optional[SplitTemporal] = None,
    col_fecha: str = "fecha",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Divide el DataFrame en train/val/test respetando el orden temporal.

    Args:
        df: panel completo con columna de fecha.
        split: configuración del split (usa defaults si None).
        col_fecha: nombre de la columna de fecha.

    Returns:
        (train_df, val_df, test_df) — DataFrames separados por período.
    """
    split = split or SplitTemporal()
    fechas = pd.to_datetime(df[col_fecha])

    mask_train = (
        (fechas >= pd.Timestamp(split.train_inicio))
        & (fechas <= pd.Timestamp(split.train_fin))
    )
    mask_val = (
        (fechas >= pd.Timestamp(split.val_inicio))
        & (fechas <= pd.Timestamp(split.val_fin))
    )
    mask_test = (
        (fechas >= pd.Timestamp(split.test_inicio))
        & (fechas <= pd.Timestamp(split.test_fin))
    )

    train = df[mask_train].copy()
    val = df[mask_val].copy()
    test = df[mask_test].copy()

    logger.info(
        f"Split temporal: train={len(train):,} filas "
        f"({split.train_inicio}..{split.train_fin}), "
        f"val={len(val):,} ({split.val_inicio}..{split.val_fin}), "
        f"test={len(test):,} ({split.test_inicio}..{split.test_fin})"
    )

    return train, val, test


# =============================================================================
# DATASET PRINCIPAL: GOLD → X, Y LISTO PARA ENTRENAR
# =============================================================================

@dataclass
class DatasetEntrenamiento:
    """Contiene X, y para train/val/test listos para LightGBM."""

    X_train: pd.DataFrame
    y_train: pd.Series
    X_val: pd.DataFrame
    y_val: pd.Series
    X_test: pd.DataFrame
    y_test: pd.Series
    features: list[str]
    categoricas: list[str]
    contaminante: str
    horizonte: int
    target_col: str
    train_meta: pd.DataFrame  # fecha, station_id, zone para referencia
    val_meta: pd.DataFrame
    test_meta: pd.DataFrame


def construir_dataset(
    gold: pd.DataFrame,
    contaminante: str,
    horizonte: int = 1,
    split: Optional[SplitTemporal] = None,
    excluir_otros_targets: bool = True,
) -> DatasetEntrenamiento:
    """Pipeline completo Gold → X, y para entrenar un modelo de un contaminante.

    Pasos:
        1. Construye target adelantado al horizonte deseado
        2. Filtra filas con target NULL (final de serie, sin futuro)
        3. Selecciona columnas de features
        4. Aplica split temporal
        5. Empaqueta en DatasetEntrenamiento

    Args:
        gold: DataFrame del panel diario Gold.
        contaminante: 'O3', 'PM25' o 'PM10'.
        horizonte: días hacia adelante (1-7).
        split: configuración de split temporal (defaults razonables).
        excluir_otros_targets: si True, excluye otros contaminantes de features.

    Returns:
        DatasetEntrenamiento con X/y separados en train/val/test.
    """
    if contaminante not in TARGETS:
        raise ValueError(f"Contaminante no soportado: {contaminante}")

    target_col = TARGETS[contaminante]
    logger.info(
        f"Construyendo dataset para {contaminante} (target={target_col}, "
        f"horizonte={horizonte}d)"
    )

    # 1. Target con shift
    df = construir_target_con_horizonte(gold, target_col, horizonte)

    # 2. Eliminar filas sin target (final de cada serie por estación)
    n_antes = len(df)
    df = df[df["y"].notna()].copy()
    logger.info(f"Filas con target válido: {len(df):,} (descartadas {n_antes - len(df):,})")

    # 3. Selección de features
    features = seleccionar_features(df, contaminante, excluir_otros_targets=excluir_otros_targets)
    categoricas = [c for c in COLS_CATEGORICAS if c in features]
    logger.info(f"Features: {len(features)} ({len(categoricas)} categóricas)")

    # 4. Split temporal
    train, val, test = aplicar_split_temporal(df, split)

    # Convertir categóricas a tipo category de pandas (LightGBM las maneja nativamente)
    for col in categoricas:
        for split_df in (train, val, test):
            split_df[col] = split_df[col].astype("category")

    # 5. Empaquetar
    return DatasetEntrenamiento(
        X_train=train[features],
        y_train=train["y"],
        X_val=val[features],
        y_val=val["y"],
        X_test=test[features],
        y_test=test["y"],
        features=features,
        categoricas=categoricas,
        contaminante=contaminante,
        horizonte=horizonte,
        target_col=target_col,
        train_meta=train[COLS_IDENTIFICADORAS].reset_index(drop=True),
        val_meta=val[COLS_IDENTIFICADORAS].reset_index(drop=True),
        test_meta=test[COLS_IDENTIFICADORAS].reset_index(drop=True),
    )
