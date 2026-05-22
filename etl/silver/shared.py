"""Utilidades compartidas para la capa Silver.

Funciones puras reutilizadas por rama_silver.py y openmeteo_silver.py:
normalización de timestamps, reemplazo de centinelas y carga de catálogos.
"""

from __future__ import annotations

from pathlib import Path

import awswrangler as wr
import pandas as pd

from utils.logging import get_logger

logger = get_logger(__name__)

#: Valor centinela que RAMA usa para datos faltantes
SENTINEL_VALUE: int = -99


def replace_sentinel_nulls(
    df: pd.DataFrame,
    sentinel: int = SENTINEL_VALUE,
) -> tuple[pd.DataFrame, int]:
    """Reemplaza el valor centinela con ``pd.NA`` en todo el DataFrame.

    Args:
        df: DataFrame con posibles valores centinela.
        sentinel: Valor a sustituir (por defecto ``-99``).

    Returns:
        Tupla (df_limpio, n_reemplazos).
    """
    n_replacements = int((df == sentinel).sum().sum())
    df = df.replace(sentinel, pd.NA)
    return df, n_replacements


def hora_to_datetime_local(
    fecha: pd.Series,
    hora: pd.Series,
) -> pd.Series:
    """Convierte columnas FECHA + HORA(1-24) a datetime_local con hora 0-23.

    En los archivos RAMA, HORA=1 corresponde a las 00:00 del día indicado
    en FECHA, y HORA=24 corresponde a las 23:00.

    Args:
        fecha: Serie con la fecha del registro (puede tener componente hora
            ignorada, pues es repetida para todas las horas del día).
        hora: Serie entera con valores 1-24 (convención SIMAT).

    Returns:
        Serie ``datetime64[ns]`` timezone-naive con hora en rango [0, 23].
    """
    base_date = pd.to_datetime(fecha).dt.normalize()
    return base_date + pd.to_timedelta(hora.astype(int) - 1, unit="h")


def load_dim_estaciones(dim_path: Path) -> pd.DataFrame:
    """Carga el catálogo maestro de estaciones RAMA.

    Args:
        dim_path: Ruta al archivo ``dim_estaciones.csv``.

    Returns:
        DataFrame con columnas ``station_id``, ``latitude``, ``longitude``
        y otras columnas del catálogo.
    """
    df = pd.read_csv(dim_path, dtype={"station_id": "string"})
    logger.debug(
        "Catálogo dim_estaciones cargado",
        extra={"rows": len(df), "path": str(dim_path)},
    )
    return df


def add_time_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega columnas derivadas year, month, day, hour desde datetime_local.

    Args:
        df: DataFrame con columna ``datetime_local`` (datetime64[ns] naive).

    Returns:
        DataFrame con columnas year (int16), month (int8), day (int8),
        hour (int8) agregadas.
    """
    return df.assign(
        year=df["datetime_local"].dt.year.astype("int16"),
        month=df["datetime_local"].dt.month.astype("int8"),
        day=df["datetime_local"].dt.day.astype("int8"),
        hour=df["datetime_local"].dt.hour.astype("int8"),
    )


def write_parquet(
    df: pd.DataFrame,
    output_dir: Path,
    partition_cols: list[str],
    context: str = "",
) -> int:
    """Escribe DataFrame a Parquet con compresión Snappy y particionamiento Hive.

    Args:
        df: DataFrame a escribir (sin índice pandas).
        output_dir: Directorio raíz de salida.
        partition_cols: Columnas para particionamiento Hive (e.g. year/month).
        context: Etiqueta para logging.

    Returns:
        Número de filas escritas.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(
        output_dir,
        engine="pyarrow",
        compression="snappy",
        index=False,
        partition_cols=partition_cols,
        existing_data_behavior="delete_matching",
    )
    n_rows = len(df)
    logger.info(
        "Parquet escrito",
        extra={"context": context, "rows": n_rows, "output_dir": str(output_dir)},
    )
    return n_rows


def write_s3_parquet(
    df: pd.DataFrame,
    s3_path: str,
    partition_cols: list[str],
    context: str = "",
) -> int:
    """Escribe DataFrame a S3 como Parquet Snappy con particionamiento Hive.

    Usa ``awswrangler.s3.to_parquet`` en modo ``overwrite_partitions``:
    solo sobrescribe las particiones year/month presentes en el DataFrame,
    dejando el resto intactas (procesamiento incremental idempotente).

    Compatible con AWS Athena, Glue Data Catalog y DuckDB.

    Args:
        df: DataFrame a escribir (sin índice pandas).
        s3_path: Ruta S3 raíz del dataset, e.g.
            ``"s3://bucket/air-sense-mx/silver/observaciones_horarias/"``.
        partition_cols: Columnas para particionamiento Hive (["year", "month"]).
        context: Etiqueta para logging.

    Returns:
        Número de filas escritas.
    """
    wr.s3.to_parquet(
        df=df,
        path=s3_path,
        dataset=True,
        mode="overwrite_partitions",
        partition_cols=partition_cols,
        compression="snappy",
        index=False,
    )
    n_rows = len(df)
    logger.info(
        "Parquet escrito en S3",
        extra={"context": context, "rows": n_rows, "s3_path": s3_path},
    )
    return n_rows
