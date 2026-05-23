"""Tests de contrato de datos para la capa Silver.

Validan que los Parquet generados cumplan el schema canónico y
son compatibles con PyArrow, Athena y DuckDB.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pyarrow.parquet as pq
import pytest

from etl.silver.openmeteo_silver import normalize_openmeteo, parse_openmeteo_json
from etl.silver.rama_silver import process_rama_file
from etl.silver.schemas import (
    METEO_DTYPES,
    METEO_PARTITION_COLS,
    METEO_PK,
    OBSERVACIONES_DTYPES,
    OBSERVACIONES_PARTITION_COLS,
    OBSERVACIONES_PK,
)
from etl.silver.shared import write_parquet
from etl.silver.validations import (
    validate_no_duplicates,
    validate_timestamps_not_null,
    validate_timezone_naive,
    validate_year_month_not_null,
)

# ---------------------------------------------------------------------------
# Fixtures compartidos
# ---------------------------------------------------------------------------


@pytest.fixture()
def dim_estaciones_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "station_id": pd.array(["BJU", "XAL"], dtype="string"),
            "latitude": [19.3705, 19.5239],
            "longitude": [-99.1596, -99.0148],
        }
    )


@pytest.fixture()
def observaciones_df(dim_estaciones_df: pd.DataFrame, tmp_path: Path) -> pd.DataFrame:
    """DataFrame Silver observaciones_horarias de prueba."""
    fake_excel = pd.DataFrame(
        {
            "FECHA": pd.to_datetime(["2023-05-01"] * 4),
            "HORA": [1, 2, 3, 4],
            "BJU": [22.5, 30.1, -99.0, 40.0],
            "XAL": [18.0, 25.0, 28.0, -99.0],
        }
    )
    fake_path = tmp_path / "2023O3.xls"
    with patch("etl.silver.rama_silver.parse_rama_excel", return_value=fake_excel):
        df, _ = process_rama_file(fake_path, dim_estaciones_df)
    return df


@pytest.fixture()
def meteo_df(dim_estaciones_df: pd.DataFrame, tmp_path: Path) -> pd.DataFrame:
    """DataFrame Silver meteo_horario de prueba."""
    payload = {
        "latitude": 19.36731,
        "longitude": -99.18732,
        "hourly": {
            "time": ["2023-05-01T00:00", "2023-05-01T01:00"],
            "temperature_2m": [18.5, 17.8],
            "relative_humidity_2m": [65.0, 68.0],
            "dewpoint_2m": [11.2, 11.5],
            "surface_pressure": [780.0, 781.0],
            "precipitation": [0.0, 0.0],
            "cloud_cover": [10.0, 15.0],
            "shortwave_radiation": [0.0, 0.0],
            "wind_speed_10m": [3.5, 4.0],
            "wind_direction_10m": [180.0, 185.0],
            "wind_gusts_10m": [6.0, 7.5],
        },
        "_metadata": {"station_id": "BJU", "year": 2023},
    }
    path = tmp_path / "openmeteo_BJU_2023.json"
    path.write_text(json.dumps(payload))
    df_raw = parse_openmeteo_json(path)
    df, _ = normalize_openmeteo(df_raw, dim_estaciones_df)
    return df


# ---------------------------------------------------------------------------
# Tests de schema: observaciones_horarias
# ---------------------------------------------------------------------------


class TestObservacionesSchema:
    def test_required_columns_present(self, observaciones_df: pd.DataFrame) -> None:
        for col in OBSERVACIONES_DTYPES:
            assert col in observaciones_df.columns, f"Columna faltante: {col}"

    def test_no_object_dtype_in_numeric_columns(
        self, observaciones_df: pd.DataFrame
    ) -> None:
        numeric_cols = ["value", "latitude", "longitude"]
        for col in numeric_cols:
            assert observaciones_df[col].dtype != object, f"{col} es dtype object"

    def test_station_id_is_string_dtype(self, observaciones_df: pd.DataFrame) -> None:
        assert observaciones_df["station_id"].dtype == pd.StringDtype()

    def test_value_is_float64_nullable(self, observaciones_df: pd.DataFrame) -> None:
        assert observaciones_df["value"].dtype == pd.Float64Dtype()

    def test_year_dtype_int16(self, observaciones_df: pd.DataFrame) -> None:
        assert str(observaciones_df["year"].dtype) == "int16"

    def test_month_range(self, observaciones_df: pd.DataFrame) -> None:
        assert observaciones_df["month"].between(1, 12).all()

    def test_hour_range(self, observaciones_df: pd.DataFrame) -> None:
        assert observaciones_df["hour"].between(0, 23).all()

    def test_no_duplicates_by_pk(self, observaciones_df: pd.DataFrame) -> None:
        n = validate_no_duplicates(observaciones_df, OBSERVACIONES_PK)
        assert n == 0

    def test_no_null_timestamps(self, observaciones_df: pd.DataFrame) -> None:
        validate_timestamps_not_null(observaciones_df)  # no debe lanzar

    def test_timezone_naive(self, observaciones_df: pd.DataFrame) -> None:
        validate_timezone_naive(observaciones_df)  # no debe lanzar

    def test_year_month_not_null(self, observaciones_df: pd.DataFrame) -> None:
        validate_year_month_not_null(observaciones_df)  # no debe lanzar


# ---------------------------------------------------------------------------
# Tests de schema: meteo_horario
# ---------------------------------------------------------------------------


class TestMeteoSchema:
    def test_required_columns_present(self, meteo_df: pd.DataFrame) -> None:
        for col in METEO_DTYPES:
            assert col in meteo_df.columns, f"Columna faltante: {col}"

    def test_no_object_dtype_in_numeric_columns(
        self, meteo_df: pd.DataFrame
    ) -> None:
        numeric_cols = [
            "temperature_2m", "relative_humidity_2m", "latitude", "longitude"
        ]
        for col in numeric_cols:
            assert meteo_df[col].dtype != object, f"{col} es dtype object"

    def test_station_id_is_string_dtype(self, meteo_df: pd.DataFrame) -> None:
        assert meteo_df["station_id"].dtype == pd.StringDtype()

    def test_temperature_is_float64_nullable(self, meteo_df: pd.DataFrame) -> None:
        assert meteo_df["temperature_2m"].dtype == pd.Float64Dtype()

    def test_no_duplicates_by_pk(self, meteo_df: pd.DataFrame) -> None:
        n = validate_no_duplicates(meteo_df, METEO_PK)
        assert n == 0

    def test_no_null_timestamps(self, meteo_df: pd.DataFrame) -> None:
        validate_timestamps_not_null(meteo_df)

    def test_timezone_naive(self, meteo_df: pd.DataFrame) -> None:
        validate_timezone_naive(meteo_df)


# ---------------------------------------------------------------------------
# Tests de escritura Parquet (compatibilidad PyArrow)
# ---------------------------------------------------------------------------


class TestParquetCompatibility:
    def test_observaciones_parquet_readable_by_pyarrow(
        self,
        observaciones_df: pd.DataFrame,
        tmp_path: Path,
    ) -> None:
        out_dir = tmp_path / "observaciones_horarias"
        write_parquet(observaciones_df, out_dir, OBSERVACIONES_PARTITION_COLS)
        # Debe ser legible por PyArrow
        table = pq.read_table(str(out_dir))
        assert table.num_rows == len(observaciones_df)

    def test_meteo_parquet_readable_by_pyarrow(
        self,
        meteo_df: pd.DataFrame,
        tmp_path: Path,
    ) -> None:
        out_dir = tmp_path / "meteo_horario"
        write_parquet(meteo_df, out_dir, METEO_PARTITION_COLS)
        table = pq.read_table(str(out_dir))
        assert table.num_rows == len(meteo_df)

    def test_parquet_partition_structure_by_year_month(
        self,
        observaciones_df: pd.DataFrame,
        tmp_path: Path,
    ) -> None:
        out_dir = tmp_path / "observaciones_horarias"
        write_parquet(observaciones_df, out_dir, OBSERVACIONES_PARTITION_COLS)
        # Verifica que existen subdirectorios con Hive partitioning
        partition_dirs = list(out_dir.glob("year=*/month=*"))
        assert len(partition_dirs) > 0, "No se crearon particiones year/month"

    def test_parquet_no_index_column(
        self,
        observaciones_df: pd.DataFrame,
        tmp_path: Path,
    ) -> None:
        out_dir = tmp_path / "observaciones_horarias"
        write_parquet(observaciones_df, out_dir, OBSERVACIONES_PARTITION_COLS)
        table = pq.read_table(str(out_dir))
        # No debe haber columna "__index_level_0__" ni similar
        col_names = [c for c in table.schema.names if "index" in c.lower()]
        assert len(col_names) == 0, f"Columnas de índice encontradas: {col_names}"


# ---------------------------------------------------------------------------
# Tests de idempotencia
# ---------------------------------------------------------------------------


class TestIdempotence:
    def test_parquet_write_is_idempotent(
        self,
        observaciones_df: pd.DataFrame,
        tmp_path: Path,
    ) -> None:
        out_dir = tmp_path / "observaciones_horarias"
        write_parquet(observaciones_df, out_dir, OBSERVACIONES_PARTITION_COLS)
        # Segunda escritura (overwrite)
        write_parquet(observaciones_df, out_dir, OBSERVACIONES_PARTITION_COLS)
        table = pq.read_table(str(out_dir))
        # No debe duplicar filas
        assert table.num_rows == len(observaciones_df)
