r"""Ingesta Bronze de datos meteorológicos históricos desde Open-Meteo.

Descarga datos horarios por estación y año desde la Open-Meteo Historical
Weather API y los guarda como JSON crudo en la estructura Bronze local.

Estructura de salida::

    data/raw/openmeteo/
      station_id=XXX/
        year=YYYY/
          openmeteo_XXX_YYYY.json

La descarga es idempotente: si el archivo ya existe no se vuelve a descargar,
salvo que se indique ``overwrite=True``.

Uso::

    uv run python -m etl.openmeteo_bronze \\
      --stations-path data/dim_estaciones.csv \\
      --output-dir data/raw/openmeteo \\
      --start-year 2020
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from utils.logging import get_logger, setup_logging

logger = get_logger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────

OPEN_METEO_BASE_URL = "https://archive-api.open-meteo.com/v1/archive"

HOURLY_VARIABLES: list[str] = [
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

TIMEZONE = "America/Mexico_City"
REQUEST_TIMEOUT_SECONDS = 60
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 5.0


# ── Funciones públicas ────────────────────────────────────────────────────────


def load_active_stations(stations_path: Path) -> pd.DataFrame:
    """Carga estaciones activas desde el archivo CSV dimensional.

    Args:
        stations_path: Ruta al archivo ``dim_estaciones.csv``.

    Returns:
        DataFrame con las filas donde ``is_active`` es ``True``.
        Columnas garantizadas: ``station_id``, ``latitude``, ``longitude``, ``zone``.

    Raises:
        FileNotFoundError: Si el archivo no existe.
        ValueError: Si faltan columnas requeridas.
    """
    if not stations_path.exists():
        raise FileNotFoundError(f"Archivo de estaciones no encontrado: {stations_path}")

    df = pd.read_csv(stations_path)

    required_cols = {"station_id", "latitude", "longitude", "zone", "is_active"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Columnas faltantes en {stations_path}: {missing}")

    active = df[df["is_active"].astype(str).str.upper() == "TRUE"].copy()
    active = active.reset_index(drop=True)

    logger.info(
        "Estaciones cargadas",
        extra={"total": len(df), "active": len(active), "path": str(stations_path)},
    )
    return active


def build_openmeteo_url(
    latitude: float,
    longitude: float,
    year: int,
) -> tuple[str, dict[str, Any]]:
    """Construye la URL base y los parámetros para una solicitud a Open-Meteo.

    Args:
        latitude: Latitud de la estación en grados decimales.
        longitude: Longitud de la estación en grados decimales.
        year: Año a descargar (e.g. 2023).

    Returns:
        Tupla ``(url_base, params)`` lista para pasar a ``requests.get``.
    """
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"
    # Para el año en curso, limitar hasta hoy
    if year == date.today().year:
        end_date = date.today().isoformat()

    params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": ",".join(HOURLY_VARIABLES),
        "timezone": TIMEZONE,
    }
    return OPEN_METEO_BASE_URL, params


def download_openmeteo_year(
    station_id: str,
    latitude: float,
    longitude: float,
    year: int,
) -> dict[str, Any]:
    """Descarga datos horarios de Open-Meteo para una estación y un año.

    Reintenta hasta ``RETRY_ATTEMPTS`` veces con backoff exponencial ante
    errores de red o respuestas 5xx.

    Args:
        station_id: Identificador de la estación (usado solo para logging).
        latitude: Latitud de la estación.
        longitude: Longitud de la estación.
        year: Año a descargar.

    Returns:
        Diccionario con la respuesta JSON de la API más un campo
        ``_metadata`` con información de ingestión.

    Raises:
        requests.HTTPError: Si la API devuelve un error 4xx no recuperable.
        requests.ConnectionError: Si no hay conectividad tras todos los reintentos.
    """
    url, params = build_openmeteo_url(latitude, longitude, year)

    last_exc: Exception | None = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            logger.debug(
                "Solicitando datos Open-Meteo",
                extra={"station_id": station_id, "year": year, "attempt": attempt},
            )
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            payload: dict[str, Any] = response.json()

            lat_actual: float | None = payload.get("latitude")
            lon_actual: float | None = payload.get("longitude")

            payload["_metadata"] = {
                "station_id": station_id,
                "year": year,
                # Coordenadas del dim_estaciones.csv — usadas como parámetro de búsqueda
                "latitude_requested": latitude,
                "longitude_requested": longitude,
                # Coordenadas del grid ECMWF más cercano devueltas por Open-Meteo
                "latitude_actual": lat_actual,
                "longitude_actual": lon_actual,
                "ingested_at": datetime.now().isoformat(),
                "source_url": response.url,
                "hourly_variables": HOURLY_VARIABLES,
            }

            # Advertir si Open-Meteo resolvió a un grid point alejado >0.1°
            if lat_actual is not None and lon_actual is not None:
                lat_diff = abs(latitude - lat_actual)
                lon_diff = abs(longitude - lon_actual)
                if lat_diff > 0.1 or lon_diff > 0.1:
                    logger.warning(
                        "Grid snap significativo: coordenadas reales difieren del CSV",
                        extra={
                            "station_id": station_id,
                            "lat_csv": latitude,
                            "lon_csv": longitude,
                            "lat_grid": lat_actual,
                            "lon_grid": lon_actual,
                            "lat_diff": round(lat_diff, 4),
                            "lon_diff": round(lon_diff, 4),
                        },
                    )

            logger.info(
                "Descarga completada",
                extra={
                    "station_id": station_id,
                    "year": year,
                    "lat_csv": latitude,
                    "lon_csv": longitude,
                    "lat_grid": lat_actual,
                    "lon_grid": lon_actual,
                },
            )
            return payload

        except requests.HTTPError as exc:
            # Errores 4xx no son recuperables
            if exc.response is not None and exc.response.status_code < 500:
                raise
            last_exc = exc
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc

        wait = RETRY_BACKOFF_SECONDS * attempt
        logger.warning(
            "Error en descarga, reintentando",
            extra={
                "station_id": station_id,
                "year": year,
                "attempt": attempt,
                "wait_s": wait,
            },
        )
        time.sleep(wait)

    raise requests.ConnectionError(
        f"Fallaron {RETRY_ATTEMPTS} intentos para {station_id} año {year}"
    ) from last_exc


def build_output_path(output_dir: Path, station_id: str, year: int) -> Path:
    """Construye la ruta de salida siguiendo la convención Bronze.

    Args:
        output_dir: Directorio raíz de salida (e.g. ``data/raw/openmeteo``).
        station_id: Identificador de la estación.
        year: Año de los datos.

    Returns:
        Ruta completa al archivo JSON de salida.
    """
    return (
        output_dir
        / f"station_id={station_id}"
        / f"year={year}"
        / f"openmeteo_{station_id}_{year}.json"
    )


def save_raw_json(path: Path, data: dict[str, Any]) -> None:
    """Guarda un diccionario como JSON compacto en disco.

    Crea los directorios intermedios si no existen.

    Args:
        path: Ruta completa del archivo de destino.
        data: Datos a serializar.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    logger.debug(
        "JSON guardado", extra={"path": str(path), "bytes": path.stat().st_size}
    )


def run_openmeteo_bronze_ingestion(
    stations_path: Path,
    output_dir: Path,
    start_year: int = 2020,
    end_year: int | None = None,
    overwrite: bool = False,
) -> dict[str, int]:
    """Orquesta la descarga Open-Meteo para todas las estaciones activas.

    Para cada combinación (estación, año), verifica si el archivo ya existe y lo
    omite salvo que ``overwrite=True``.

    Args:
        stations_path: Ruta al archivo ``dim_estaciones.csv``.
        output_dir: Directorio raíz donde guardar los JSON.
        start_year: Primer año a descargar (inclusive). Por defecto 2020.
        end_year: Último año a descargar (inclusive). Por defecto año actual.
        overwrite: Si es ``True``, sobreescribe archivos existentes.

    Returns:
        Diccionario con conteos: ``{"downloaded": N, "skipped": N, "failed": N}``.
    """
    if end_year is None:
        end_year = date.today().year

    stations = load_active_stations(stations_path)
    years = list(range(start_year, end_year + 1))
    total = len(stations) * len(years)

    stats = {"downloaded": 0, "skipped": 0, "failed": 0}

    logger.info(
        "Iniciando ingesta Open-Meteo Bronze",
        extra={
            "stations": len(stations),
            "years": years,
            "total_requests": total,
            "overwrite": overwrite,
        },
    )

    for _, row in stations.iterrows():
        station_id: str = str(row["station_id"])
        latitude: float = float(row["latitude"])
        longitude: float = float(row["longitude"])

        logger.info(
            "Procesando estación",
            extra={"station_id": station_id, "lat": latitude, "lon": longitude},
        )

        for year in years:
            output_path = build_output_path(output_dir, station_id, year)

            if output_path.exists() and not overwrite:
                logger.debug(
                    "Archivo existente, omitiendo",
                    extra={
                        "station_id": station_id,
                        "year": year,
                        "path": str(output_path),
                    },
                )
                stats["skipped"] += 1
                continue

            try:
                payload = download_openmeteo_year(station_id, latitude, longitude, year)
                save_raw_json(output_path, payload)
                stats["downloaded"] += 1
                # Pausa cortés entre solicitudes
                time.sleep(0.5)
            except Exception as exc:
                logger.error(
                    "Fallo en descarga",
                    extra={"station_id": station_id, "year": year, "error": str(exc)},
                )
                stats["failed"] += 1

    logger.info(
        "Ingesta Open-Meteo Bronze finalizada",
        extra=stats,
    )
    return stats


# ── CLI ───────────────────────────────────────────────────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingesta Bronze de datos históricos Open-Meteo por estación y año."
    )
    parser.add_argument(
        "--stations-path",
        type=Path,
        default=Path("data/dim_estaciones.csv"),
        help="Ruta al archivo dim_estaciones.csv (default: data/dim_estaciones.csv)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw/openmeteo"),
        help="Directorio raíz de salida Bronze (default: data/raw/openmeteo)",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=2020,
        help="Primer año a descargar inclusive (default: 2020)",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=None,
        help="Último año a descargar inclusive (default: año actual)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Sobreescribir archivos existentes",
    )
    return parser


def main() -> None:
    """Punto de entrada CLI para la ingesta Bronze de Open-Meteo."""
    setup_logging()
    parser = _build_arg_parser()
    args = parser.parse_args()

    stats = run_openmeteo_bronze_ingestion(
        stations_path=args.stations_path,
        output_dir=args.output_dir,
        start_year=args.start_year,
        end_year=args.end_year,
        overwrite=args.overwrite,
    )

    if stats["failed"] > 0:
        raise SystemExit(
            f"Ingesta completada con {stats['failed']} errores. "
            f"Descargados: {stats['downloaded']}, Omitidos: {stats['skipped']}"
        )


if __name__ == "__main__":
    main()
