"""ETL Bronze → Silver para datos RAMA/SIMAT.

Lee archivos Excel históricos de contaminantes, convierte de formato wide
a long (tidy), limpia valores centinela (-99), normaliza timestamps a
hora local CDMX y escribe Parquet particionado por year/month en S3.

Salida: ``silver.observaciones_horarias`` en S3 (Medallion Architecture)

Estructura Bronze esperada:
    data/raw/rama/year=YYYY/YYYY{POLLUTANT}.xls

Estructura Silver generada en S3:
    s3://itam-analytics-antonio/air-sense-mx/silver/observaciones_horarias/
        year=YYYY/month=M/part-N.snappy.parquet

Uso:
    python -m etl.silver rama --help
    python -m etl.silver rama --start-year 2023 --end-year 2023
    python -m etl.silver rama --start-year 2021 --end-year 2024 --overwrite
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import pandas as pd

from etl.silver.schemas import (
    OBSERVACIONES_DTYPES,
    OBSERVACIONES_PARTITION_COLS,
    OBSERVACIONES_PK,
    POLLUTANT_VALID_RANGES,
)
from etl.silver.shared import (
    add_time_columns,
    hora_to_datetime_local,
    load_dim_estaciones,
    replace_sentinel_nulls,
    write_s3_parquet,
)
from etl.silver.validations import (
    collect_quality_metrics,
    validate_no_duplicates,
    validate_station_ids,
    validate_timestamps_not_null,
    validate_timezone_naive,
    validate_value_ranges,
    validate_year_month_not_null,
)
from utils.logging import get_logger

logger = get_logger(__name__)

_POLLUTANT_RE = re.compile(r"\d{4}([A-Za-z0-9]+)\.xls", re.IGNORECASE)


def extract_pollutant(path: Path) -> str:
    """Extrae el nombre del contaminante desde el nombre del archivo Excel.

    Args:
        path: Ruta al archivo, e.g. ``2023O3.xls``.

    Returns:
        Nombre del contaminante, e.g. ``"O3"``.

    Raises:
        ValueError: Si el nombre no sigue la convención ``YYYYCONTAMINANTE.xls``.
    """
    match = _POLLUTANT_RE.search(path.name)
    if not match:
        raise ValueError(
            f"No se puede extraer contaminante de '{path.name}'. "
            "Formato esperado: 'YYYYCONTAMINANTE.xls' (e.g. '2023O3.xls')."
        )
    return match.group(1).upper()


def parse_rama_excel(path: Path) -> pd.DataFrame:
    """Lee un archivo Excel RAMA en formato wide.

    Formato esperado:
        - Fila 0: encabezados (FECHA, HORA, ACO, AJM, ...)
        - Filas 1+: datos con FECHA repetida por día y HORA en [1, 24]

    Args:
        path: Ruta al archivo ``.xls``.

    Returns:
        DataFrame con columnas FECHA, HORA y estaciones como columnas.
    """
    df = pd.read_excel(path, header=0, dtype={"HORA": "int16"})
    logger.debug(
        "Excel RAMA leído",
        extra={"path": str(path), "rows": len(df), "cols": df.shape[1]},
    )
    return df


def pivot_to_long(df: pd.DataFrame, pollutant: str) -> pd.DataFrame:
    """Convierte DataFrame wide a formato long (tidy).

    Una fila de salida = un registro horario por estación y contaminante.
    HORA(1-24) se convierte a datetime_local con hora [0-23].

    Args:
        df: DataFrame wide con columnas FECHA, HORA y station_ids.
        pollutant: Nombre del contaminante (e.g. ``"O3"``).

    Returns:
        DataFrame long con columnas: station_id, pollutant, datetime_local, value.
    """
    station_cols = [c for c in df.columns if c not in ("FECHA", "HORA")]

    df_long = df.melt(
        id_vars=["FECHA", "HORA"],
        value_vars=station_cols,
        var_name="station_id",
        value_name="value",
    )

    df_long = df_long.assign(
        pollutant=pollutant,
        datetime_local=hora_to_datetime_local(df_long["FECHA"], df_long["HORA"]),
        station_id=df_long["station_id"].astype("string"),
    ).drop(columns=["FECHA", "HORA"])

    return df_long


def process_rama_file(
    path: Path,
    dim_estaciones: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Aplica el pipeline completo Bronze → Silver para un archivo Excel RAMA.

    Pasos:
        1. Extraer nombre del contaminante del filename
        2. Leer Excel en formato wide
        3. Pivotar a formato long
        4. Reemplazar -99 con NULL
        5. Validar station_ids contra catálogo
        6. Validar rangos físicos (fuera de rango → NULL)
        7. Validar timestamps
        8. Enriquecer con lat/lon desde dim_estaciones
        9. Agregar columnas de tiempo (year, month, day, hour)
        10. Validar y eliminar duplicados
        11. Castear tipos al schema explícito

    Args:
        path: Ruta al archivo ``.xls`` Bronze.
        dim_estaciones: DataFrame del catálogo de estaciones.

    Returns:
        Tupla (df_silver, métricas).
    """
    pollutant = extract_pollutant(path)
    ctx = path.name

    logger.info(
        "Procesando archivo RAMA",
        extra={"path": str(path), "pollutant": pollutant},
    )

    df_wide = parse_rama_excel(path)
    df = pivot_to_long(df_wide, pollutant)
    rows_input = len(df)

    # Paso 1: Reemplazar centinelas -99 → NULL
    value_df, n_nulls = replace_sentinel_nulls(df[["value"]])
    df["value"] = value_df["value"].astype("Float64")

    # Paso 2: Filtrar estaciones desconocidas
    df, n_invalid_stations = validate_station_ids(df, dim_estaciones, context=ctx)

    # Paso 3: Validar rangos físicos
    p_range = POLLUTANT_VALID_RANGES.get(pollutant, (0.0, 10_000.0))
    df, n_invalid_ranges = validate_value_ranges(
        df, "value", p_range[0], p_range[1], context=f"{ctx}:{pollutant}"
    )

    # Paso 4: Validar timestamps (falla si hay NULLs)
    validate_timestamps_not_null(df, context=ctx)
    validate_timezone_naive(df, context=ctx)

    # Paso 5: Enriquecer con coordenadas
    coords = (
        dim_estaciones[["station_id", "latitude", "longitude"]]
        .assign(station_id=lambda d: d["station_id"].astype("string"))
        .drop_duplicates("station_id")
    )
    df = df.merge(coords, on="station_id", how="left")

    # Paso 6: Columnas de tiempo derivadas
    df = add_time_columns(df)
    validate_year_month_not_null(df, context=ctx)

    # Paso 7: Eliminar duplicados
    n_dups = validate_no_duplicates(df, OBSERVACIONES_PK, context=ctx)
    df = df.drop_duplicates(subset=OBSERVACIONES_PK, keep="first")

    # Paso 8: Castear a schema canónico
    for col, dtype in OBSERVACIONES_DTYPES.items():
        if col in df.columns and dtype != "datetime64[ns]":
            df[col] = df[col].astype(dtype)

    # Seleccionar solo columnas del schema (en orden canónico)
    output_cols = [c for c in OBSERVACIONES_DTYPES if c in df.columns]
    df = df[output_cols]

    partitions = [
        f"year={y}/month={m}"
        for y, m in df[["year", "month"]].drop_duplicates().itertuples(index=False)
    ]

    metrics = collect_quality_metrics(
        rows_input=rows_input,
        rows_output=len(df),
        null_replacements=n_nulls,
        invalid_ranges=n_invalid_ranges,
        invalid_stations=n_invalid_stations,
        duplicates_removed=n_dups,
        partitions_created=sorted(partitions),
    )

    logger.info(
        "Archivo RAMA procesado",
        extra={"path": str(path), "pollutant": pollutant, **metrics},
    )

    return df, metrics


def run_rama_silver(
    bronze_dir: Path,
    s3_silver_path: str,
    dim_path: Path,
    start_year: int,
    end_year: int,
    overwrite: bool = False,
) -> dict[str, object]:
    """Orquesta el pipeline RAMA Bronze → Silver para un rango de años.

    Descubre automáticamente todos los archivos ``.xls`` en bronze_dir
    dentro del rango de años indicado, los procesa y consolida la salida
    por año/mes antes de escribir Parquet en S3.

    Args:
        bronze_dir: Directorio raíz Bronze RAMA (``data/raw/rama/``).
        s3_silver_path: Ruta S3 raíz del dataset Silver, e.g.
            ``"s3://itam-analytics-antonio/air-sense-mx/silver/observaciones_horarias/"``.
        dim_path: Ruta a ``dim_estaciones.csv``.
        start_year: Primer año a procesar (inclusive).
        end_year: Último año a procesar (inclusive).
        overwrite: Si True, sobreescribe particiones existentes.

    Returns:
        Métricas agregadas del proceso.
    """
    t0 = time.monotonic()
    logger.info(
        "Inicio pipeline RAMA Silver",
        extra={
            "bronze_dir": str(bronze_dir),
            "s3_silver_path": s3_silver_path,
            "start_year": start_year,
            "end_year": end_year,
            "overwrite": overwrite,
        },
    )

    dim_estaciones = load_dim_estaciones(dim_path)

    # Descubrir archivos por rango de años
    all_files: list[Path] = []
    for year in range(start_year, end_year + 1):
        year_dir = bronze_dir / f"year={year}"
        if not year_dir.exists():
            logger.warning(
                "Directorio Bronze no encontrado",
                extra={"year": year, "path": str(year_dir)},
            )
            continue
        year_files = sorted(year_dir.glob("*.xls"))
        all_files.extend(year_files)

    if not all_files:
        logger.warning(
            "No se encontraron archivos .xls en Bronze RAMA",
            extra={"bronze_dir": str(bronze_dir)},
        )
        return {"files_found": 0}

    logger.info("Archivos RAMA descubiertos", extra={"count": len(all_files)})

    # Procesar todos los archivos y acumular por (year, month)
    frames: list[pd.DataFrame] = []
    total_metrics: dict[str, int] = {
        "rows_input": 0,
        "rows_output": 0,
        "null_replacements": 0,
        "invalid_ranges": 0,
        "invalid_stations": 0,
        "duplicates_removed": 0,
        "files_processed": 0,
        "files_failed": 0,
    }

    for path in all_files:
        try:
            df, metrics = process_rama_file(path, dim_estaciones)
            frames.append(df)
            for key in ("rows_input", "rows_output", "null_replacements",
                        "invalid_ranges", "invalid_stations", "duplicates_removed"):
                total_metrics[key] += int(metrics.get(key, 0))
            total_metrics["files_processed"] += 1
        except Exception as exc:
            logger.error(
                "Error procesando archivo RAMA",
                extra={"path": str(path), "error": str(exc)},
            )
            total_metrics["files_failed"] += 1

    if not frames:
        logger.error("Ningún archivo pudo procesarse. Abortando escritura Silver.")
        return total_metrics

    # Consolidar y escribir Parquet particionado
    df_all = pd.concat(frames, ignore_index=True)
    df_all = df_all.drop_duplicates(subset=OBSERVACIONES_PK, keep="first")

    write_s3_parquet(
        df_all,
        s3_silver_path,
        OBSERVACIONES_PARTITION_COLS,
        context="observaciones_horarias",
    )

    elapsed = round(time.monotonic() - t0, 2)
    total_metrics["duration_seconds"] = elapsed  # type: ignore[assignment]

    logger.info(
        "Pipeline RAMA Silver completado",
        extra=total_metrics,
    )

    return total_metrics
