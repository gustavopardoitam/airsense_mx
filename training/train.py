"""Entrenamiento de modelos de predicción de contaminantes.

Algoritmos:
    - LightGBM para regresión (forecasting de concentraciones)
    - Posible XGBoost como alternativa

Signature estándar:
    train_pipeline(
        input_parquet: Path,
        output_model: Path,
        cfg: ContaminantConfig | None = None,
    ) -> dict

Retorna: {mae, rmse, mae_naive, rmse_naive, model_path, n_train, n_val, trained_at}

Todo:
    - Implementar train_pipeline()
    - Implementar _naive_baseline()
    - Comparar vs baseline
"""

from __future__ import annotations

from pathlib import Path

from config import ContaminantConfig
from utils.logging import get_logger

logger = get_logger(__name__)


def train_pipeline(
    input_parquet: Path,
    output_model: Path,
    cfg: ContaminantConfig | None = None,
) -> dict:
    """Entrena modelo LightGBM y retorna métricas + path.

    Args:
        input_parquet: Ruta al parquet preparado (gold_features.parquet).
        output_model: Ruta donde guardar el modelo serializado (.pkl).
        cfg: Configuración del modelo. Si es None, usa defaults.

    Returns:
        Dict con mae, rmse, mae_naive, rmse_naive, model_path, n_train, n_val.

    Raises:
        FileNotFoundError: Si input_parquet no existe.

    TODO: Implementar
        1. Cargar input_parquet
        2. Split temporal por cuantil
        3. Entrenar LightGBM
        4. Calcular baseline naive (último valor observado)
        5. Validar: modelo >= baseline + 10% relativo en MAE
        6. Guardar .pkl + .json metadata
        7. Retornar métricas
    """
    if cfg is None:
        cfg = ContaminantConfig()

    if not Path(input_parquet).exists():
        raise FileNotFoundError(
            f"No existe el dataset preparado: {input_parquet}. "
            "Ejecuta primero python -m etl."
        )

    logger.info("TODO: train_pipeline(%s)", input_parquet)
    return {
        "mae": 0.0,
        "rmse": 0.0,
        "mae_naive": 0.0,
        "rmse_naive": 0.0,
        "model_path": str(output_model),
        "n_train": 0,
        "n_val": 0,
    }
