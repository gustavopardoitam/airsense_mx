"""Inferencia: produce gold.predicciones_diarias desde modelos entrenados.

Este paquete contiene el código que toma los modelos LightGBM entrenados
y los aplica sobre features de Gold para producir la tabla que consume
Streamlit (vía Athena).

API pública:
    from inference import construir_predicciones, cargar_modelos

Uso típico:
    from inference import construir_predicciones

    predicciones = construir_predicciones(
        gold=gold_df,
        models_dir="artifacts/models/",
        fecha_inicio="2025-10-01",
        fecha_fin="2026-02-28",
    )

CLI:
    python -m inference.predict --gold-path ... --models-dir ... --output ...
"""

from __future__ import annotations

from inference.predict import (
    ModeloContaminante,
    cargar_modelos,
    construir_predicciones,
    derivar_probabilidad,
    escribir_predicciones,
    predecir_dataset,
    predict,  # wrapper compatible con stub original
)

__all__ = [
    "ModeloContaminante",
    "cargar_modelos",
    "construir_predicciones",
    "derivar_probabilidad",
    "escribir_predicciones",
    "predecir_dataset",
    "predict",
]
