"""Entry point para evaluación de modelos.

Uso:
    python -m evaluation

Todo:
    - Implementar evaluate_pipeline()
    - Calcular métricas: MAE, RMSE, F1 macro (si clasificación)
    - Generar reportes HTML
"""

from __future__ import annotations

from utils.logging import get_logger, setup_logging

logger = get_logger(__name__)


def main() -> None:
    """Orquestador de evaluación de modelos.

    Fases:
        1. Cargar modelo entrenado
        2. Hacer predicciones en validation set
        3. Calcular métricas: MAE, RMSE vs baseline
        4. Generar matriz de confusión si clasificación
        5. Generar reporte HTML con visualizaciones
        6. Loggear métricas en RDS (tabla metrics)

    TODO: Implementar
    """
    setup_logging()
    logger.info("Iniciando evaluation pipeline")
    logger.warning("Evaluation pipeline no implementado. Placeholder funcional.")


if __name__ == "__main__":
    main()
