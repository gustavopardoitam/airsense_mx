"""ETL Pipeline para AirSense MX — Arquitectura Medallion.

Bronze → Silver → Gold

Procesos:
    - Bronze: Ingestión cruda de RAMA/SIMAT, Open-Meteo, PCAA
    - Silver: Normalización, validación, limpieza de datos
    - Gold: Features de ingeniería, panel analítico, datos listos para ML

Ejecutar:
    python -m etl
Este paquete contiene el pipeline de feature engineering que transforma
las observaciones horarias (Silver) en el panel diario por estación (Gold)
listo para entrenar modelos.

API pública:
    from etl import construir_gold

Uso típico:
    from etl import construir_gold

    gold = construir_gold(
        obs=silver_obs_df,
        meteo=silver_meteo_df,
        fecha_inicio="2021-01-01",
        fecha_fin="2026-02-28",
    )

CLI:
    python -m etl.silver_to_gold --silver-obs ... --silver-meteo ... --output ...
"""

from __future__ import annotations


from etl.silver_to_gold import (
    construir_gold,
    agregar_diario_obs,
    agregar_diario_meteo,
    construir_lags,
    construir_rolling,
    agregar_calendario,
    agregar_labels,
    agregar_flags_calidad,
)
from etl.silver_adapter import (
    adaptar_silver_completo,
    adaptar_observaciones,
    adaptar_meteo,
)

__all__ = [
    "construir_gold",
    "agregar_diario_obs",
    "agregar_diario_meteo",
    "construir_lags",
    "construir_rolling",
    "agregar_calendario",
    "agregar_labels",
    "agregar_flags_calidad",
]

__all__ = [
    "construir_gold",
    "agregar_diario_obs",
    "agregar_diario_meteo",
    "construir_lags",
    "construir_rolling",
    "agregar_calendario",
    "agregar_labels",
    "agregar_flags_calidad",
    # silver_adapter
    "adaptar_silver_completo",
    "adaptar_observaciones",
    "adaptar_meteo",
]