"""Tests unitarios para etl/silver/rama_silver.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from etl.silver.rama_silver import (
    extract_pollutant,
    pivot_to_long,
    process_rama_file,
)
from etl.silver.shared import hora_to_datetime_local, replace_sentinel_nulls

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def dim_estaciones_df() -> pd.DataFrame:
    """Catálogo mínimo de estaciones para tests."""
    return pd.DataFrame(
        {
            "station_id": pd.array(["ACO", "BJU", "XAL"], dtype="string"),
            "latitude": [19.6355, 19.3705, 19.5239],
            "longitude": [-98.9120, -99.1596, -99.0148],
        }
    )


@pytest.fixture()
def rama_wide_df() -> pd.DataFrame:
    """DataFrame wide simulando un archivo Excel RAMA con 3 estaciones."""
    return pd.DataFrame(
        {
            "FECHA": pd.to_datetime(["2023-01-01"] * 3),
            "HORA": [1, 2, 3],
            "ACO": [10.0, -99.0, 15.0],
            "BJU": [20.0, 25.0, -99.0],
            "XAL": [-99.0, 30.0, 35.0],
            "UNKNOWN": [1.0, 2.0, 3.0],  # estación no en catálogo
        }
    )


# ---------------------------------------------------------------------------
# extract_pollutant
# ---------------------------------------------------------------------------


def test_extract_pollutant_o3() -> None:
    assert extract_pollutant(Path("2023O3.xls")) == "O3"


def test_extract_pollutant_pm25() -> None:
    assert extract_pollutant(Path("2021PM25.xls")) == "PM25"


def test_extract_pollutant_invalid_raises() -> None:
    with pytest.raises(ValueError, match="No se puede extraer"):
        extract_pollutant(Path("datos_sin_formato.xls"))


# ---------------------------------------------------------------------------
# hora_to_datetime_local (shared)
# ---------------------------------------------------------------------------


def test_hora_1_maps_to_hour_0() -> None:
    fecha = pd.Series(pd.to_datetime(["2023-01-01"]))
    hora = pd.Series([1])
    result = hora_to_datetime_local(fecha, hora)
    assert result.iloc[0] == pd.Timestamp("2023-01-01 00:00")


def test_hora_24_maps_to_hour_23() -> None:
    fecha = pd.Series(pd.to_datetime(["2023-01-01"]))
    hora = pd.Series([24])
    result = hora_to_datetime_local(fecha, hora)
    assert result.iloc[0] == pd.Timestamp("2023-01-01 23:00")


def test_hora_result_is_timezone_naive() -> None:
    fecha = pd.Series(pd.to_datetime(["2023-06-15"]))
    hora = pd.Series([12])
    result = hora_to_datetime_local(fecha, hora)
    assert result.dt.tz is None


# ---------------------------------------------------------------------------
# replace_sentinel_nulls (shared)
# ---------------------------------------------------------------------------


def test_sentinel_replaced_with_na() -> None:
    df = pd.DataFrame({"a": [1.0, -99.0, 3.0], "b": [-99.0, 2.0, -99.0]})
    df_clean, n = replace_sentinel_nulls(df)
    assert n == 3
    assert df_clean["a"].isna().sum() == 1
    assert df_clean["b"].isna().sum() == 2


def test_no_sentinel_returns_zero_count() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
    _, n = replace_sentinel_nulls(df)
    assert n == 0


def test_original_df_not_mutated() -> None:
    df = pd.DataFrame({"a": [-99.0, 2.0]})
    df_original = df.copy()
    replace_sentinel_nulls(df)
    pd.testing.assert_frame_equal(df, df_original)


# ---------------------------------------------------------------------------
# pivot_to_long
# ---------------------------------------------------------------------------


def test_pivot_produces_long_format(rama_wide_df: pd.DataFrame) -> None:
    df_long = pivot_to_long(rama_wide_df, "O3")
    # 3 filas × 4 estaciones = 12 registros
    assert len(df_long) == 12
    assert "station_id" in df_long.columns
    assert "pollutant" in df_long.columns
    assert "datetime_local" in df_long.columns
    assert "value" in df_long.columns


def test_pivot_sets_pollutant_correctly(rama_wide_df: pd.DataFrame) -> None:
    df_long = pivot_to_long(rama_wide_df, "PM25")
    assert (df_long["pollutant"] == "PM25").all()


def test_pivot_datetime_timezone_naive(rama_wide_df: pd.DataFrame) -> None:
    df_long = pivot_to_long(rama_wide_df, "O3")
    assert df_long["datetime_local"].dt.tz is None


def test_pivot_hora_1_gives_hour_0(rama_wide_df: pd.DataFrame) -> None:
    df_long = pivot_to_long(rama_wide_df, "O3")
    first_row = (
        df_long[df_long["station_id"] == "ACO"]
        .sort_values("datetime_local")
        .iloc[0]
    )
    assert first_row["datetime_local"].hour == 0


# ---------------------------------------------------------------------------
# process_rama_file (integración unitaria con mock de read_excel)
# ---------------------------------------------------------------------------


def test_process_rama_file_removes_sentinel(
    tmp_path: Path,
    dim_estaciones_df: pd.DataFrame,
) -> None:
    fake_excel = pd.DataFrame(
        {
            "FECHA": pd.to_datetime(["2023-01-01"] * 2),
            "HORA": [1, 2],
            "ACO": [5.0, -99.0],
            "BJU": [-99.0, 10.0],
        }
    )
    fake_path = tmp_path / "2023O3.xls"

    with patch("etl.silver.rama_silver.parse_rama_excel", return_value=fake_excel):
        df, metrics = process_rama_file(fake_path, dim_estaciones_df)

    assert metrics["null_replacements"] == 2
    assert df["value"].isna().sum() == 2


def test_process_rama_file_filters_unknown_stations(
    tmp_path: Path,
    dim_estaciones_df: pd.DataFrame,
) -> None:
    fake_excel = pd.DataFrame(
        {
            "FECHA": pd.to_datetime(["2023-01-01"]),
            "HORA": [1],
            "ACO": [10.0],
            "GHOST": [99.0],  # no está en catálogo
        }
    )
    fake_path = tmp_path / "2023O3.xls"

    with patch("etl.silver.rama_silver.parse_rama_excel", return_value=fake_excel):
        df, metrics = process_rama_file(fake_path, dim_estaciones_df)

    assert metrics["invalid_stations"] > 0
    assert "GHOST" not in df["station_id"].values


def test_process_rama_file_no_duplicates(
    tmp_path: Path,
    dim_estaciones_df: pd.DataFrame,
) -> None:
    fake_excel = pd.DataFrame(
        {
            "FECHA": pd.to_datetime(["2023-01-01"]),
            "HORA": [1],
            "ACO": [10.0],
        }
    )
    fake_path = tmp_path / "2023O3.xls"

    with patch("etl.silver.rama_silver.parse_rama_excel", return_value=fake_excel):
        df, _ = process_rama_file(fake_path, dim_estaciones_df)

    pk_cols = ["station_id", "pollutant", "datetime_local"]
    assert not df.duplicated(subset=pk_cols).any()


def test_process_rama_file_schema_dtypes(
    tmp_path: Path,
    dim_estaciones_df: pd.DataFrame,
) -> None:
    fake_excel = pd.DataFrame(
        {
            "FECHA": pd.to_datetime(["2023-03-01"]),
            "HORA": [6],
            "BJU": [42.0],
        }
    )
    fake_path = tmp_path / "2023O3.xls"

    with patch("etl.silver.rama_silver.parse_rama_excel", return_value=fake_excel):
        df, _ = process_rama_file(fake_path, dim_estaciones_df)

    assert df["station_id"].dtype == pd.StringDtype()
    assert df["value"].dtype == pd.Float64Dtype()
    assert str(df["year"].dtype) == "int16"
    assert str(df["month"].dtype) == "int8"
    assert str(df["hour"].dtype) == "int8"


def test_process_rama_file_invalid_ranges_nulled(
    tmp_path: Path,
    dim_estaciones_df: pd.DataFrame,
) -> None:
    # O3 max = 500, valor 999 debe quedar NULL
    fake_excel = pd.DataFrame(
        {
            "FECHA": pd.to_datetime(["2023-01-01"]),
            "HORA": [1],
            "BJU": [999.0],
        }
    )
    fake_path = tmp_path / "2023O3.xls"

    with patch("etl.silver.rama_silver.parse_rama_excel", return_value=fake_excel):
        df, metrics = process_rama_file(fake_path, dim_estaciones_df)

    assert metrics["invalid_ranges"] >= 1
    assert df["value"].isna().all()
