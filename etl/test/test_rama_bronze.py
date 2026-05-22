"""Tests unitarios para etl/rama_bronze.py.

Cobertura completa con mocks totales — sin acceso a red ni sistema de
archivos real (excepto tmp_path de pytest para pruebas de I/O).
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from etl.rama_bronze import (
    RAMA_BASE_URL,
    build_output_path,
    build_rama_download_url,
    download_rama_excel,
    extract_all_from_zip,
    looks_like_excel,
    run_rama_bronze_ingestion,
    save_excel_file,
    year_to_simat_value,
)

# ---------------------------------------------------------------------------
# Constantes de prueba
# ---------------------------------------------------------------------------

XLS_CONTENT = b"\xd0\xcf\x11\xe0" + b"\x00" * 100  # firma XLS clásico válida
XLSX_CONTENT = b"PK\x03\x04" + b"\x00" * 100  # firma XLSX (ZIP) válida
HTML_CONTENT = b"<html><body>Error del portal</body></html>"
EMPTY_CONTENT = b""
RANDOM_CONTENT = b"\x00\x01\x02\x03" * 50

# HTML con JS redirect que incluye URL del ZIP (respuesta real del portal)
HTML_WITH_ZIP_URL = (
    '<html><script>setTimeout("location.href='
    "'https://aire.cdmx.gob.mx/descargas/Opendata/Bases_publicas/RAMA/21RAMA.zip'"
    '",1000);</script></html>'
)


# ZIP de prueba con XLS de O3 para año 2021
def _make_test_zip(year: int, pollutant: str, content: bytes = XLS_CONTENT) -> bytes:
    """Crea un ZIP en memoria con un XLS de prueba para el contaminante dado."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{year}{pollutant}.xls", content)
    return buf.getvalue()


ZIP_2021_O3 = _make_test_zip(2021, "O3")
ZIP_2021_MULTI = None  # Se construye abajo para múltiples contaminantes


def _make_multi_zip(year: int, pollutants: list[str]) -> bytes:
    """Crea un ZIP en memoria con XLS de prueba para múltiples contaminantes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in pollutants:
            zf.writestr(f"{year}{p}.xls", XLS_CONTENT)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# TestYearToSimatValue
# ---------------------------------------------------------------------------


class TestYearToSimatValue:
    """Pruebas para year_to_simat_value."""

    def test_2021_returns_21(self) -> None:
        """Año 2021 debe retornar '21'."""
        assert year_to_simat_value(2021) == "21"

    def test_2024_returns_24(self) -> None:
        """Año 2024 debe retornar '24'."""
        assert year_to_simat_value(2024) == "24"

    def test_2026_returns_26(self) -> None:
        """Año 2026 debe retornar '26'."""
        assert year_to_simat_value(2026) == "26"


# ---------------------------------------------------------------------------
# TestBuildRamaDownloadUrl
# ---------------------------------------------------------------------------


class TestBuildRamaDownloadUrl:
    """Pruebas para build_rama_download_url."""

    def test_returns_official_cdmx_domain(self) -> None:
        """Debe retornar URL del dominio oficial aire.cdmx.gob.mx."""
        url = build_rama_download_url()
        assert "aire.cdmx.gob.mx" in url

    def test_contains_aKBh_parameter(self) -> None:
        """Debe contener el parámetro opc=aKBh que identifica la sección RAMA."""
        assert "aKBh" in build_rama_download_url()

    def test_matches_base_url_constant(self) -> None:
        """El valor debe coincidir con la constante RAMA_BASE_URL."""
        assert build_rama_download_url() == RAMA_BASE_URL


# ---------------------------------------------------------------------------
# TestBuildOutputPath
# ---------------------------------------------------------------------------


class TestBuildOutputPath:
    """Pruebas para build_output_path."""

    def test_correct_year_partition_structure(self, tmp_path: Path) -> None:
        """Debe generar ruta con partición por año."""
        path = build_output_path(tmp_path, "2021O3.xls", 2021)
        assert "year=2021" in str(path)

    def test_filename_preserved_in_path(self, tmp_path: Path) -> None:
        """El nombre de archivo del ZIP debe conservarse tal cual."""
        path = build_output_path(tmp_path, "2021PM10.xls", 2021)
        assert path.name == "2021PM10.xls"

    def test_different_filenames_produce_different_paths(self, tmp_path: Path) -> None:
        """Archivos distintos deben generar rutas distintas."""
        assert build_output_path(tmp_path, "2021O3.xls", 2021) != build_output_path(
            tmp_path, "2021PM25.xls", 2021
        )

    def test_different_years_produce_different_paths(self, tmp_path: Path) -> None:
        """Años distintos deben generar rutas distintas."""
        assert build_output_path(tmp_path, "2021O3.xls", 2021) != build_output_path(
            tmp_path, "2022O3.xls", 2022
        )


# ---------------------------------------------------------------------------
# TestLooksLikeExcel
# ---------------------------------------------------------------------------


class TestLooksLikeExcel:
    """Pruebas para looks_like_excel."""

    def test_xls_magic_bytes_returns_true(self) -> None:
        """Firma XLS clásica (D0 CF 11 E0) debe retornar True."""
        assert looks_like_excel(XLS_CONTENT) is True

    def test_xlsx_magic_bytes_returns_true(self) -> None:
        """Firma XLSX/ZIP (PK 03 04) debe retornar True."""
        assert looks_like_excel(XLSX_CONTENT) is True

    def test_html_content_returns_false(self) -> None:
        """Respuesta HTML del portal (error) debe retornar False."""
        assert looks_like_excel(HTML_CONTENT) is False

    def test_empty_content_returns_false(self) -> None:
        """Contenido vacío debe retornar False."""
        assert looks_like_excel(EMPTY_CONTENT) is False

    def test_random_binary_returns_false(self) -> None:
        """Binario arbitrario sin firma Excel válida debe retornar False."""
        assert looks_like_excel(RANDOM_CONTENT) is False


# ---------------------------------------------------------------------------
# TestSaveExcelFile
# ---------------------------------------------------------------------------


class TestSaveExcelFile:
    """Pruebas para save_excel_file."""

    def test_creates_file_at_path(self, tmp_path: Path) -> None:
        """Debe crear el archivo en la ruta especificada."""
        path = tmp_path / "output.xls"
        save_excel_file(path, XLS_CONTENT)
        assert path.exists()

    def test_content_matches_input(self, tmp_path: Path) -> None:
        """El contenido guardado debe ser idéntico al original."""
        path = tmp_path / "output.xls"
        save_excel_file(path, XLS_CONTENT)
        assert path.read_bytes() == XLS_CONTENT

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Debe crear directorios intermedios si no existen."""
        path = tmp_path / "contaminante=O3" / "year=2021" / "rama_O3_2021.xls"
        save_excel_file(path, XLS_CONTENT)
        assert path.exists()


# ---------------------------------------------------------------------------
# TestDownloadRamaExcel
# ---------------------------------------------------------------------------


class TestDownloadRamaExcel:
    """Pruebas para download_rama_excel con mocks totales de red."""

    def _mock_post_html(self, html_text: str) -> MagicMock:
        """Crea mock de respuesta POST con HTML que contiene JS redirect."""
        resp = MagicMock()
        resp.text = html_text
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        return resp

    def _mock_get_zip(self, zip_bytes: bytes) -> MagicMock:
        """Crea mock de respuesta GET con contenido ZIP."""
        resp = MagicMock()
        resp.content = zip_bytes
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        return resp

    def _mock_http_error(self, status_code: int = 404) -> MagicMock:
        """Crea mock de respuesta HTTP con error."""
        resp = MagicMock()
        resp.content = b""
        resp.status_code = status_code
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
        return resp

    def test_returns_zip_bytes_on_success(self) -> None:
        """Debe retornar bytes del ZIP cuando el portal responde correctamente."""
        session = MagicMock()
        session.post.return_value = self._mock_post_html(HTML_WITH_ZIP_URL)
        session.get.return_value = self._mock_get_zip(ZIP_2021_O3)

        result = download_rama_excel(session, 2021)

        assert result == ZIP_2021_O3

    def test_posts_correct_seluniano_value(self) -> None:
        """Debe enviar seluniano con valor de dos dígitos correcto."""
        session = MagicMock()
        session.post.return_value = self._mock_post_html(HTML_WITH_ZIP_URL)
        session.get.return_value = self._mock_get_zip(ZIP_2021_O3)

        download_rama_excel(session, 2023)

        assert session.post.call_args.kwargs["data"]["seluniano"] == "23"

    def test_posts_correct_submit_button_value(self) -> None:
        """Debe enviar unibaja='Descargar archivo' para activar la descarga."""
        session = MagicMock()
        session.post.return_value = self._mock_post_html(HTML_WITH_ZIP_URL)
        session.get.return_value = self._mock_get_zip(ZIP_2021_O3)

        download_rama_excel(session, 2021)

        assert session.post.call_args.kwargs["data"]["unibaja"] == "Descargar archivo"

    def test_http_error_on_post_raises_without_retry(self) -> None:
        """Error HTTP 4xx en el POST no debe reintentarse."""
        session = MagicMock()
        session.post.return_value = self._mock_http_error(404)

        with pytest.raises(requests.HTTPError):
            download_rama_excel(session, 2021)

        assert session.post.call_count == 1

    def test_html_without_zip_url_raises_value_error(self) -> None:
        """HTML de respuesta sin URL ZIP debe levantar ValueError."""
        session = MagicMock()
        session.post.return_value = self._mock_post_html("<html>sin url</html>")

        with pytest.raises(ValueError, match="No se encontró URL de descarga ZIP"):
            download_rama_excel(session, 2022)

    def test_timeout_retries_three_times(self) -> None:
        """Timeout debe reintentarse hasta RETRY_ATTEMPTS (3) veces."""
        session = MagicMock()
        session.post.side_effect = requests.Timeout()

        with patch("etl.rama_bronze.time.sleep"):
            with pytest.raises(requests.RequestException):
                download_rama_excel(session, 2021)

        assert session.post.call_count == 3


# ---------------------------------------------------------------------------
# TestExtractAllFromZip
# ---------------------------------------------------------------------------


class TestExtractAllFromZip:
    """Pruebas para extract_all_from_zip."""

    def test_extracts_all_xls_files(self) -> None:
        """Debe retornar todos los archivos XLS del ZIP."""
        zip_bytes = _make_multi_zip(2021, ["O3", "PM25", "NO2"])
        result = extract_all_from_zip(zip_bytes)
        assert set(result.keys()) == {"2021O3.xls", "2021PM25.xls", "2021NO2.xls"}

    def test_content_matches_original(self) -> None:
        """El contenido extraído debe ser idéntico al original."""
        zip_bytes = _make_test_zip(2021, "O3", XLS_CONTENT)
        result = extract_all_from_zip(zip_bytes)
        assert result["2021O3.xls"] == XLS_CONTENT

    def test_raises_for_bad_zip(self) -> None:
        """Debe levantar BadZipFile si los bytes no son ZIP válido."""
        with pytest.raises(zipfile.BadZipFile):
            extract_all_from_zip(XLS_CONTENT)

    def test_empty_zip_returns_empty_dict(self) -> None:
        """ZIP sin XLS debe retornar diccionario vacío."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w"):
            pass
        result = extract_all_from_zip(buf.getvalue())
        assert result == {}


# ---------------------------------------------------------------------------
# TestRunRamaBronzeIngestion
# ---------------------------------------------------------------------------


class TestRunRamaBronzeIngestion:
    """Pruebas para run_rama_bronze_ingestion con mocks totales."""

    def test_skips_existing_files_without_downloading(self, tmp_path: Path) -> None:
        """Carpeta de año con XLS no debe provocar descarga."""
        year_dir = tmp_path / "year=2021"
        year_dir.mkdir(parents=True)
        (year_dir / "2021O3.xls").write_bytes(XLS_CONTENT)

        with patch("etl.rama_bronze.download_rama_excel") as mock_dl:
            stats = run_rama_bronze_ingestion(
                output_dir=tmp_path,
                start_year=2021,
                end_year=2021,
            )

        mock_dl.assert_not_called()
        assert stats["skipped"] == 1
        assert stats["downloaded"] == 0

    def test_downloads_missing_files(self, tmp_path: Path) -> None:
        """Año sin carpeta debe descargarse y guardarse todos los XLS."""
        zip_bytes = _make_multi_zip(2021, ["O3", "PM25"])
        with patch("etl.rama_bronze.download_rama_excel", return_value=zip_bytes):
            stats = run_rama_bronze_ingestion(
                output_dir=tmp_path,
                start_year=2021,
                end_year=2021,
            )

        assert stats["downloaded"] == 2
        assert stats["skipped"] == 0

    def test_overwrite_redownloads_existing_files(self, tmp_path: Path) -> None:
        """Con overwrite=True debe redownloadear aunque la carpeta exista."""
        year_dir = tmp_path / "year=2021"
        year_dir.mkdir(parents=True)
        (year_dir / "2021O3.xls").write_bytes(XLS_CONTENT)
        zip_bytes = _make_test_zip(2021, "O3")

        with patch("etl.rama_bronze.download_rama_excel", return_value=zip_bytes):
            stats = run_rama_bronze_ingestion(
                output_dir=tmp_path,
                start_year=2021,
                end_year=2021,
                overwrite=True,
            )

        assert stats["downloaded"] == 1
        assert stats["skipped"] == 0

    def test_dry_run_does_not_write_to_disk(self, tmp_path: Path) -> None:
        """Dry run no debe escribir archivos a disco."""
        with patch("etl.rama_bronze.download_rama_excel", return_value=ZIP_2021_O3):
            stats = run_rama_bronze_ingestion(
                output_dir=tmp_path,
                start_year=2021,
                end_year=2021,
                dry_run=True,
            )

        assert not (tmp_path / "year=2021").exists()
        assert stats["dry_run"] == 1
        assert stats["downloaded"] == 0

    def test_failed_download_counts_year_as_failed(self, tmp_path: Path) -> None:
        """Error de descarga ZIP debe marcar el año como fallido (1 conteo)."""
        with patch(
            "etl.rama_bronze.download_rama_excel",
            side_effect=requests.RequestException("timeout"),
        ):
            stats = run_rama_bronze_ingestion(
                output_dir=tmp_path,
                start_year=2021,
                end_year=2021,
            )

        assert stats["failed"] == 1
        assert stats["downloaded"] == 0

    def test_failed_extraction_counts_pollutant_as_failed(self, tmp_path: Path) -> None:
        """ZIP inválido debe marcar el año como fallido."""
        with patch("etl.rama_bronze.download_rama_excel", return_value=XLS_CONTENT):
            stats = run_rama_bronze_ingestion(
                output_dir=tmp_path,
                start_year=2021,
                end_year=2021,
            )

        assert stats["failed"] == 1
        assert stats["downloaded"] == 0

    def test_returns_all_four_stat_keys(self, tmp_path: Path) -> None:
        """El resultado debe contener las cuatro claves de estadísticas."""
        zip_bytes = _make_test_zip(2021, "O3")
        with patch("etl.rama_bronze.download_rama_excel", return_value=zip_bytes):
            stats = run_rama_bronze_ingestion(
                output_dir=tmp_path,
                start_year=2021,
                end_year=2021,
            )

        assert set(stats.keys()) == {"downloaded", "skipped", "failed", "dry_run"}

    def test_excel_downloaded_once_per_year_for_multiple_pollutants(
        self, tmp_path: Path
    ) -> None:
        """El ZIP anual se descarga una sola vez por año, sin importar contaminantes."""
        zip_bytes = _make_multi_zip(2023, ["O3", "PM25", "PM10", "NO2"])
        with patch(
            "etl.rama_bronze.download_rama_excel", return_value=zip_bytes
        ) as mock_dl:
            run_rama_bronze_ingestion(
                output_dir=tmp_path,
                start_year=2023,
                end_year=2023,
            )

        assert mock_dl.call_count == 1

    def test_multiple_years_download_once_each(self, tmp_path: Path) -> None:
        """Cada año debe provocar exactamente una descarga."""
        zip_bytes = _make_test_zip(2021, "O3")
        with patch(
            "etl.rama_bronze.download_rama_excel", return_value=zip_bytes
        ) as mock_dl:
            run_rama_bronze_ingestion(
                output_dir=tmp_path,
                start_year=2021,
                end_year=2023,
            )

        assert mock_dl.call_count == 3
