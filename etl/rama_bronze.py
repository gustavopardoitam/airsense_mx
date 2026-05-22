r"""Capa Bronze: ingesta de archivos Excel históricos RAMA/SIMAT.

Descarga datos históricos de contaminantes atmosféricos (O3, PM25, PM10,
NO2, SO2, CO) desde el portal oficial de calidad del aire de la CDMX
y los almacena como archivos crudos en la estructura Bronze del data lake.

Decisiones de diseño:
- Un Excel por año: el portal entrega un archivo consolidado anual.
- Se guarda una copia raw por contaminante para compatibilidad downstream Silver.
- Idempotente: verifica existencia de archivos antes de descargar.
- Bronze no transforma datos — los bytes se guardan tal como vienen del portal.
- Validación de firma binaria protege contra descargas parciales o respuestas HTML.

Estructura de salida:
    data/raw/rama/year=2021/2021O3.xls
    data/raw/rama/year=2021/2021PM25.xls

Uso:
    uv run python -m etl.rama_bronze \\
      --output-dir data/raw/rama \\
      --start-year 2021 \\
      --pollutants O3 PM25 PM10 NO2 SO2 CO
"""

from __future__ import annotations

import argparse
import io
import re
import ssl
import time
import zipfile
from datetime import datetime
from pathlib import Path

import requests
import urllib3
from requests.adapters import HTTPAdapter
from requests.exceptions import HTTPError, RequestException, Timeout

from utils.logging import get_logger, setup_logging

# El portal aire.cdmx.gob.mx usa DH con clave corta (legacy gov server) y CA
# gubernamental mexicana no incluida en bundles estándar.
# SECLEVEL=1 + OP_LEGACY_SERVER_CONNECT + send(verify=False) resuelven ambos.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

RAMA_BASE_URL = "https://www.aire.cdmx.gob.mx/default.php?opc=%27aKBh%27"
DEFAULT_POLLUTANTS: list[str] = ["O3", "PM25", "PM10", "NO2", "SO2", "CO"]
DEFAULT_START_YEAR: int = 2021
REQUEST_TIMEOUT_SECONDS: int = 60
RETRY_ATTEMPTS: int = 3
RETRY_BACKOFF_SECONDS: float = 5.0

# Firmas binarias para validación de contenido Excel
_XLS_MAGIC = b"\xd0\xcf\x11\xe0"  # Compound Document (XLS clásico)
_XLSX_MAGIC = b"PK\x03\x04"  # ZIP/OOXML (XLSX, XLSM)
_HTML_MARKER = b"<html"  # Respuesta HTML (error del portal)


# ---------------------------------------------------------------------------
# Funciones de utilidad
# ---------------------------------------------------------------------------


def year_to_simat_value(year: int) -> str:
    """Convierte un año calendario al valor de dos dígitos del formulario SIMAT.

    El portal RAMA usa los dos últimos dígitos del año como valor del campo
    `seluniano` en el formulario POST.

    Args:
        year: Año calendario completo (p.ej. 2021).

    Returns:
        Cadena de dos caracteres (p.ej. "21" para 2021).

    Ejemplo:
        >>> year_to_simat_value(2024)
        '24'
    """
    return str(year)[-2:]


def build_rama_download_url() -> str:
    """Devuelve la URL base del portal RAMA para el formulario de descarga.

    Returns:
        URL del portal de calidad del aire de la CDMX.
    """
    return RAMA_BASE_URL


def build_output_path(output_dir: Path, filename: str, year: int) -> Path:
    """Construye la ruta de salida Bronze para un archivo y año dados.

    Sigue la convención de particionamiento Hive del data lake.
    Un directorio por año contiene todos los XLS de contaminantes.

    Args:
        output_dir: Directorio raíz Bronze para RAMA.
        filename: Nombre del archivo tal como viene en el ZIP (p.ej. "2021O3.xls").
        year: Año calendario.

    Returns:
        Ruta completa al archivo Excel de destino.

    Ejemplo:
        >>> build_output_path(Path("data/raw/rama"), "2021O3.xls", 2021)
        PosixPath('data/raw/rama/year=2021/2021O3.xls')
    """
    return output_dir / f"year={year}" / filename


def looks_like_excel(content: bytes) -> bool:
    """Valida que el contenido descargado sea un archivo Excel binario.

    Compara los primeros bytes con las firmas conocidas de XLS clásico
    y XLSX. Rechaza respuestas HTML que indican un error del portal.

    Args:
        content: Bytes descargados del portal.

    Returns:
        True si el contenido parece ser XLS o XLSX válido.
    """
    if not content:
        return False
    if content[:4] == _XLS_MAGIC:
        return True
    if content[:4] == _XLSX_MAGIC:
        return True
    if _HTML_MARKER in content[:512].lower():
        return False
    return False


def save_excel_file(path: Path, content: bytes) -> None:
    """Guarda bytes crudos de Excel en disco, creando directorios si es necesario.

    Args:
        path: Ruta destino del archivo.
        content: Bytes del archivo Excel a guardar.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    logger.info(
        "Archivo Excel guardado",
        extra={"path": str(path), "bytes": len(content)},
    )


# ---------------------------------------------------------------------------
# Utilidades de parseo
# ---------------------------------------------------------------------------


def _extract_zip_url_from_html(html_text: str) -> str:
    """Extrae la URL del ZIP de descarga del JavaScript de redirección del portal.

    El portal CDMX responde al POST con HTML que contiene un snippet JS:
        setTimeout("location.href='https://...YYRAMA.zip'",1000);

    Args:
        html_text: Cuerpo HTML de la respuesta POST del portal.

    Returns:
        URL absoluta del archivo ZIP.

    Raises:
        ValueError: Si no se encuentra el patrón esperado en el HTML.
    """
    match = re.search(r"location\.href='([^']+\.zip)'", html_text, re.IGNORECASE)
    if not match:
        raise ValueError(
            "No se encontró URL de descarga ZIP en la respuesta del portal CDMX. "
            "El portal puede haber cambiado su estructura o el año no está disponible."
        )
    return match.group(1)


def extract_all_from_zip(zip_bytes: bytes) -> dict[str, bytes]:
    """Extrae todos los archivos XLS del ZIP anual RAMA.

    El ZIP contiene un XLS por contaminante (p.ej. 2021O3.xls, 2021PM25.xls).
    Se extraen todos sin necesidad de especificar contaminantes.

    Args:
        zip_bytes: Contenido del ZIP descargado del portal RAMA.

    Returns:
        Diccionario {nombre_archivo: bytes_crudos} para todos los XLS del ZIP.

    Raises:
        zipfile.BadZipFile: Si los bytes no corresponden a un ZIP válido.
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return {
            name: zf.read(name)
            for name in zf.namelist()
            if name.lower().endswith((".xls", ".xlsx"))
        }


# ---------------------------------------------------------------------------
# Descarga HTTP
# ---------------------------------------------------------------------------


class _LegacySSLAdapter(HTTPAdapter):
    """Adaptador HTTP para el portal CDMX con SSL legacy.

    El servidor usa parámetros Diffie-Hellman cortos y una CA gubernamental
    mexicana no incluida en los bundles estándar. Se requieren dos ajustes:
    - SECLEVEL=1: acepta claves DH <1024 bits.
    - OP_LEGACY_SERVER_CONNECT: permite renegociación legacy (Python 3.12+).
    - send() con verify=False: omite verificación de CA no estándar.
    """

    def init_poolmanager(self, *args: object, **kwargs: object) -> None:
        """Configura el pool con contexto SSL permisivo para el portal CDMX."""
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0)
        kwargs["ssl_context"] = ctx  # type: ignore[arg-type]
        super().init_poolmanager(*args, **kwargs)

    def send(  # type: ignore[override]
        self,
        request: requests.PreparedRequest,
        **kwargs: object,
    ) -> requests.Response:
        """Fuerza verify=False para omitir CA gubernamental no estándar."""
        kwargs["verify"] = False
        return super().send(request, **kwargs)  # type: ignore[arg-type]


def _make_session() -> requests.Session:
    """Crea una sesión HTTP con adaptador SSL compatible con el portal CDMX.

    El portal usa un servidor legacy con DH key corta y CA gubernamental
    mexicana. Se usa SECLEVEL=1 y se deshabilita verificación de certificado.
    """
    session = requests.Session()
    session.mount("https://", _LegacySSLAdapter())
    session.headers.update(
        {
            "User-Agent": "AirSenseMX/1.0 (investigación académica ITAM)",
            "Referer": RAMA_BASE_URL,
        }
    )
    logger.warning(
        "SSL SECLEVEL=1 activo para portal CDMX (servidor legacy gubernamental)"
    )
    return session


def download_rama_excel(session: requests.Session, year: int) -> bytes:
    r"""Descarga el ZIP anual RAMA mediante POST al formulario oficial.

    Flujo de descarga:
    1. POST al formulario con seluniano=<YY> para activar la descarga.
    2. Parsea la URL ZIP del JavaScript de redirección en el HTML de respuesta.
    3. GET para descargar el ZIP desde la URL extraída.

    Reintenta hasta RETRY_ATTEMPTS veces con backoff lineal ante errores de
    red. Valida la firma binaria (PK\x03\x04) del ZIP resultante.

    Args:
        session: Sesión HTTP reutilizable (requests.Session).
        year: Año calendario a descargar.

    Returns:
        Bytes crudos del ZIP anual (contiene XLS por contaminante).

    Raises:
        requests.HTTPError: Si el portal retorna código HTTP no-2xx.
        requests.Timeout: Si el portal no responde en el tiempo configurado.
        ValueError: Si el HTML no contiene URL ZIP o el archivo descargado es inválido.
        requests.RequestException: Si todos los reintentos fallan.
    """
    url = build_rama_download_url()
    form_data = {
        "seluniano": year_to_simat_value(year),
        "unibaja": "Descargar archivo",
    }

    last_exc: Exception | None = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            # Paso 1: POST → HTML con JS redirect
            post_resp = session.post(
                url, data=form_data, timeout=REQUEST_TIMEOUT_SECONDS
            )
            post_resp.raise_for_status()

            # Paso 2: Extraer URL ZIP del HTML
            zip_url = _extract_zip_url_from_html(post_resp.text)

            # Paso 3: GET → descarga ZIP
            get_resp = session.get(zip_url, timeout=REQUEST_TIMEOUT_SECONDS)
            get_resp.raise_for_status()

            content = get_resp.content
            if not looks_like_excel(content):
                raise ValueError(
                    f"Contenido descargado no es ZIP/Excel válido (año={year}): "
                    f"primeros bytes={content[:8]!r}"
                )
            logger.info(
                "ZIP RAMA descargado",
                extra={
                    "year": year,
                    "bytes": len(content),
                    "zip_url": zip_url,
                    "attempt": attempt,
                },
            )
            return content
        except (HTTPError, ValueError) as exc:
            logger.error(
                "Error no reintentable en descarga RAMA",
                extra={"year": year, "error": str(exc)},
            )
            raise
        except (Timeout, RequestException) as exc:
            last_exc = exc
            logger.warning(
                "Error transitorio — reintentando",
                extra={"year": year, "attempt": attempt, "error": str(exc)},
            )
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    raise RequestException(
        f"Descarga RAMA fallida tras {RETRY_ATTEMPTS} intentos para año={year}"
    ) from last_exc


# ---------------------------------------------------------------------------
# Orquestador
# ---------------------------------------------------------------------------


def run_rama_bronze_ingestion(
    output_dir: Path,
    start_year: int,
    end_year: int,
    pollutants: list[str] | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
) -> dict[str, int]:
    """Orquesta la ingesta Bronze RAMA: un ZIP por año con todos los contaminantes.

    Por cada año descarga el ZIP una sola vez y extrae automáticamente todos los
    XLS que contiene. Los archivos se guardan en data/raw/rama/year={año}/.
    Idempotente: si la carpeta del año ya tiene archivos XLS, salta la descarga.

    Args:
        output_dir: Directorio raíz de salida (p.ej. data/raw/rama).
        start_year: Año inicial de la ingesta (inclusive).
        end_year: Año final de la ingesta (inclusive).
        pollutants: Lista de contaminantes a guardar (p.ej. ["O3", "PM25"]).
            Si es None, se guardan todos los XLS del ZIP.
        overwrite: Si True, reingesta aunque la carpeta del año ya exista.
        dry_run: Si True, registra en log pero no escribe a disco.

    Returns:
        Diccionario con conteos: downloaded, skipped, failed, dry_run.
    """
    stats: dict[str, int] = {"downloaded": 0, "skipped": 0, "failed": 0, "dry_run": 0}
    session = _make_session()

    logger.info(
        "Ingesta Bronze RAMA iniciada",
        extra={"years": list(range(start_year, end_year + 1))},
    )

    for year in range(start_year, end_year + 1):
        year_dir = output_dir / f"year={year}"
        existing = list(year_dir.glob("*.xls*")) if year_dir.exists() else []

        if existing and not overwrite:
            logger.info(
                "Año ya descargado — saltando",
                extra={"year": year, "files": len(existing)},
            )
            stats["skipped"] += len(existing)
            continue

        if dry_run:
            logger.info("Dry run — se omitiría descarga", extra={"year": year})
            stats["dry_run"] += 1
            continue

        try:
            zip_bytes = download_rama_excel(session, year)
        except Exception as exc:
            logger.error(
                "Descarga ZIP fallida — saltando año",
                extra={"year": year, "error": str(exc)},
            )
            stats["failed"] += 1
            continue

        try:
            xls_files = extract_all_from_zip(zip_bytes)
        except zipfile.BadZipFile as exc:
            logger.error(
                "ZIP inválido — saltando año",
                extra={"year": year, "error": str(exc)},
            )
            stats["failed"] += 1
            continue

        for filename, content in xls_files.items():
            if pollutants and not any(filename == f"{year}{p}.xls" for p in pollutants):
                continue
            path = build_output_path(output_dir, filename, year)
            save_excel_file(path, content)
            stats["downloaded"] += 1

        logger.info(
            "Año procesado",
            extra={"year": year, "contaminantes": len(xls_files)},
        )

    logger.info("Ingesta Bronze RAMA finalizada", extra={"stats": stats})
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    """Parsea argumentos de línea de comandos para la ingesta RAMA Bronze."""
    parser = argparse.ArgumentParser(
        description="Ingesta Bronze RAMA — descarga Excels anuales del portal CDMX"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw/rama"),
        help="Directorio raíz de salida (default: data/raw/rama)",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=DEFAULT_START_YEAR,
        help=f"Año inicial de ingesta (default: {DEFAULT_START_YEAR})",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=datetime.now().year,
        help="Año final de ingesta (default: año actual)",
    )
    parser.add_argument(
        "--pollutants",
        nargs="+",
        default=None,
        metavar="CONTAMINANTE",
        help=(
            "Filtrar contaminantes a guardar (p.ej. O3 PM25 NO2). "
            "Sin este flag se guardan todos."
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Reingesta archivos aunque ya existan",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Registra en log pero no escribe a disco",
    )
    return parser.parse_args()


def main() -> None:
    """Punto de entrada principal para `python -m etl.rama_bronze`."""
    setup_logging()
    args = _parse_args()
    stats = run_rama_bronze_ingestion(
        output_dir=args.output_dir,
        start_year=args.start_year,
        end_year=args.end_year,
        pollutants=args.pollutants,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
    )
    logger.info(
        "Resumen final",
        extra={
            "downloaded": stats["downloaded"],
            "skipped": stats["skipped"],
            "failed": stats["failed"],
        },
    )


if __name__ == "__main__":
    main()
