"""Tests unitarios para etl/silver/openmeteo_silver.py."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from etl.silver.openmeteo_silver import normalize_openmeteo, parse_openmeteo_json
from etl.silver.schemas import METEO_HOURLY_VARS

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def dim_estaciones_df() -> pd.DataFrame:
    """Catálogo mínimo de estaciones para tests."""
    return pd.DataFrame(
        {
            "station_id": pd.array(["BJU", "XAL", "ACO"], dtype="string"),
            "latitude": [19.3705, 19.5239, 19.6355],
            "longitude": [-99.1596, -99.0148, -98.9120],
        }
    )


@pytest.fixture()
def sample_openmeteo_json(tmp_path: Path) -> Path:
    """Archivo JSON de Open-Meteo mínimo para tests."""
    payload = {
        "latitude": 19.36731,
        "longitude": -99.18732,
        "timezone": "America/Mexico_City",
        "hourly": {
            "time": ["2023-06-01T00:00", "2023-06-01T01:00", "2023-06-01T02:00"],
            "temperature_2m": [18.5, 17.8, 17.2],
            "relative_humidity_2m": [65.0, 68.0, 70.0],
            "dewpoint_2m": [11.2, 11.5, 11.8],
            "surface_pressure": [780.0, 781.0, 782.0],
            "precipitation": [0.0, 0.0, 0.0],
            "cloud_cover": [10.0, 15.0, 20.0],
            "shortwave_radiation": [0.0, 0.0, 50.0],
            "wind_speed_10m": [3.5, 4.0, 3.8],
            "wind_direction_10m": [180.0, 185.0, 175.0],
            "wind_gusts_10m": [6.0, 7.5, 6.5],
        },
        "_metadata": {
            "station_id": "BJU",
            "year": 2023,
            "latitude_actual": 19.36731,
            "longitude_actual": -99.18732,
        },
    }
    path = tmp_path / "openmeteo_BJU_2023.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# parse_openmeteo_json
# ---------------------------------------------------------------------------


def test_parse_openmeteo_json_returns_dataframe(
    sample_openmeteo_json: Path,
) -> None:
    df = parse_openmeteo_json(sample_openmeteo_json)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 3


def test_parse_openmeteo_json_has_station_id(
    sample_openmeteo_json: Path,
) -> None:
    df = parse_openmeteo_json(sample_openmeteo_json)
    assert "station_id" in df.columns
    assert df["station_id"].iloc[0] == "BJU"


def test_parse_openmeteo_json_datetime_local_timezone_naive(
    sample_openmeteo_json: Path,
) -> None:
    df = parse_openmeteo_json(sample_openmeteo_json)
    assert "datetime_local" in df.columns
    assert df["datetime_local"].dt.tz is None


def test_parse_openmeteo_json_first_hour_is_midnight(
    sample_openmeteo_json: Path,
) -> None:
    df = parse_openmeteo_json(sample_openmeteo_json)
    assert df["datetime_local"].iloc[0] == pd.Timestamp("2023-06-01 00:00")


def test_parse_openmeteo_json_has_expected_columns(
    sample_openmeteo_json: Path,
) -> None:
    df = parse_openmeteo_json(sample_openmeteo_json)
    for var in METEO_HOURLY_VARS:
        assert var in df.columns, f"Columna faltante: {var}"


def test_parse_openmeteo_json_has_lat_lon(
    sample_openmeteo_json: Path,
) -> None:
    df = parse_openmeteo_json(sample_openmeteo_json)
    assert "latitude" in df.columns
    assert "longitude" in df.columns
    assert abs(df["latitude"].iloc[0] - 19.36731) < 0.001


# ---------------------------------------------------------------------------
# normalize_openmeteo
# ---------------------------------------------------------------------------


def test_normalize_openmeteo_schema_dtypes(
    sample_openmeteo_json: Path,
    dim_estaciones_df: pd.DataFrame,
) -> None:
    df_raw = parse_openmeteo_json(sample_openmeteo_json)
    df_silver, _ = normalize_openmeteo(df_raw, dim_estaciones_df)

    assert df_silver["station_id"].dtype == pd.StringDtype()
    assert str(df_silver["year"].dtype) == "int16"
    assert str(df_silver["month"].dtype) == "int8"
    assert str(df_silver["hour"].dtype) == "int8"
    assert df_silver["temperature_2m"].dtype == pd.Float64Dtype()


def test_normalize_openmeteo_no_duplicates(
    sample_openmeteo_json: Path,
    dim_estaciones_df: pd.DataFrame,
) -> None:
    df_raw = parse_openmeteo_json(sample_openmeteo_json)
    df_silver, _ = normalize_openmeteo(df_raw, dim_estaciones_df)

    pk_cols = ["station_id", "datetime_local"]
    assert not df_silver.duplicated(subset=pk_cols).any()


def test_normalize_openmeteo_time_columns_derived(
    sample_openmeteo_json: Path,
    dim_estaciones_df: pd.DataFrame,
) -> None:
    df_raw = parse_openmeteo_json(sample_openmeteo_json)
    df_silver, _ = normalize_openmeteo(df_raw, dim_estaciones_df)

    assert "year" in df_silver.columns
    assert "month" in df_silver.columns
    assert "day" in df_silver.columns
    assert "hour" in df_silver.columns
    assert df_silver["year"].iloc[0] == 2023
    assert df_silver["month"].iloc[0] == 6
    assert df_silver["hour"].iloc[0] == 0


def test_normalize_openmeteo_invalid_range_nulled(
    tmp_path: Path,
    dim_estaciones_df: pd.DataFrame,
) -> None:
    # temperature > 50 debe quedar NULL
    payload = {
        "latitude": 19.36731,
        "longitude": -99.18732,
        "hourly": {
            "time": ["2023-01-01T00:00"],
            "temperature_2m": [999.0],  # fuera de rango
            "relative_humidity_2m": [65.0],
            "dewpoint_2m": [11.0],
            "surface_pressure": [780.0],
            "precipitation": [0.0],
            "cloud_cover": [10.0],
            "shortwave_radiation": [0.0],
            "wind_speed_10m": [3.0],
            "wind_direction_10m": [180.0],
            "wind_gusts_10m": [5.0],
        },
        "_metadata": {"station_id": "BJU", "year": 2023},
    }
    path = tmp_path / "openmeteo_BJU_2023.json"
    path.write_text(json.dumps(payload))

    df_raw = parse_openmeteo_json(path)
    df_silver, metrics = normalize_openmeteo(df_raw, dim_estaciones_df)

    assert metrics["invalid_ranges"] >= 1
    assert pd.isna(df_silver["temperature_2m"].iloc[0])


def test_normalize_openmeteo_filters_unknown_stations(
    tmp_path: Path,
    dim_estaciones_df: pd.DataFrame,
) -> None:
    payload = {
        "latitude": 19.0,
        "longitude": -99.0,
        "hourly": {
            "time": ["2023-01-01T00:00"],
            "temperature_2m": [18.0],
            "relative_humidity_2m": [65.0],
            "dewpoint_2m": [10.0],
            "surface_pressure": [780.0],
            "precipitation": [0.0],
            "cloud_cover": [10.0],
            "shortwave_radiation": [0.0],
            "wind_speed_10m": [3.0],
            "wind_direction_10m": [180.0],
            "wind_gusts_10m": [5.0],
        },
        "_metadata": {"station_id": "GHOST", "year": 2023},  # no en catálogo
    }
    path = tmp_path / "openmeteo_GHOST_2023.json"
    path.write_text(json.dumps(payload))

    df_raw = parse_openmeteo_json(path)
    df_silver, metrics = normalize_openmeteo(df_raw, dim_estaciones_df)

    assert metrics["invalid_stations"] >= 1
    assert len(df_silver) == 0


def test_normalize_openmeteo_metrics_shape(
    sample_openmeteo_json: Path,
    dim_estaciones_df: pd.DataFrame,
) -> None:
    df_raw = parse_openmeteo_json(sample_openmeteo_json)
    _, metrics = normalize_openmeteo(df_raw, dim_estaciones_df)

    required_keys = {
        "rows_input", "rows_output", "null_replacements",
        "invalid_ranges", "invalid_stations", "duplicates_removed",
        "partitions_created",
    }
    assert required_keys.issubset(metrics.keys())
