"""Entrenamiento de modelos LightGBM para AirSense MX.

Este paquete contiene la lógica de entrenamiento del modelo:
    - build_features: preparación de X/y desde Gold (target con horizonte,
      split temporal, selección de features).
    - train: entrenamiento de modelos LightGBM con quantile regression
      (p10, p50, p90) y validación contra baseline naïve.

API pública:
    from training import entrenar_modelos, train_pipeline, construir_dataset

Uso típico:
    from training import entrenar_modelos
    resultados = entrenar_modelos(gold_df, output_dir="artifacts/models/")

CLI:
    python -m training.train --gold-path ... --output-dir ...
"""

from __future__ import annotations


from training.build_features import (
    DatasetEntrenamiento,
    SplitTemporal,
    TARGETS,
    construir_dataset,
)
from training.train import (
    MetricasModelo,
    MetricasBaseline,
    ResultadoEntrenamiento,
    entrenar_modelos,
    entrenar_un_modelo,
    train_pipeline,
)

__all__ = [
    # build_features
    "DatasetEntrenamiento",
    "SplitTemporal",
    "TARGETS",
    "construir_dataset",
    # train
    "MetricasModelo",
    "MetricasBaseline",
    "ResultadoEntrenamiento",
    "entrenar_modelos",
    "entrenar_un_modelo",
    "train_pipeline",
]
