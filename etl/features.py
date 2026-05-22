"""Feature Engineering para AirSense MX.

Funciones para construir features de series de tiempo:
    - Rolling averages (con shift para evitar data leakage)
    - Lags (valores históricos)
    - Features temporales (hora, día de semana, etc.)
    - Features meteorológicas

Estas funciones son importadas tanto en training/train.py como en
inference/predict.py para garantizar consistencia.

Todo:
    - Implementar build_features()
    - Implementar make_modeling_dataset()
    - Implementar temporal_split()
"""

from __future__ import annotations

from utils.logging import get_logger

logger = get_logger(__name__)


def build_features() -> None:
    """Construye todas las features para el modelo.

    Entrada:
        DataFrame con columnas: station_id, pollutant, timestamp, value

    Salida:
        DataFrame con features: rolling_Xh, lag_Xh, hora, día_semana, etc.

    Nota: Rolling usa shift(1) ANTES de calcular la media, para evitar
    que el valor actual afecte su propio rolling window.

    TODO: Implementar
    """
    logger.info(
        "Iniciando build_features",
        extra={"stage": "features", "step": "build_features"},
    )
    logger.warning(
        "TODO: build_features no implementado",
        extra={"stage": "features"},
    )


def make_modeling_dataset() -> None:
    """Construye dataset final para entrenamiento.

    Incluye: features + target + índices de series

    TODO: Implementar
    """
    logger.info(
        "Iniciando make_modeling_dataset",
        extra={"stage": "features", "step": "make_modeling_dataset"},
    )
    logger.warning(
        "TODO: make_modeling_dataset no implementado",
        extra={"stage": "features"},
    )


def temporal_split() -> None:
    """Split temporal por cuantil (sin data leakage en series de tiempo).

    Never usar train_test_split random. Split por:
        cutoff = df[time_col].quantile(train_quantile_cutoff)
        train = df[df[time_col] <= cutoff]
        valid = df[df[time_col] > cutoff]

    TODO: Implementar
    """
    logger.info(
        "Iniciando temporal_split",
        extra={"stage": "features", "step": "temporal_split"},
    )
    logger.warning(
        "TODO: temporal_split no implementado",
        extra={"stage": "features"},
    )
