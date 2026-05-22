"""Schemas explícitos y rangos de validación para la capa Silver.

Define los tipos de datos canónicos para ``observaciones_horarias``
y ``meteo_horario``. Nunca inferir schemas automáticamente.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Observaciones horarias RAMA/SIMAT
# ---------------------------------------------------------------------------

#: Tipos de columnas para silver.observaciones_horarias
OBSERVACIONES_DTYPES: dict[str, str] = {
    "station_id": "string",
    "pollutant": "string",
    "datetime_local": "datetime64[ns]",
    "value": "Float64",
    "latitude": "float64",
    "longitude": "float64",
    "year": "int16",
    "month": "int8",
    "day": "int8",
    "hour": "int8",
}

#: Columnas clave primaria (unicidad por registro)
OBSERVACIONES_PK: list[str] = ["station_id", "pollutant", "datetime_local"]

#: Columnas de particionamiento Parquet
OBSERVACIONES_PARTITION_COLS: list[str] = ["year", "month"]

#: Rangos físicamente válidos por contaminante (min, max)
POLLUTANT_VALID_RANGES: dict[str, tuple[float, float]] = {
    "O3": (0.0, 500.0),
    "PM25": (0.0, 1000.0),
    "PM10": (0.0, 1000.0),
    "SO2": (0.0, 1000.0),
    "NO2": (0.0, 1000.0),
    "NO": (0.0, 1000.0),
    "NOx": (0.0, 1000.0),
    "CO": (0.0, 100.0),
}

# ---------------------------------------------------------------------------
# Meteorología horaria Open-Meteo
# ---------------------------------------------------------------------------

#: Tipos de columnas para silver.meteo_horario
METEO_DTYPES: dict[str, str] = {
    "station_id": "string",
    "datetime_local": "datetime64[ns]",
    "temperature_2m": "Float64",
    "relative_humidity_2m": "Float64",
    "dewpoint_2m": "Float64",
    "surface_pressure": "Float64",
    "precipitation": "Float64",
    "cloud_cover": "Float64",
    "shortwave_radiation": "Float64",
    "wind_speed_10m": "Float64",
    "wind_direction_10m": "Float64",
    "wind_gusts_10m": "Float64",
    "latitude": "float64",
    "longitude": "float64",
    "year": "int16",
    "month": "int8",
    "day": "int8",
    "hour": "int8",
}

#: Columnas clave primaria para meteo
METEO_PK: list[str] = ["station_id", "datetime_local"]

#: Columnas de particionamiento Parquet
METEO_PARTITION_COLS: list[str] = ["year", "month"]

#: Rangos físicamente válidos para variables meteorológicas (min, max)
METEO_VALID_RANGES: dict[str, tuple[float, float]] = {
    "temperature_2m": (-20.0, 50.0),
    "relative_humidity_2m": (0.0, 100.0),
    "dewpoint_2m": (-40.0, 40.0),
    "surface_pressure": (700.0, 1100.0),
    "precipitation": (0.0, 500.0),
    "cloud_cover": (0.0, 100.0),
    "shortwave_radiation": (0.0, 2000.0),
    "wind_speed_10m": (0.0, 200.0),
    "wind_direction_10m": (0.0, 360.0),
    "wind_gusts_10m": (0.0, 300.0),
}

#: Variables hourly presentes en los JSON de Open-Meteo
METEO_HOURLY_VARS: list[str] = [
    "temperature_2m",
    "relative_humidity_2m",
    "dewpoint_2m",
    "surface_pressure",
    "precipitation",
    "cloud_cover",
    "shortwave_radiation",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
]
