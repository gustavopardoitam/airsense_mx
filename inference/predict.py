"""Predicción e inferencia en producción.

Procesos:
    - Cargar modelo entrenado (.pkl + metadata .json)
    - Preparar features para últimos datos disponibles
    - Hacer predicciones para próximas 24/48/72 horas
    - Clipping a rango físico válido (np.clip)
    - Guardar en RDS y S3

Todo:
    - Implementar predict()
    - Feature engineering igual a training
"""

from __future__ import annotations

from pathlib import Path

from utils.logging import get_logger

logger = get_logger(__name__)


def predict(model_path: Path) -> dict:
    """Hace predicciones usando modelo entrenado.

    Args:
        model_path: Ruta al archivo .pkl del modelo.

    Returns:
        Dict con predicciones: {station_id, pollutant, forecast_value, timestamp}

    TODO: Implementar
        1. Cargar modelo (.pkl) + metadata (.json)
        2. Validar que features requeridas coinciden
        3. Obtener últimas mediciones
        4. Preparar features
        5. Hacer predicciones
        6. Aplicar np.clip para validez física
        7. Retornar predicciones
    """
    logger.info("TODO: predict(%s)", model_path)
    return {"predictions": []}
