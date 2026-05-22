"""Tests unitarios para etl/openmeteo_bronze.py.

Todos los tests usan mocks. No realizan llamadas reales a la API ni I/O en disco
salvo en directorios temporales gestionados por pytest (tmp_path).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from etl.openmeteo_bronze import (
    build_openmeteo_url,
    build_output_path,
    download_openmeteo_year,
    load_active_stations,
    run_openmeteo_bronze_ingestion,
    save_raw_json,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def stations_csv(tmp_path: Path) -> Path:
    """CSV mínimo con 3 estaciones: 2 activas, 1 inactiva."""
    content = (
        "station_id,station_name,station_name_full,zone,zone_full,municipality,"
        "state,latitude,longitude,altitude_masl,pollutants_measured,is_active,notes\n"
        "BJU,Benito Juárez,Benito Juárez — CDMX,CE,Centro,Benito Juárez,"
        "Ciudad de México,19.3705,-99.1596,2249,O3;NO2,TRUE,\n"
        "XAL,Xalostoc,Xalostoc — EdoMex,NE,Noreste,Ecatepec,"
        "Estado de México,19.5300,-99.0700,2230,O3;PM10,TRUE,\n"
        "TPN,Tlalpan,Tlalpan — CDMX,SO,Suroeste,Tlalpan,"
        "Ciudad de México,19.2722,-99.2077,2548,O3,FALSE,Cerrada\n"
    )
    path = tmp_path / "dim_estaciones.csv"
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def sample_api_response() -> dict:
    """Respuesta mínima simulada de Open-Meteo."""
    return {
        "latitude": 19.375,
        "longitude": -99.125,
        "timezone": "America/Mexico_City",
        "hourly": {
            "time": ["2023-01-01T00:00", "2023-01-01T01:00"],
            "temperature_2m": [12.5, 11.8],
            "wind_speed_10m": [3.2, 2.9],
        },
    }


# ── TestLoadActiveStations ────────────────────────────────────────────────────


class TestLoadActiveStations:
    def test_returns_only_active(self, stations_csv: Path) -> None:
        df = load_active_stations(stations_csv)
        assert len(df) == 2
        assert set(df["station_id"]) == {"BJU", "XAL"}

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_active_stations(tmp_path / "no_existe.csv")

    def test_missing_column_raises(self, tmp_path: Path) -> None:
        bad_csv = tmp_path / "bad.csv"
        bad_csv.write_text("station_id,latitude\nBJU,19.37\n")
        with pytest.raises(ValueError, match="Columnas faltantes"):
            load_active_stations(bad_csv)

    def test_required_columns_present(self, stations_csv: Path) -> None:
        df = load_active_stations(stations_csv)
        for col in ("station_id", "latitude", "longitude", "zone"):
            assert col in df.columns


# ── TestBuildOpenMeteoUrl ─────────────────────────────────────────────────────


class TestBuildOpenMeteoUrl:
    def test_returns_correct_base_url(self) -> None:
        url, _ = build_openmeteo_url(19.37, -99.15, 2022)
        assert "archive-api.open-meteo.com" in url

    def test_params_include_start_and_end_date(self) -> None:
        _, params = build_openmeteo_url(19.37, -99.15, 2022)
        assert params["start_date"] == "2022-01-01"
        assert params["end_date"] == "2022-12-31"

    def test_current_year_end_date_is_today(self) -> None:
        from datetime import date

        year = date.today().year
        _, params = build_openmeteo_url(19.37, -99.15, year)
        assert params["end_date"] == date.today().isoformat()

    def test_timezone_is_mexico_city(self) -> None:
        _, params = build_openmeteo_url(19.37, -99.15, 2022)
        assert params["timezone"] == "America/Mexico_City"

    def test_hourly_variables_included(self) -> None:
        _, params = build_openmeteo_url(19.37, -99.15, 2022)
        assert "temperature_2m" in params["hourly"]
        assert "wind_speed_10m" in params["hourly"]


# ── TestBuildOutputPath ───────────────────────────────────────────────────────


class TestBuildOutputPath:
    def test_path_follows_partition_convention(self) -> None:
        path = build_output_path(Path("data/raw/openmeteo"), "BJU", 2023)
        assert path == Path(
            "data/raw/openmeteo/station_id=BJU/year=2023/openmeteo_BJU_2023.json"
        )

    def test_different_stations_produce_different_paths(self) -> None:
        p1 = build_output_path(Path("out"), "BJU", 2023)
        p2 = build_output_path(Path("out"), "XAL", 2023)
        assert p1 != p2

    def test_different_years_produce_different_paths(self) -> None:
        p1 = build_output_path(Path("out"), "BJU", 2022)
        p2 = build_output_path(Path("out"), "BJU", 2023)
        assert p1 != p2


# ── TestDownloadOpenMeteoYear ─────────────────────────────────────────────────


class TestDownloadOpenMeteoYear:
    def test_returns_metadata_key(self, sample_api_response: dict) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_api_response
        mock_resp.raise_for_status.return_value = None
        mock_resp.url = "https://archive-api.open-meteo.com/v1/archive?latitude=19.37"

        with patch("etl.openmeteo_bronze.requests.get", return_value=mock_resp):
            result = download_openmeteo_year("BJU", 19.37, -99.15, 2023)

        assert "_metadata" in result

    def test_metadata_contains_station_id_and_year(
        self, sample_api_response: dict
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_api_response
        mock_resp.raise_for_status.return_value = None
        mock_resp.url = "https://example.com"

        with patch("etl.openmeteo_bronze.requests.get", return_value=mock_resp):
            result = download_openmeteo_year("BJU", 19.37, -99.15, 2023)

        assert result["_metadata"]["station_id"] == "BJU"
        assert result["_metadata"]["year"] == 2023

    def test_metadata_contains_requested_coordinates_from_csv(
        self, sample_api_response: dict
    ) -> None:
        """Las coordenadas del CSV deben quedar en metadata como latitude_requested."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_api_response
        mock_resp.raise_for_status.return_value = None
        mock_resp.url = "https://example.com"

        with patch("etl.openmeteo_bronze.requests.get", return_value=mock_resp):
            result = download_openmeteo_year("BJU", 19.3705, -99.1596, 2023)

        assert result["_metadata"]["latitude_requested"] == 19.3705
        assert result["_metadata"]["longitude_requested"] == -99.1596

    def test_metadata_contains_actual_grid_coordinates(
        self, sample_api_response: dict
    ) -> None:
        """Las coordenadas reales del grid ECMWF deben quedar en latitude_actual."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = (
            sample_api_response  # latitude=19.375, longitude=-99.125
        )
        mock_resp.raise_for_status.return_value = None
        mock_resp.url = "https://example.com"

        with patch("etl.openmeteo_bronze.requests.get", return_value=mock_resp):
            result = download_openmeteo_year("BJU", 19.3705, -99.1596, 2023)

        assert result["_metadata"]["latitude_actual"] == sample_api_response["latitude"]
        assert (
            result["_metadata"]["longitude_actual"] == sample_api_response["longitude"]
        )

    def test_original_payload_preserved(self, sample_api_response: dict) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_api_response
        mock_resp.raise_for_status.return_value = None
        mock_resp.url = "https://example.com"

        with patch("etl.openmeteo_bronze.requests.get", return_value=mock_resp):
            result = download_openmeteo_year("BJU", 19.37, -99.15, 2023)

        assert result["latitude"] == sample_api_response["latitude"]
        assert "hourly" in result

    def test_raises_on_4xx_without_retry(self) -> None:
        mock_resp = MagicMock()
        http_error = requests.HTTPError(response=MagicMock(status_code=404))
        mock_resp.raise_for_status.side_effect = http_error

        with patch("etl.openmeteo_bronze.requests.get", return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                download_openmeteo_year("BJU", 19.37, -99.15, 2023)

    def test_retries_on_connection_error(self, sample_api_response: dict) -> None:
        mock_ok = MagicMock()
        mock_ok.json.return_value = sample_api_response
        mock_ok.raise_for_status.return_value = None
        mock_ok.url = "https://example.com"

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise requests.ConnectionError("timeout simulado")
            return mock_ok

        with patch("etl.openmeteo_bronze.requests.get", side_effect=side_effect):
            with patch("etl.openmeteo_bronze.time.sleep"):
                result = download_openmeteo_year("BJU", 19.37, -99.15, 2023)

        assert "_metadata" in result
        assert call_count == 2


# ── TestSaveRawJson ───────────────────────────────────────────────────────────


class TestSaveRawJson:
    def test_creates_file(self, tmp_path: Path) -> None:
        path = tmp_path / "station_id=BJU" / "year=2023" / "openmeteo_BJU_2023.json"
        save_raw_json(path, {"key": "value"})
        assert path.exists()

    def test_content_is_valid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "out.json"
        data = {"latitude": 19.37, "hourly": {"time": []}}
        save_raw_json(path, data)
        loaded = json.loads(path.read_text())
        assert loaded == data

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        path = tmp_path / "a" / "b" / "c" / "file.json"
        save_raw_json(path, {})
        assert path.parent.exists()


# ── TestRunOpenMeteoBronzeIngestion ───────────────────────────────────────────


class TestRunOpenMeteoBronzeIngestion:
    def test_skips_existing_files(self, stations_csv: Path, tmp_path: Path) -> None:
        """Si el archivo ya existe, debe contar como 'skipped'."""
        # Pre-crear archivo para BJU 2020
        existing = build_output_path(tmp_path, "BJU", 2020)
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_text("{}", encoding="utf-8")

        with patch("etl.openmeteo_bronze.download_openmeteo_year") as mock_dl:
            mock_dl.return_value = {"_metadata": {}}
            with patch("etl.openmeteo_bronze.save_raw_json"):
                with patch("etl.openmeteo_bronze.time.sleep"):
                    stats = run_openmeteo_bronze_ingestion(
                        stations_path=stations_csv,
                        output_dir=tmp_path,
                        start_year=2020,
                        end_year=2020,
                        overwrite=False,
                    )

        assert stats["skipped"] >= 1

    def test_overwrite_flag_redownloads(
        self, stations_csv: Path, tmp_path: Path
    ) -> None:
        """Con overwrite=True, archivos existentes deben descargarse de nuevo."""
        existing = build_output_path(tmp_path, "BJU", 2020)
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_text("{}", encoding="utf-8")

        with patch("etl.openmeteo_bronze.download_openmeteo_year") as mock_dl:
            mock_dl.return_value = {"latitude": 19.37, "_metadata": {}}
            with patch("etl.openmeteo_bronze.save_raw_json"):
                with patch("etl.openmeteo_bronze.time.sleep"):
                    stats = run_openmeteo_bronze_ingestion(
                        stations_path=stations_csv,
                        output_dir=tmp_path,
                        start_year=2020,
                        end_year=2020,
                        overwrite=True,
                    )

        assert stats["downloaded"] == 2  # 2 estaciones activas
        assert stats["skipped"] == 0

    def test_failed_station_does_not_abort(
        self, stations_csv: Path, tmp_path: Path
    ) -> None:
        """Un error en una estación no debe abortar el resto."""
        call_count = 0

        def failing_download(station_id, lat, lon, year):
            nonlocal call_count
            call_count += 1
            if station_id == "BJU":
                raise requests.ConnectionError("simulado")
            return {"latitude": lat, "_metadata": {}}

        with patch(
            "etl.openmeteo_bronze.download_openmeteo_year", side_effect=failing_download
        ):
            with patch("etl.openmeteo_bronze.save_raw_json"):
                with patch("etl.openmeteo_bronze.time.sleep"):
                    stats = run_openmeteo_bronze_ingestion(
                        stations_path=stations_csv,
                        output_dir=tmp_path,
                        start_year=2020,
                        end_year=2020,
                    )

        assert stats["failed"] == 1
        assert stats["downloaded"] == 1

    def test_returns_stats_dict_with_expected_keys(
        self, stations_csv: Path, tmp_path: Path
    ) -> None:
        with patch("etl.openmeteo_bronze.download_openmeteo_year") as mock_dl:
            mock_dl.return_value = {"latitude": 19.37, "_metadata": {}}
            with patch("etl.openmeteo_bronze.save_raw_json"):
                with patch("etl.openmeteo_bronze.time.sleep"):
                    stats = run_openmeteo_bronze_ingestion(
                        stations_path=stations_csv,
                        output_dir=tmp_path,
                        start_year=2020,
                        end_year=2020,
                    )

        assert set(stats.keys()) == {"downloaded", "skipped", "failed"}
