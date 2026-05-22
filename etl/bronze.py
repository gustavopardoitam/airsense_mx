"""Capa Bronze: Ingestión de datos crudos a S3.

Fuentes:
    - RAMA/SIMAT: Contaminantes (O₃, SO₂, NOₓ, CO, PM10, PM2.5, H₂S)
    - Open-Meteo: Datos meteorológicos históricos
    - PCAA: Registros de contingencias ambientales

Schema mínimo Bronze:
    - Todos los campos de la fuente original
    - _ingested_at: timestamp de ingestión
    - _source_file: nombre del archivo original

Particionamiento: year/month

Todo:
    - Implementar ingestión desde RAMA/SIMAT API
    - Implementar descarga de Open-Meteo
    - Implementar carga de PCAA
    - S3 upload con awswrangler
"""

from __future__ import annotations

from utils.logging import get_logger

logger = get_logger(__name__)

# Whitelist explícita de archivos esperados en Bronze
BRONZE_FILES: list[str] = [
    "rama_simat_2024.parquet",
    "open_meteo_2024.parquet",
    "pcaa_2024.parquet",
]


def ingest_rama_simat() -> None:
    """Descarga y carga datos de RAMA/SIMAT a Bronze en S3.

    TODO: Implementar
        1. Query a API RAMA/SIMAT
        2. Normalizar schema
        3. Agregar columnas técnicas (_ingested_at, _source_file)
        4. Guardar a S3 particionado por year/month

    Raises:
        DataUnavailableError: Si la API no está disponible
    """
    logger.info(
        "Iniciando ingestión RAMA/SIMAT",
        extra={"source": "rama_simat", "stage": "bronze"},
    )
    logger.warning(
        "TODO: ingest_rama_simat no implementado",
        extra={"source": "rama_simat"},
    )


def ingest_open_meteo() -> None:
    """Descarga y carga datos meteorológicos de Open-Meteo a Bronze.

    TODO: Implementar
        1. Query a Open-Meteo Historical Weather API
        2. Variables: temperatura, humedad, presión, viento
        3. Frecuencia: horaria
        4. Guardar a S3 particionado por year/month

    Raises:
        DataUnavailableError: Si la API no está disponible
    """
    logger.info(
        "Iniciando ingestión Open-Meteo",
        extra={"source": "open_meteo", "stage": "bronze"},
    )
    logger.warning(
        "TODO: ingest_open_meteo no implementado",
        extra={"source": "open_meteo"},
    )


def ingest_pcaa() -> None:
    """Carga registros de contingencias ambientales a Bronze.

    TODO: Implementar
        1. Leer archivo o query API de PCAA
        2. Schema: date, contingency_phase (0-3), affected_areas
        3. Guardar a S3 particionado por year/month

    Raises:
        DataUnavailableError: Si la fuente no está disponible
    """
    logger.info(
        "Iniciando ingestión PCAA",
        extra={"source": "pcaa", "stage": "bronze"},
    )
    logger.warning(
        "TODO: ingest_pcaa no implementado",
        extra={"source": "pcaa"},
    )
