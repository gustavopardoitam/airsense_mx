"""Entry point para entrenar modelos de predicción.

Uso:
    python -m training

Todo:
    - Implementar train_pipeline()
    - Generar modelo y metadata JSON
"""

from __future__ import annotations

from utils.logging import get_logger, setup_logging

logger = get_logger(__name__)


def main() -> None:
    """Orquestador del entrenamiento de modelos.

    Fases:
        1. Cargar dataset preparado (Gold)
        2. Aplicar feature engineering
        3. Split temporal (sin data leakage)
        4. Entrenar LightGBM/XGBoost
        5. Calcular baseline naive
        6. Comparar: modelo debe superar baseline ≥10% en MAE
        7. Guardar modelo (.pkl) + metadata (.json)
        8. Generar reporte de evaluación

    TODO: Implementar
    """
    setup_logging()
    logger.info("Iniciando training pipeline")
    logger.warning("Training pipeline no implementado. Placeholder funcional.")


if __name__ == "__main__":
    main()
