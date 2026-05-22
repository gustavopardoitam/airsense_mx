"""Capa Silver: normalización, limpieza y validación de datos Bronze.

Procesa archivos crudos de RAMA/SIMAT (Excel) y Open-Meteo (JSON) y
produce Parquet tipificados y particionados para consumo analítico.

Salidas:
    - ``silver.observaciones_horarias``: mediciones horarias de contaminantes
    - ``silver.meteo_horario``: variables meteorológicas horarias

Uso:
    python -m etl.silver rama --help
    python -m etl.silver openmeteo --help
"""

from __future__ import annotations
