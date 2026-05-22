"""Capa Bronze: Copia archivos crudos de data/raw/ a AWS S3.

Automatiza la subida de todos los archivos de contaminantes y meteorología
desde `data/raw/` (incluyendo subcarpetas) al bucket S3 especificado, 
preservando estructura y formato.

Características:
    - Descubre automáticamente **todos** los archivos en `data/raw/` (recursivo)
    - Preserva estructura de carpetas anidadas en S3
    - Sube directamente a S3 (sin conversión)
    - Estructura en S3: `s3://<your-bucket-name>/air-sense-mx/bronze/`
    - Idempotente: verifica existencia antes de sobrescribir
    - Logs con cifras de control: archivos procesados, bytes, tiempo

Ejemplo de estructura de salida:
    - data/raw/file1.json → s3://<your-bucket-name>/air-sense-mx/bronze/file1.json
    - data/raw/subfolder/file2.csv → s3://<your-bucket-name>/air-sense-mx/bronze/subfolder/file2.csv
    - data/raw/a/b/c/file3.xlsx → s3://<your-bucket-name>/air-sense-mx/bronze/a/b/c/file3.xlsx

Uso:

    uv run python -m etl.bronze --bucket <your-bucket-name>
    uv run python -m etl.bronze --bucket <your-bucket-name> --data-dir /ruta/custom

Requisitos:
    boto3 — con permisos S3:PutObject.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import boto3

from utils.logging import get_logger, setup_logging

logger = get_logger(__name__)

# Configuración
S3_PREFIX: str = "air-sense-mx/bronze"


def upload_files_to_s3(
    data_dir: Path, bucket: str, dry_run: bool = False
) -> dict[str, int]:
    """Descubre archivos recursivamente en data_dir y los sube a S3.

    Args:
        data_dir: Ruta local al directorio de datos.
        bucket: Nombre del bucket S3 destino.
        dry_run: Si es True, solo simula sin subir.

    Returns:
        Diccionario con conteos: {"uploaded": N, "skipped": N, "failed": N, "bytes": B}
    """
    if not data_dir.is_dir():
        raise RuntimeError(f"Directorio no encontrado: {data_dir}")

    s3_client = boto3.client("s3")
    stats = {"uploaded": 0, "skipped": 0, "failed": 0, "bytes": 0}

    # Descubre archivos recursivamente (incluyendo subcarpetas)
    archivos = sorted([f for f in data_dir.rglob("*") if f.is_file()])

    if not archivos:
        logger.warning("No hay archivos en %s", data_dir)
        return stats

    logger.info(
        "Descubiertos %d archivo(s) en %s (recursivo)",
        len(archivos),
        data_dir,
        extra={"data_dir": str(data_dir), "files_count": len(archivos)},
    )

    for file_path in archivos:
        try:
            # Mantiene la estructura de carpetas relativa
            relative_path = file_path.relative_to(data_dir)
            s3_key = f"{S3_PREFIX}/{relative_path}"
            file_size = file_path.stat().st_size

            # Verifica si existe en S3
            try:
                s3_client.head_object(Bucket=bucket, Key=s3_key)
                logger.info(
                    "Saltado (existe en S3): %s",
                    relative_path,
                    extra={"file": str(relative_path), "s3_key": s3_key},
                )
                stats["skipped"] += 1
                continue
            except s3_client.exceptions.NoSuchKey:
                pass  # No existe, seguir con la subida

            if dry_run:
                logger.info(
                    "[DRY-RUN] Subiría: %s → s3://%s/%s (%d bytes)",
                    relative_path,
                    bucket,
                    s3_key,
                    file_size,
                )
                stats["uploaded"] += 1
                stats["bytes"] += file_size
            else:
                # Sube a S3
                s3_client.upload_file(str(file_path), bucket, s3_key)
                logger.info(
                    "✓ Subido: %s → s3://%s/%s (%d bytes)",
                    relative_path,
                    bucket,
                    s3_key,
                    file_size,
                    extra={
                        "file": str(relative_path),
                        "s3_key": s3_key,
                        "bytes": file_size,
                    },
                )
                stats["uploaded"] += 1
                stats["bytes"] += file_size

        except Exception as exc:
            logger.error(
                "Error subiendo %s: %s",
                file_path,
                str(exc),
                extra={"file": str(file_path), "error": str(exc)},
            )
            stats["failed"] += 1

    return stats


def main() -> None:
    """Orquesta la subida de archivos raw a Bronze en S3."""
    parser = argparse.ArgumentParser(
        description="ETL capa Bronze — Copia raw files a S3"
    )
    parser.add_argument("--bucket", required=True, help="Nombre del bucket S3 destino")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Ruta a data/raw/ (default: data/raw)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simula sin subir a S3",
    )
    args = parser.parse_args()

    # Setup
    setup_logging()
    data_dir = args.data_dir or Path("data/raw")

    try:
        logger.info("=== Bronze ETL — inicio ===")
        logger.info(
            "Bucket: %s | Data dir: %s | Dry-run: %s",
            args.bucket,
            data_dir,
            args.dry_run,
        )

        t_start = time.time()
        stats = upload_files_to_s3(data_dir, args.bucket, args.dry_run)
        elapsed = time.time() - t_start

        # Cifras de control finales
        logger.info("=== Bronze ETL — cifras de control ===")
        logger.info("  Archivos subidos    : %d", stats["uploaded"])
        logger.info("  Archivos saltados   : %d", stats["skipped"])
        logger.info("  Archivos fallidos   : %d", stats["failed"])
        logger.info(
            "  Bytes totales       : %d (%.2f MB)",
            stats["bytes"],
            stats["bytes"] / 1e6,
        )
        logger.info("  Tiempo total        : %.1fs", elapsed)
        logger.info("=== Bronze ETL — fin OK ===")

    except Exception:
        logger.exception("Error fatal en Bronze ETL")
        sys.exit(1)


if __name__ == "__main__":
    main()
