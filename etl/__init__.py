"""ETL Pipeline para AirSense MX — Arquitectura Medallion.

Bronze → Silver → Gold

Procesos:
    - Bronze: Ingestión cruda de RAMA/SIMAT, Open-Meteo, PCAA
    - Silver: Normalización, validación, limpieza de datos
    - Gold: Features de ingeniería, panel analítico, datos listos para ML

Ejecutar:
    python -m etl
"""

from __future__ import annotations
