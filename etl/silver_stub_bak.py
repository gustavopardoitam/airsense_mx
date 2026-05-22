"""Capa Silver: Normalización y validación de datos.

Procesos:
    - Timestamps normalizados a UTC, ISO 8601
    - Formato largo (tidy): una fila = una medición
    - Valores inválidos (out of range físico) marcados como null
    - Flags de calidad de datos
    - Validación de schema con pandera o contratos YAML

Entrada: Bronze (Parquet)
Salida: Silver (Parquet, particionado)

Todo:
    - Normalizar timestamps
    - Implementar validación de rango físico
    - Crear flags de calidad
    - Guardar a S3
"""

from __future__ import annotations

from utils.logging import get_logger

logger = get_logger(__name__)

# Umbrales de validación física por contaminante
INVALID_THRESHOLDS = {
    "O3": (0.0, 500.0),  # ppb
    "PM25": (0.0, 1000.0),  # µg/m³
    "PM10": (0.0, 1000.0),  # µg/m³
    "SO2": (0.0, 1000.0),  # ppb
    "NOx": (0.0, 1000.0),  # ppb
    "CO": (0.0, 100.0),  # ppm
    "H2S": (0.0, 100.0),  # ppb
}


def normalize_timestamps() -> None:
    """Normaliza todos los timestamps a UTC, formato ISO 8601.

    TODO: Implementar
    """
    logger.info(
        "Iniciando normalización de timestamps",
        extra={"stage": "silver", "step": "normalize_timestamps"},
    )
    logger.warning(
        "TODO: normalize_timestamps no implementado",
        extra={"stage": "silver"},
    )


def flag_invalid_readings() -> None:
    """Marca lecturas físicamente imposibles como nulas con trazabilidad.

    Una lectura es inválida si está fuera de INVALID_THRESHOLDS.

    TODO: Implementar
        1. Aplicar INVALID_THRESHOLDS a cada contaminante
        2. Crear columna is_valid (booleano)
        3. Reemplazar valores inválidos con NULL
        4. Loggear cantidad de valores inválidos por estación/contaminante
    """
    logger.info(
        "Iniciando marcado de lecturas inválidas",
        extra={"stage": "silver", "step": "flag_invalid"},
    )
    logger.warning(
        "TODO: flag_invalid_readings no implementado",
        extra={"stage": "silver"},
    )


def validate_schema() -> None:
    """Valida que Silver cumple schema esperado.

    TODO: Implementar
        1. Usar pandera o contratos YAML
        2. Requerir: station_id, pollutant, timestamp, value, unit, is_valid
        3. Tipos: station_id (str), timestamp (datetime), value (float)
    """
    logger.info(
        "Iniciando validación de schema Silver",
        extra={"stage": "silver", "step": "validate_schema"},
    )
    logger.warning(
        "TODO: validate_schema no implementado",
        extra={"stage": "silver"},
    )
