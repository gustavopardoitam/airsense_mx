"""Capa Gold: Datos analíticos listos para ML y visualización.

Procesos:
    - Panel diario por estación: promedios, máximos, percentiles
    - Features de ingeniería: rolling windows, lags
    - Features temporales: hora, día de semana, mes
    - Features meteorológicas: temp, humedad, presión, viento
    - Labels: contingency_phase (0-3)

Entrada: Silver (Parquet)
Salida: Gold (Parquet), dataset_filename = 'gold_features.parquet'

Todo:
    - Implementar feature engineering
    - Crear labels de contingencia
    - Generar panel diario
    - Guardar a S3
"""

from __future__ import annotations

from utils.logging import get_logger

logger = get_logger(__name__)


def build_daily_panel() -> None:
    """Construye panel diario por estación y contaminante.

    Cálculos:
        - mean, max, min, p50, p75, p90, p95, p99
        - horas de excedencia por threshold
        - variabilidad

    TODO: Implementar
    """
    logger.info("TODO: Construir panel diario")


def engineer_features() -> None:
    """Realiza feature engineering para modelos de ML.

    Features:
        - Rolling averages: 8h, 24h
        - Lags: t-1, t-3, t-6, t-24
        - Temporales: hora, día_semana, mes, es_fin_de_semana
        - Meteorológicas: temp, humedad, presión, viento

    TODO: Implementar
        1. Importar de etl/features.py
        2. Aplicar rolling con shift(1) para evitar data leakage
        3. Crear lags por (station, pollutant)
        4. Agregar features meteorológicas
    """
    logger.info("TODO: Engineer features")


def create_contingency_labels() -> None:
    """Crea labels de contingencia basados en thresholds NOM-172.

    Target: contingency_phase (int)
        - 0: Sin contingencia (normal)
        - 1: Fase I (alert)
        - 2: Fase II (warning)
        - 3: Doble contingencia (emergency)

    Thresholds: Ver config.ContaminantConfig

    TODO: Implementar
    """
    logger.info("TODO: Crear labels de contingencia")
