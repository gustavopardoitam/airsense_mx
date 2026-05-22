"""Capa Bronze: ingesta de datos meteorológicos históricos de Open-Meteo.

Descarga datos horarios de meteorología para 5 centroides de zona en la ZMVM
y almacena respuestas JSON crudas en S3 Bronze.

Decisiones de diseño:
- Una solicitud por (zona, año) → 25 llamadas API total para 5 zonas × 5 años.
  Justificación: Open-Meteo utiliza una grilla ECMWF de ~9km. Estaciones dentro
  de la misma zona reciben valores prácticamente idénticos, por lo que los
  centroides por zona son suficientes.
- Idempotente: verifica la existencia de la clave S3 vía head_object antes de
  cada llamada API. Es seguro ejecutar múltiples veces sin sobrescribir datos válidos.
- JSON crudo almacenado tal cual (principio Bronze: cero transformación aquí).
  Se añade un sobre de metadatos (_metadata) sin modificar el cuerpo de la API.
- Timezone: America/Mexico_City. Datos pre-Nov-2022 incluyen DST (UTC-5 verano).
  El ETL de Silver es responsable de normalizar a UTC-6 consistente.

Ruta S3:
    s3://airsense-mx/bronze/open_meteo/zone={zone}/year={year}/
        meteo_{zone}_{year}.json

Uso:
    python -m etl.bronze_open_meteo                   # todas las zonas, 2020-2024
    python -m etl.bronze_open_meteo --years 2023 2024
    python -m etl.bronze_open_meteo --zones NO NE
    python -m etl.bronze_open_meteo --dry-run         # obtener pero omitir S3
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from typing import Any

import boto3
import requests
from botocore.exceptions import ClientError

from utils.logging import get_logger, setup_logging

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration — edit here, nowhere else
# ---------------------------------------------------------------------------

OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Only ingest the variables agreed in the data contract.
# Do NOT add variables without updating silver.meteo_horario schema first.
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

# Centroids derived from the geographic spread of RAMA stations.
# Adjust using dim_estaciones.csv if a better centroid is identified.
# Format: {zone_id: (latitude, longitude)}
ZONE_CENTROIDS: dict[str, tuple[float, float]] = {
    "CE": (19.391, -99.110),  # Centro Histórico / Merced
    "NO": (19.540, -99.235),  # Tlalnepantla / Azcapotzalco
    "NE": (19.485, -99.020),  # Ecatepec / Neza-Chalco-Itza
    "SO": (19.310, -99.185),  # Pedregal / Copilco
    "SE": (19.330, -98.990),  # Tláhuac / Iztapalapa
}

DEFAULT_YEARS: list[int] = list(range(2020, 2025))  # 2020–2024 inclusive

S3_BUCKET = "airsense-mx"
REQUEST_TIMEOUT_SECONDS = 60
SLEEP_BETWEEN_REQUESTS = 1.0  # seconds — polite usage of the free API


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------


def build_s3_key(zone: str, year: int) -> str:
    """Construye la clave S3 para una zona y año dados.

    Args:
        zone: Identificador de zona (CE/NO/NE/SO/SE).
        year: Año calendario (p.ej. 2020).

    Returns:
        Clave S3 completa sin prefijo del bucket.

    Ejemplo:
        >>> build_s3_key("NO", 2022)
        'bronze/open_meteo/zone=NO/year=2022/meteo_NO_2022.json'
    """
    return f"bronze/open_meteo/zone={zone}/year={year}/meteo_{zone}_{year}.json"


def s3_key_exists(s3_client: Any, bucket: str, key: str) -> bool:
    """Verifica si un objeto S3 ya existe (puerta de idempotencia).

    Utiliza head_object que es más económico que get_object y no
    descarga el cuerpo del objeto.

    Args:
        s3_client: Cliente S3 de Boto3.
        bucket: Nombre del bucket S3.
        key: Clave del objeto S3.

    Returns:
        True si el objeto existe, False si retorna 404.

    Raises:
        ClientError: Para cualquier error distinto a 404 (p.ej. permiso denegado).
    """
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "404":
            return False
        raise  # 403, 5xx, etc. must propagate — we shouldn't silently skip


def upload_json_to_s3(s3_client: Any, bucket: str, key: str, data: dict) -> None:
    """Serializa un diccionario a JSON compacto y lo carga a S3.

    Args:
        s3_client: Cliente S3 de Boto3.
        bucket: Bucket destino.
        key: Clave destino.
        data: Diccionario a cargar.
    """
    body = json.dumps(data, ensure_ascii=False)  # compact, no indent → smaller file
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body.encode("utf-8"),
        ContentType="application/json",
    )
    logger.info(
        "Uploaded JSON to S3",
        extra={"bucket": bucket, "key": key, "bytes": len(body)},
    )


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------


def fetch_open_meteo(zone: str, lat: float, lon: float, year: int) -> dict:
    """Llama a la API de archivo de Open-Meteo para una combinación (zona, año).

    Nota sobre latitud/longitud devueltas: Open-Meteo ajusta (snap) coordenadas
    al punto de grilla ECMWF más cercano (~9km resolución). La respuesta incluye
    el punto de grilla real usado, que puede diferir ligeramente de lat/lon
    solicitados. Ambos se preservan en el sobre Bronze para trazabilidad.

    Args:
        zone: Identificador de zona, usado solo para contexto de logging.
        lat: Latitud del centroide.
        lon: Longitud del centroide.
        year: Año a obtener (año calendario completo 1 ene – 31 dic).

    Returns:
        Diccionario de respuesta cruda de API (claves: latitude, longitude, hourly, …).

    Raises:
        requests.HTTPError: Si la API retorna código de estado no-2xx.
        requests.Timeout: Si la API no responde en 60 segundos.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": f"{year}-01-01",
        "end_date": f"{year}-12-31",
        "hourly": ",".join(HOURLY_VARIABLES),
        "timezone": "America/Mexico_City",
    }
    resp = requests.get(OPEN_METEO_ARCHIVE_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()
    logger.info(
        "Open-Meteo response received",
        extra={"zone": zone, "year": year, "http_status": resp.status_code},
    )
    return resp.json()


def wrap_with_metadata(payload: dict, zone: str, year: int, source_url: str) -> dict:
    """Añade un sobre de metadatos Bronze a la respuesta cruda de la API.

    Principio Bronze: nunca modificar datos de fuente; solo prepend _metadata.
    El ETL de Silver retira _metadata antes de construir silver.meteo_horario.

    Args:
        payload: Diccionario crudo de Open-Meteo (sin modificaciones).
        zone: Identificador de zona para esta solicitud.
        year: Año para esta solicitud.
        source_url: URL base utilizada (para reproducibilidad).

    Returns:
        Nuevo diccionario con _metadata como primer clave, datos de fuente después.
    """
    return {
        "_metadata": {
            "_ingested_at": datetime.now(timezone.utc).isoformat(),
            "_source_url": source_url,
            "_zone": zone,
            "_year": year,
            "_hourly_variables": HOURLY_VARIABLES,
            # Actual grid point snapped by Open-Meteo (may differ from centroid)
            "_actual_latitude": payload.get("latitude"),
            "_actual_longitude": payload.get("longitude"),
        },
        **payload,
    }


# ---------------------------------------------------------------------------
# Core ingest function
# ---------------------------------------------------------------------------


def ingest_zone_year(
    s3_client: Any,
    zone: str,
    lat: float,
    lon: float,
    year: int,
    bucket: str,
    dry_run: bool = False,
) -> str:
    """Ingesta una combinación (zona, año) de principio a fin.

    Flujo:
        1. Construye la clave S3 destino.
        2. Si la clave existe → retorna "skipped" (idempotencia).
        3. Llama a la API de Open-Meteo.
        4. Envuelve respuesta con sobre de metadatos.
        5. Carga a S3 (u omite si dry_run).

    Args:
        s3_client: Cliente S3 de Boto3.
        zone: Identificador de zona.
        lat: Latitud del centroide.
        lon: Longitud del centroide.
        year: Año a ingestar.
        bucket: Bucket S3 destino.
        dry_run: Si es True, obtiene de API pero omite la carga a S3.

    Returns:
        Uno de: "skipped", "uploaded", "dry_run".
    """
    key = build_s3_key(zone, year)

    if not dry_run and s3_key_exists(s3_client, bucket, key):
        logger.info(
            "Key already exists — skipping",
            extra={"zone": zone, "year": year, "key": key},
        )
        return "skipped"

    payload = fetch_open_meteo(zone, lat, lon, year)
    wrapped = wrap_with_metadata(payload, zone, year, OPEN_METEO_ARCHIVE_URL)
    hourly_rows = len(payload.get("hourly", {}).get("time", []))

    if dry_run:
        logger.info(
            "Dry run — would upload",
            extra={"key": key, "hourly_rows": hourly_rows},
        )
        return "dry_run"

    upload_json_to_s3(s3_client, bucket, key, wrapped)
    logger.info(
        "Zone-year ingested",
        extra={"zone": zone, "year": year, "hourly_rows": hourly_rows},
    )
    return "uploaded"


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def main(
    zones: list[str] | None = None,
    years: list[int] | None = None,
    dry_run: bool = False,
) -> None:
    """Orquesta la ingesta Bronze para todas las combinaciones (zona, año) solicitadas.

    Args:
        zones: Subconjunto de zonas a ingestar. Por defecto todas las 5 ZONE_CENTROIDS.
        years: Lista de años a ingestar. Por defecto DEFAULT_YEARS.
        dry_run: Si es True, llama a la API pero no escribe en S3.
    """
    setup_logging()

    zones = zones or list(ZONE_CENTROIDS.keys())
    years = years or DEFAULT_YEARS
    total = len(zones) * len(years)

    logger.info(
        "Bronze Open-Meteo ingestion started",
        extra={"zones": zones, "years": years, "total_requests": total, "dry_run": dry_run},
    )

    s3_client = boto3.client("s3")
    stats: dict[str, int] = {"skipped": 0, "uploaded": 0, "dry_run": 0, "failed": 0}

    for zone in zones:
        lat, lon = ZONE_CENTROIDS[zone]
        for year in years:
            try:
                status = ingest_zone_year(
                    s3_client, zone, lat, lon, year, S3_BUCKET, dry_run=dry_run
                )
                stats[status] += 1
            except requests.HTTPError as exc:
                logger.error(
                    "HTTP error — zone/year skipped",
                    extra={"zone": zone, "year": year, "http_status": exc.response.status_code},
                )
                stats["failed"] += 1
            except requests.Timeout:
                logger.error(
                    "Timeout — zone/year skipped",
                    extra={"zone": zone, "year": year},
                )
                stats["failed"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Unexpected error — zone/year skipped",
                    extra={"zone": zone, "year": year, "error": str(exc)},
                )
                stats["failed"] += 1
            finally:
                time.sleep(SLEEP_BETWEEN_REQUESTS)

    logger.info("Bronze Open-Meteo ingestion finished", extra={"stats": stats})

    if stats["failed"] > 0:
        raise SystemExit(
            f"{stats['failed']} zone-year(s) failed. "
            "Check logs, fix the issue, and re-run — already uploaded files will be skipped."
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bronze ingestion: Open-Meteo historical weather data for ZMVM zones."
    )
    parser.add_argument(
        "--zones",
        nargs="+",
        choices=list(ZONE_CENTROIDS.keys()),
        help="Zones to ingest (default: all 5 zones).",
    )
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        help="Years to ingest, e.g. --years 2023 2024 (default: 2020–2024).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Call the API but do not write to S3. Useful for smoke-testing connectivity.",
    )
    return parser


if __name__ == "__main__":
    args = _build_arg_parser().parse_args()
    main(zones=args.zones, years=args.years, dry_run=args.dry_run)
