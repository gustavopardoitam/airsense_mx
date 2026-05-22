"""Unit tests for etl/bronze_open_meteo.py.

Tests only pure functions and behavior with mocked I/O.
No real API calls, no real S3 writes.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from etl.bronze_open_meteo import (
    HOURLY_VARIABLES,
    ZONE_CENTROIDS,
    build_s3_key,
    ingest_zone_year,
    s3_key_exists,
    wrap_with_metadata,
)


# ---------------------------------------------------------------------------
# build_s3_key — pure function, no mocks needed
# ---------------------------------------------------------------------------


class TestBuildS3Key:
    def test_returns_expected_path(self) -> None:
        key = build_s3_key("NO", 2022)
        assert key == "bronze/open_meteo/zone=NO/year=2022/meteo_NO_2022.json"

    def test_all_zones_produce_distinct_keys(self) -> None:
        keys = [build_s3_key(z, 2020) for z in ZONE_CENTROIDS]
        assert len(set(keys)) == len(ZONE_CENTROIDS), "Every zone must produce a unique key"

    def test_all_years_produce_distinct_keys(self) -> None:
        keys = [build_s3_key("CE", y) for y in range(2020, 2025)]
        assert len(set(keys)) == 5


# ---------------------------------------------------------------------------
# wrap_with_metadata — pure function, no mocks needed
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_payload() -> dict:
    """Minimal Open-Meteo-like response."""
    return {
        "latitude": 19.391,
        "longitude": -99.11,
        "timezone": "America/Mexico_City",
        "hourly_units": {"time": "iso8601", "temperature_2m": "°C"},
        "hourly": {
            "time": ["2022-01-01T00:00", "2022-01-01T01:00"],
            "temperature_2m": [12.5, 11.8],
        },
    }


class TestWrapWithMetadata:
    def test_metadata_key_present(self, sample_payload: dict) -> None:
        result = wrap_with_metadata(sample_payload, "CE", 2022, "https://example.com")
        assert "_metadata" in result

    def test_source_data_preserved(self, sample_payload: dict) -> None:
        result = wrap_with_metadata(sample_payload, "CE", 2022, "https://example.com")
        assert result["hourly"] == sample_payload["hourly"]
        assert result["latitude"] == sample_payload["latitude"]

    def test_metadata_contains_expected_fields(self, sample_payload: dict) -> None:
        result = wrap_with_metadata(sample_payload, "NO", 2021, "https://api.test")
        meta = result["_metadata"]
        assert meta["_zone"] == "NO"
        assert meta["_year"] == 2021
        assert meta["_source_url"] == "https://api.test"
        assert meta["_hourly_variables"] == HOURLY_VARIABLES
        assert "_ingested_at" in meta

    def test_actual_grid_point_stored_in_metadata(self, sample_payload: dict) -> None:
        """Open-Meteo may snap to a slightly different lat/lon than requested.
        The actual grid point must be stored in metadata for traceability.
        """
        result = wrap_with_metadata(sample_payload, "CE", 2022, "https://api.test")
        assert result["_metadata"]["_actual_latitude"] == 19.391
        assert result["_metadata"]["_actual_longitude"] == -99.11


# ---------------------------------------------------------------------------
# s3_key_exists — requires mocked boto3 client
# ---------------------------------------------------------------------------


class TestS3KeyExists:
    def test_returns_true_when_object_exists(self) -> None:
        s3 = MagicMock()
        s3.head_object.return_value = {}  # head_object succeeds → object exists
        assert s3_key_exists(s3, "airsense-mx", "bronze/test.json") is True

    def test_returns_false_on_404(self) -> None:
        s3 = MagicMock()
        error = ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        s3.head_object.side_effect = error
        assert s3_key_exists(s3, "airsense-mx", "bronze/test.json") is False

    def test_reraises_non_404_errors(self) -> None:
        """403 (permission denied) should propagate — we must not silently skip."""
        s3 = MagicMock()
        error = ClientError({"Error": {"Code": "403", "Message": "Forbidden"}}, "HeadObject")
        s3.head_object.side_effect = error
        with pytest.raises(ClientError):
            s3_key_exists(s3, "airsense-mx", "bronze/test.json")


# ---------------------------------------------------------------------------
# ingest_zone_year — integration of the above with mocks
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_api_response() -> dict:
    """Minimal realistic Open-Meteo response structure."""
    return {
        "latitude": 19.391,
        "longitude": -99.11,
        "timezone": "America/Mexico_City",
        "hourly_units": {"time": "iso8601"},
        "hourly": {"time": ["2020-01-01T00:00"] * 8760},  # simulates a full year
    }


class TestIngestZoneYear:
    def test_returns_skipped_when_key_exists(self) -> None:
        s3 = MagicMock()
        s3.head_object.return_value = {}  # key exists
        result = ingest_zone_year(s3, "CE", 19.391, -99.11, 2020, "airsense-mx")
        assert result == "skipped"

    def test_returns_dry_run_without_uploading(self, fake_api_response: dict) -> None:
        s3 = MagicMock()
        with patch("etl.bronze_open_meteo.fetch_open_meteo", return_value=fake_api_response):
            result = ingest_zone_year(
                s3, "NO", 19.54, -99.23, 2020, "airsense-mx", dry_run=True
            )
        assert result == "dry_run"
        s3.put_object.assert_not_called()  # must not write to S3 in dry_run

    def test_uploads_when_key_missing(self, fake_api_response: dict) -> None:
        s3 = MagicMock()
        error = ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        s3.head_object.side_effect = error  # key does not exist

        with patch("etl.bronze_open_meteo.fetch_open_meteo", return_value=fake_api_response):
            result = ingest_zone_year(s3, "NE", 19.48, -99.02, 2021, "airsense-mx")

        assert result == "uploaded"
        s3.put_object.assert_called_once()

    def test_upload_key_matches_build_s3_key(self, fake_api_response: dict) -> None:
        """The key used in put_object must match what build_s3_key returns."""
        s3 = MagicMock()
        error = ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        s3.head_object.side_effect = error

        with patch("etl.bronze_open_meteo.fetch_open_meteo", return_value=fake_api_response):
            ingest_zone_year(s3, "SO", 19.31, -99.18, 2022, "airsense-mx")

        call_kwargs = s3.put_object.call_args.kwargs
        assert call_kwargs["Key"] == "bronze/open_meteo/zone=SO/year=2022/meteo_SO_2022.json"
        assert call_kwargs["Bucket"] == "airsense-mx"

    def test_uploaded_body_contains_metadata_key(self, fake_api_response: dict) -> None:
        """JSON written to S3 must include the _metadata envelope."""
        import json

        s3 = MagicMock()
        error = ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        s3.head_object.side_effect = error

        with patch("etl.bronze_open_meteo.fetch_open_meteo", return_value=fake_api_response):
            ingest_zone_year(s3, "SE", 19.33, -98.99, 2020, "airsense-mx")

        body_bytes = s3.put_object.call_args.kwargs["Body"]
        stored = json.loads(body_bytes.decode("utf-8"))
        assert "_metadata" in stored
        assert stored["_metadata"]["_zone"] == "SE"
        assert stored["_metadata"]["_year"] == 2020
