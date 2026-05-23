"""Sincronización de la capa Gold desde el bucket de Gustavo al bucket propio.

Copia server-side (sin descargar datos) los objetos Parquet de
gold/predicciones_diarias/, gold/panel_diario/ y el archivo
dim/dim_estaciones.csv desde airsense-mx-gustavo hacia
itam-analytics-antonio/airsense-mx/.

Uso:
    uv run python scripts/sync_gold_from_gustavo.py
    uv run python scripts/sync_gold_from_gustavo.py --dry-run

Credenciales:
    Local  → ~/.aws/credentials o variables de entorno AWS_*.
    ECS    → IAM Task Role (sin configuración adicional).

Notas:
    - La copia es server-side: boto3 no descarga los objetos, solo los
      replica dentro de S3. No consume ancho de banda local.
    - Idempotente: volver a ejecutar sobreescribe con la versión más
      reciente de Gustavo.
    - Ejecutar una vez al día, después de que el pipeline de Gustavo
      termine (p.ej. via cron o EventBridge).
"""

from __future__ import annotations

import argparse
import sys

import boto3
from botocore.exceptions import ClientError

from utils.logging import get_logger, setup_logging

logger = get_logger(__name__)

# =============================================================================
# CONSTANTES
# =============================================================================

SRC_BUCKET: str = "airsense-mx-gustavo"
DST_BUCKET: str = "itam-analytics-antonio"
DST_PREFIX: str = "airsense-mx"

# Pares (prefijo_origen, prefijo_destino) a sincronizar
PREFIJOS: list[tuple[str, str]] = [
    ("gold/predicciones_diarias/", f"{DST_PREFIX}/gold/predicciones_diarias/"),
    ("gold/panel_diario/", f"{DST_PREFIX}/gold/panel_diario/"),
    ("dim/dim_estaciones.csv", f"{DST_PREFIX}/dim/dim_estaciones.csv"),
]


# =============================================================================
# LÓGICA DE COPIA
# =============================================================================


def _listar_objetos(s3: object, bucket: str, prefix: str) -> list[str]:
    """Lista todas las claves bajo un prefijo en S3.

    Args:
        s3: Cliente boto3 de S3.
        bucket: Nombre del bucket.
        prefix: Prefijo (carpeta) a listar.

    Returns:
        Lista de claves (strings) encontradas.
    """
    claves: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            claves.append(obj["Key"])
    return claves


def _copiar_objeto(
    s3: object,
    src_key: str,
    dst_key: str,
    dry_run: bool,
) -> bool:
    """Copia un objeto de forma server-side entre buckets.

    Args:
        s3: Cliente boto3 de S3.
        src_key: Clave origen en SRC_BUCKET.
        dst_key: Clave destino en DST_BUCKET.
        dry_run: Si True, solo loggea sin copiar.

    Returns:
        True si la copia fue exitosa (o dry-run), False si hubo error.
    """
    if dry_run:
        logger.info(
            "[DRY-RUN] Copiaría objeto",
            extra={"src": f"s3://{SRC_BUCKET}/{src_key}", "dst": f"s3://{DST_BUCKET}/{dst_key}"},
        )
        return True
    try:
        s3.copy_object(
            CopySource={"Bucket": SRC_BUCKET, "Key": src_key},
            Bucket=DST_BUCKET,
            Key=dst_key,
        )
        return True
    except ClientError as exc:
        logger.error(
            "Error al copiar objeto",
            extra={"src_key": src_key, "error": str(exc)},
        )
        return False


def sincronizar_prefijo(
    s3: object,
    src_prefix: str,
    dst_prefix: str,
    dry_run: bool,
) -> tuple[int, int]:
    """Sincroniza todos los objetos bajo src_prefix hacia dst_prefix.

    Args:
        s3: Cliente boto3 de S3.
        src_prefix: Prefijo origen en SRC_BUCKET.
        dst_prefix: Prefijo destino en DST_BUCKET.
        dry_run: Modo simulación sin escritura real.

    Returns:
        Tupla (copiados, fallidos).
    """
    # Caso especial: clave individual (no termina en /)
    if not src_prefix.endswith("/"):
        ok = _copiar_objeto(s3, src_prefix, dst_prefix, dry_run)
        return (1, 0) if ok else (0, 1)

    claves = _listar_objetos(s3, SRC_BUCKET, src_prefix)
    if not claves:
        logger.warning(
            "Prefijo vacío o sin acceso",
            extra={"src": f"s3://{SRC_BUCKET}/{src_prefix}"},
        )
        return (0, 0)

    copiados = fallidos = 0
    for src_key in claves:
        # Reemplaza solo el prefijo raíz para construir la clave destino
        rel = src_key[len(src_prefix):]
        dst_key = f"{dst_prefix}{rel}"
        if _copiar_objeto(s3, src_key, dst_key, dry_run):
            copiados += 1
        else:
            fallidos += 1

    return copiados, fallidos


# =============================================================================
# ENTRY POINT
# =============================================================================


def main() -> None:
    """Punto de entrada del script de sincronización."""
    setup_logging()

    parser = argparse.ArgumentParser(
        description=(
            "Sincroniza la capa Gold desde airsense-mx-gustavo"
            " a itam-analytics-antonio."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simula la sincronización sin escribir en S3.",
    )
    args = parser.parse_args()

    modo = "DRY-RUN" if args.dry_run else "REAL"
    logger.info(
        "Iniciando sincronización Gold",
        extra={"modo": modo, "src_bucket": SRC_BUCKET, "dst_bucket": DST_BUCKET},
    )

    s3 = boto3.client("s3")
    total_copiados = total_fallidos = 0

    for src_prefix, dst_prefix in PREFIJOS:
        logger.info(
            "Sincronizando prefijo",
            extra={"src": f"s3://{SRC_BUCKET}/{src_prefix}"},
        )
        copiados, fallidos = sincronizar_prefijo(
            s3, src_prefix, dst_prefix, args.dry_run
        )
        total_copiados += copiados
        total_fallidos += fallidos
        logger.info(
            "Prefijo completado",
            extra={
                "src_prefix": src_prefix,
                "copiados": copiados,
                "fallidos": fallidos,
            },
        )

    logger.info(
        "Sincronización finalizada",
        extra={
            "total_copiados": total_copiados,
            "total_fallidos": total_fallidos,
            "modo": modo,
        },
    )

    if total_fallidos > 0:
        logger.error(
            "Algunos objetos fallaron",
            extra={"fallidos": total_fallidos},
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
