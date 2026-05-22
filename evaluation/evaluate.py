"""Evaluación y validación de modelos entrenados.

Métricas:
    - MAE, RMSE comparados contra baseline naive
    - Para clasificación: F1 macro, precisión, recall por clase
    - Matriz de confusión

Todo:
    - Implementar evaluate()
    - Generar reportes HTML
"""

from __future__ import annotations

from utils.logging import get_logger

logger = get_logger(__name__)


def evaluate() -> None:
    """Evalúa modelo en validation set.

    TODO: Implementar
        1. Cargar modelo (.pkl) y metadata (.json)
        2. Cargar validation set
        3. Hacer predicciones
        4. Calcular MAE, RMSE, etc.
        5. Comparar contra baseline
        6. Generar plots con plotly
        7. Guardar reporte HTML
    """
    logger.info("TODO: evaluate()")
