"""ETL Bronze → Silver para datos Open-Meteo.

Lee archivos JSON históricos por estación, aplana la estructura nested
``hourly.*``, normaliza timestamps y escribe Parquet particionado por year/month
en S3 (Medallion Architecture).

Salida: ``silver.meteo_horario`` en S3

Estructura Bronze esperada:
    data/raw/openmeteo/station_id=XXX/year=YYYY/openmeteo_XXX_YYYY.json

Estructura Silver generada en S3:
    s3://itam-analytics-antonio/air-sense-mx/silver/meteo_horario/
        year=YYYY/month=M/part-N.snappy.parquet

Uso:
    python -m etl.silver openmeteo --help
    python -m etl.silver openmeteo --start-year 2023 --end-year 2023
    python -m etl.silver openmeteo --station-id BJU --start-year 2021 --end-year 2024
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd

from etl.silver.schemas import (
    METEO_DTYPES,
    METEO_HOURLY_VARS,
    METEO_PARTITION_COLS,
    METEO_PK,
    METEO_VALID_RANGES,
)
from etl.silver.shared import (
    add_time_columns,
    load_dim_estaciones,
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


def parse_openmeteo_json(path: Path) -> pd.DataFrame:
    """Lee un archivo JSON de Open-Meteo y lo aplana a formato tabular.

    El JSON tiene estructura:
        {
          "latitude": float,
          "longitude": float,
          "hourly": {"time": [...], "temperature_2m": [...], ...},
          "_metadata": {"station_id": str, ...}
        }

    Args:
        path: Ruta al archivo JSON.

    Returns:
        DataFrame tabular con columnas: station_id, datetime_local,
        latitude, longitude y todas las variables hourly disponibles.

    Raises:
        KeyError: Si el JSON no tiene la clave ``hourly`` o ``_metadata``.
    """
    with path.open(encoding="utf-8") as fh:
        raw = json.load(fh)

    metadata = raw.get("_metadata", {})
    station_id = metadata.get("station_id") or path.parent.parent.name.replace(
        "station_id=", ""
    )
    latitude = metadata.get("latitude_actual") or raw.get("latitude")
    longitude = metadata.get("longitude_actual") or raw.get("longitude")

    hourly = raw["hourly"]
    times = hourly["time"]

    # Construir DataFrame con las variables hourly disponibles
    data: dict[str, object] = {
        "datetime_local": pd.to_datetime(times, format="ISO8601"),
    }
    for var in METEO_HOURLY_VARS:
        if var in hourly:
            data[var] = hourly[var]

    df = pd.DataFrame(data)
    df.insert(0, "station_id", station_id)
    df["latitude"] = latitude
    df["longitude"] = longitude

    logger.debug(
        "JSON Open-Meteo leído",
        extra={"path": str(path), "station_id": station_id, "rows": len(df)},
    )
    return df


def normalize_openmeteo(
    df: pd.DataFrame,
    dim_estaciones: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Aplica el pipeline completo de limpieza para datos Open-Meteo.

    Pasos:
        1. Validar station_id contra catálogo
        2. Validar rangos físicos por variable
        3. Validar timestamps
        4. Agregar columnas de tiempo
        5. Validar y eliminar duplicados
        6. Castear tipos al schema explícito

    Args:
        df: DataFrame resultado de :func:`parse_openmeteo_json`.
        dim_estaciones: Catálogo de estaciones para validación.

    Returns:
        Tupla (df_silver, métricas).
    """
    ctx = str(df["station_id"].iloc[0]) if len(df) > 0 else "unknown"
    rows_input = len(df)
    n_invalid_ranges = 0

    # Paso 1: Validar station_ids
    df["station_id"] = df["station_id"].astype("string")
    df, n_invalid_stations = validate_station_ids(df, dim_estaciones, context=ctx)

    # Paso 2: Validar rangos por variable meteorológica
    for var, (min_v, max_v) in METEO_VALID_RANGES.items():
        if var in df.columns:
            df, n_inv = validate_value_ranges(
                df, var, min_v, max_v, context=f"{ctx}:{var}"
            )
            n_invalid_ranges += n_inv

    # Paso 3: Validar timestamps (ya son datetime de parse_openmeteo_json)
    validate_timestamps_not_null(df, context=ctx)
    validate_timezone_naive(df, context=ctx)

    # Paso 4: Columnas de tiempo
    df = add_time_columns(df)
    validate_year_month_not_null(df, context=ctx)

    # Paso 5: Eliminar duplicados
    n_dups = validate_no_duplicates(df, METEO_PK, context=ctx)
    df = df.drop_duplicates(subset=METEO_PK, keep="first")

    # Paso 6: Castear a schema canónico
    for col, dtype in METEO_DTYPES.items():
        if col in df.columns and dtype != "datetime64[ns]":
            df[col] = df[col].astype(dtype)

    # Seleccionar solo columnas del schema
    output_cols = [c for c in METEO_DTYPES if c in df.columns]
    df = df[output_cols]

    partitions = [
        f"year={y}/month={m}"
        for y, m in df[["year", "month"]].drop_duplicates().itertuples(index=False)
    ]

    metrics = collect_quality_metrics(
        rows_input=rows_input,
        rows_output=len(df),
        null_replacements=0,  # Open-Meteo no usa -99
        invalid_ranges=n_invalid_ranges,
        invalid_stations=n_invalid_stations,
        duplicates_removed=n_dups,
        partitions_created=sorted(partitions),
    )

    return df, metrics


def run_openmeteo_silver(
    bronze_dir: Path,
    s3_silver_path: str,
    dim_path: Path,
    start_year: int,
    end_year: int,
    station_id_filter: str | None = None,
    overwrite: bool = False,
) -> dict[str, object]:
    """Orquesta el pipeline Open-Meteo Bronze → Silver para un rango de años.

    Descubre recursivamente todos los JSON en bronze_dir filtrando por año
    y opcionalmente por station_id, los procesa y escribe Parquet consolidado
    en S3.

    Args:
        bronze_dir: Directorio raíz Bronze Open-Meteo (``data/raw/openmeteo/``).
        s3_silver_path: Ruta S3 raíz del dataset Silver, e.g.
            ``"s3://itam-analytics-antonio/air-sense-mx/silver/meteo_horario/"``.
        dim_path: Ruta a ``dim_estaciones.csv``.
        start_year: Primer año a procesar (inclusive).
        end_year: Último año a procesar (inclusive).
        station_id_filter: Si se especifica, solo procesa esa estación.
        overwrite: Si True, sobreescribe particiones existentes.

    Returns:
        Métricas agregadas del proceso.
    """
    t0 = time.monotonic()
    logger.info(
        "Inicio pipeline Open-Meteo Silver",
        extra={
            "bronze_dir": str(bronze_dir),
            "s3_silver_path": s3_silver_path,
            "start_year": start_year,
            "end_year": end_year,
            "station_id_filter": station_id_filter,
            "overwrite": overwrite,
        },
    )

    dim_estaciones = load_dim_estaciones(dim_path)

    # Descubrir archivos JSON por rango de años y estación
    all_files: list[Path] = []
    station_dirs = sorted(bronze_dir.iterdir()) if bronze_dir.exists() else []
    for station_dir in station_dirs:
        if not station_dir.is_dir():
            continue
        sid = station_dir.name.replace("station_id=", "")
        if station_id_filter and sid != station_id_filter:
            continue
        for year in range(start_year, end_year + 1):
            year_dir = station_dir / f"year={year}"
            if not year_dir.exists():
                continue
            all_files.extend(sorted(year_dir.glob("*.json")))

    if not all_files:
        logger.warning(
            "No se encontraron archivos JSON en Bronze Open-Meteo",
            extra={"bronze_dir": str(bronze_dir)},
        )
        return {"files_found": 0}

    logger.info("Archivos Open-Meteo descubiertos", extra={"count": len(all_files)})

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
            df_raw = parse_openmeteo_json(path)
            df_silver, metrics = normalize_openmeteo(df_raw, dim_estaciones)
            frames.append(df_silver)
            for key in ("rows_input", "rows_output", "null_replacements",
                        "invalid_ranges", "invalid_stations", "duplicates_removed"):
                total_metrics[key] += int(metrics.get(key, 0))
            total_metrics["files_processed"] += 1
        except Exception as exc:
            logger.error(
                "Error procesando archivo Open-Meteo",
                extra={"path": str(path), "error": str(exc)},
            )
            total_metrics["files_failed"] += 1

    if not frames:
        logger.error("Ningún archivo pudo procesarse. Abortando escritura Silver.")
        return total_metrics

    # Consolidar y escribir Parquet
    df_all = pd.concat(frames, ignore_index=True)
    df_all = df_all.drop_duplicates(subset=METEO_PK, keep="first")

    write_s3_parquet(
        df_all,
        s3_silver_path,
        METEO_PARTITION_COLS,
        context="meteo_horario",
    )

    elapsed = round(time.monotonic() - t0, 2)
    total_metrics["duration_seconds"] = elapsed  # type: ignore[assignment]

    logger.info(
        "Pipeline Open-Meteo Silver completado",
        extra=total_metrics,
    )

    return total_metrics
