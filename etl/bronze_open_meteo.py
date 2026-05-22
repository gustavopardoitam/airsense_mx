"""Bronze layer: ingestion of Open-Meteo historical weather data.

Downloads hourly meteorological data for 5 zone centroids in the ZMVM
and stores raw JSON responses in S3 Bronze.

Design decisions:
- One request per (zone, year) → 25 API calls total for 5 zones × 5 years.
  Rationale: Open-Meteo uses a ~9km ECMWF grid. Stations within the same
  zone receive virtually identical values, so per-zone centroids are enough.
- Idempotent: checks S3 key existence via head_object before every API call.
  Safe to run multiple times without overwriting valid data.
- Raw JSON stored as-is (Bronze principle: zero transformation here).
  A metadata envelope (_metadata key) is added without touching the API body.
- Timezone: America/Mexico_City. Pre-Nov-2022 data includes DST (UTC-5 summer).
  Silver ETL is responsible for normalizing to consistent UTC-6.

S3 path:
    s3://airsense-mx/bronze/open_meteo/zone={zone}/year={year}/
        meteo_{zone}_{year}.json

Usage:
    python -m etl.bronze_open_meteo                   # all zones, 2020-2024
    python -m etl.bronze_open_meteo --years 2023 2024
    python -m etl.bronze_open_meteo --zones NO NE
    python -m etl.bronze_open_meteo --dry-run         # fetch but skip S3 write
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
    """Returns the S3 key for a given zone and year.

    Args:
        zone: Zone identifier (CE/NO/NE/SO/SE).
        year: Calendar year (e.g. 2020).

    Returns:
        Full S3 key without bucket prefix.

    Example:
        >>> build_s3_key("NO", 2022)
        'bronze/open_meteo/zone=NO/year=2022/meteo_NO_2022.json'
    """
    return f"bronze/open_meteo/zone={zone}/year={year}/meteo_{zone}_{year}.json"


def s3_key_exists(s3_client: Any, bucket: str, key: str) -> bool:
    """Checks whether an S3 object already exists (idempotency gate).

    Uses head_object which is cheaper than get_object and does not
    download the body.

    Args:
        s3_client: Boto3 S3 client.
        bucket: S3 bucket name.
        key: S3 object key.

    Returns:
        True if the object exists, False if it returns 404.

    Raises:
        ClientError: For any error other than 404 (e.g. permission denied).
    """
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "404":
            return False
        raise  # 403, 5xx, etc. must propagate — we shouldn't silently skip


def upload_json_to_s3(s3_client: Any, bucket: str, key: str, data: dict) -> None:
    """Serializes a dict to compact JSON and uploads it to S3.

    Args:
        s3_client: Boto3 S3 client.
        bucket: Target bucket.
        key: Target key.
        data: Dict to upload.
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
    """Calls Open-Meteo archive API for one (zone, year) combination.

    Note on the returned latitude/longitude: Open-Meteo snaps coordinates to
    the nearest ECMWF grid point (~9km resolution). The response includes the
    actual grid point used, which may differ slightly from lat/lon requested.
    Both are preserved in the Bronze envelope for traceability.

    Args:
        zone: Zone identifier, used only for logging context.
        lat: Centroid latitude.
        lon: Centroid longitude.
        year: Year to fetch (full calendar year Jan 1 – Dec 31).

    Returns:
        Raw API response dict (keys: latitude, longitude, hourly, hourly_units, …).

    Raises:
        requests.HTTPError: If the API returns a non-2xx status code.
        requests.Timeout: If the API does not respond in 60 seconds.
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
    """Adds a Bronze metadata envelope to the raw API response.

    Bronze principle: never modify source data; only prepend _metadata.
    Silver ETL strips _metadata before building silver.meteo_horario.

    Args:
        payload: Raw dict from Open-Meteo (unmodified).
        zone: Zone identifier for this request.
        year: Year for this request.
        source_url: Base URL used (for reproducibility).

    Returns:
        New dict with _metadata as the first key, source data spread after it.
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
    """Ingests one (zone, year) combination end-to-end.

    Workflow:
        1. Build the target S3 key.
        2. If key exists → return "skipped" (idempotency).
        3. Call Open-Meteo API.
        4. Wrap response with metadata envelope.
        5. Upload to S3 (or skip if dry_run).

    Args:
        s3_client: Boto3 S3 client.
        zone: Zone identifier.
        lat: Centroid latitude.
        lon: Centroid longitude.
        year: Year to ingest.
        bucket: Target S3 bucket.
        dry_run: If True, fetches from API but skips the S3 upload.

    Returns:
        One of: "skipped", "uploaded", "dry_run".
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
    """Orchestrates Bronze ingestion for all requested (zone, year) combinations.

    Args:
        zones: Subset of zones to ingest. Defaults to all 5 ZONE_CENTROIDS.
        years: List of years to ingest. Defaults to DEFAULT_YEARS.
        dry_run: If True, calls the API but does not write to S3.
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
