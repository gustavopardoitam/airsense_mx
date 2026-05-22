"""Excepciones de dominio para AirSense MX.

Define excepciones específicas del negocio que comunican claramente
qué salió mal con suficiente contexto para depuración.

Uso:
    from utils.exceptions import DataUnavailableError

    if not readings:
        raise DataUnavailableError(
            f"No hay lecturas para estación {station_id} en {date_range}",
            station_id=station_id,
        )
"""

from __future__ import annotations


class AirSenseError(Exception):
    """Excepción base para todos los errores de AirSense MX."""

    pass


class DataUnavailableError(AirSenseError):
    """Los datos requeridos no están disponibles.

    Ejemplos:
        - Estación sin conexión
        - Gap de horas en mediciones
        - Archivo no encontrado en S3
    """

    pass


class InvalidReadingError(AirSenseError):
    """Una lectura de contaminante está fuera de rango físico válido.

    Ejemplos:
        - O3 < 0 o > 500 ppb
        - PM2.5 < 0 o > 1000 µg/m³
        - Temperatura < -50°C o > 60°C
    """

    pass


class ContingencyClassificationError(AirSenseError):
    """No se puede clasificar el riesgo de contingencia.

    Ejemplos:
        - Contaminante no reconocido
        - Valor faltante en datos de entrada
        - Modelo no disponible
    """

    pass


class ModelNotFoundError(AirSenseError):
    """El modelo serializado no existe en artifacts/models/.

    Ejemplos:
        - pm25_forecaster_v1.0.pkl no encontrado
        - Archivo .json de metadata faltante
    """

    pass


class FeatureEngineeringError(AirSenseError):
    """Error durante feature engineering en ETL o inference.

    Ejemplos:
        - Faltan columnas esperadas
        - Rolling window no puede calcularse (< min_periods)
        - Lag requiere historial que no existe
    """

    pass
