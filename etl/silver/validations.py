"""Validaciones de contrato y calidad para la capa Silver.

Funciones puras que validan DataFrames antes de escritura a Parquet.
Cada función retorna métricas o lanza ValueError en casos fatales.
"""

from __future__ import annotations

import pandas as pd

from utils.logging import get_logger

logger = get_logger(__name__)


def validate_no_duplicates(
    df: pd.DataFrame,
    pk_cols: list[str],
    context: str = "",
) -> int:
    """Cuenta duplicados por clave primaria y los registra.

    Args:
        df: DataFrame a validar.
        pk_cols: Columnas que forman la clave primaria.
        context: Etiqueta para logging.

    Returns:
        Número de filas duplicadas encontradas.
    """
    n_dups = int(df.duplicated(subset=pk_cols, keep=False).sum())
    if n_dups > 0:
        logger.warning(
            "Duplicados encontrados en clave primaria",
            extra={"context": context, "pk_cols": str(pk_cols), "count": n_dups},
        )
    return n_dups


def validate_station_ids(
    df: pd.DataFrame,
    dim_estaciones: pd.DataFrame,
    context: str = "",
) -> tuple[pd.DataFrame, int]:
    """Filtra registros con station_id no presentes en el catálogo.

    Args:
        df: DataFrame con columna ``station_id``.
        dim_estaciones: Catálogo con columna ``station_id``.
        context: Etiqueta para logging.

    Returns:
        Tupla (df_válido, n_inválidos).
    """
    valid_ids = set(dim_estaciones["station_id"])
    mask_invalid = ~df["station_id"].isin(valid_ids)
    n_invalid = int(mask_invalid.sum())
    if n_invalid > 0:
        invalid_sample = df.loc[mask_invalid, "station_id"].unique().tolist()
        logger.warning(
            "station_id desconocidos filtrados",
            extra={
                "context": context,
                "count": n_invalid,
                "sample": str(invalid_sample[:10]),
            },
        )
    return df.loc[~mask_invalid].copy(), n_invalid


def validate_value_ranges(
    df: pd.DataFrame,
    value_col: str,
    min_val: float,
    max_val: float,
    context: str = "",
) -> tuple[pd.DataFrame, int]:
    """Convierte a NULL los valores fuera del rango físico permitido.

    Args:
        df: DataFrame con la columna numérica a validar.
        value_col: Nombre de la columna de valores.
        min_val: Límite inferior válido (inclusive).
        max_val: Límite superior válido (inclusive).
        context: Etiqueta para logging.

    Returns:
        Tupla (df_corregido, n_inválidos).
    """
    mask_invalid = df[value_col].notna() & (
        (df[value_col] < min_val) | (df[value_col] > max_val)
    )
    n_invalid = int(mask_invalid.sum())
    if n_invalid > 0:
        logger.warning(
            "Valores fuera de rango convertidos a NULL",
            extra={
                "context": context,
                "column": value_col,
                "range": f"[{min_val}, {max_val}]",
                "count": n_invalid,
            },
        )
        df = df.copy()
        df.loc[mask_invalid, value_col] = pd.NA
    return df, n_invalid


def validate_timestamps_not_null(
    df: pd.DataFrame,
    context: str = "",
) -> None:
    """Falla si datetime_local contiene valores nulos.

    Args:
        df: DataFrame con columna ``datetime_local``.
        context: Etiqueta para mensaje de error.

    Raises:
        ValueError: Si existen NULLs en datetime_local.
    """
    nulls = int(df["datetime_local"].isna().sum())
    if nulls > 0:
        raise ValueError(
            f"[{context}] datetime_local contiene {nulls} NULLs. "
            "Verificar la lógica de parseo de timestamps."
        )


def validate_timezone_naive(
    df: pd.DataFrame,
    context: str = "",
) -> None:
    """Falla si datetime_local tiene timezone (debe ser naive UTC-6).

    Args:
        df: DataFrame con columna ``datetime_local``.
        context: Etiqueta para mensaje de error.

    Raises:
        ValueError: Si datetime_local tiene tzinfo distinto de None.
    """
    tz = getattr(df["datetime_local"].dt, "tz", None)
    if tz is not None:
        raise ValueError(
            f"[{context}] datetime_local tiene timezone '{tz}'. "
            "Silver requiere datetime naive (hora local CDMX UTC-6)."
        )


def validate_year_month_not_null(
    df: pd.DataFrame,
    context: str = "",
) -> None:
    """Falla si year o month tienen valores nulos.

    Args:
        df: DataFrame con columnas ``year`` y ``month``.
        context: Etiqueta para mensaje de error.

    Raises:
        ValueError: Si year o month tienen NULLs.
    """
    for col in ("year", "month"):
        if col in df.columns:
            nulls = int(df[col].isna().sum())
            if nulls > 0:
                raise ValueError(
                    f"[{context}] Columna '{col}' contiene {nulls} NULLs."
                )


def collect_quality_metrics(
    rows_input: int,
    rows_output: int,
    null_replacements: int,
    invalid_ranges: int,
    invalid_stations: int,
    duplicates_removed: int,
    partitions_created: list[str],
) -> dict[str, object]:
    """Construye el diccionario de métricas de calidad para logging.

    Args:
        rows_input: Filas antes de limpieza.
        rows_output: Filas después de limpieza.
        null_replacements: Centinelas -99 convertidos a NULL.
        invalid_ranges: Valores fuera de rango.
        invalid_stations: station_id no encontrados en catálogo.
        duplicates_removed: Duplicados eliminados.
        partitions_created: Lista de particiones Parquet escritas.

    Returns:
        Diccionario con todas las métricas.
    """
    return {
        "rows_input": rows_input,
        "rows_output": rows_output,
        "null_replacements": null_replacements,
        "invalid_ranges": invalid_ranges,
        "invalid_stations": invalid_stations,
        "duplicates_removed": duplicates_removed,
        "partitions_created": partitions_created,
        "retention_rate": round(rows_output / max(rows_input, 1), 4),
    }
