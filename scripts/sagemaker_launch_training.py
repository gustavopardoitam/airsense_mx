"""Launcher de SageMaker Training Job para AirSense MX.

Ejecuta desde SageMaker Studio JupyterLab (donde tienes IAM role configurado)
o desde local si tienes credenciales AWS configuradas y el rol de ejecución.

Uso:
    python scripts/sagemaker_launch_training.py \\
        --image-uri 123456789.dkr.ecr.us-east-1.amazonaws.com/airsense-mx:v1.0 \\
        --gold-s3-path s3://airsense-mx/gold/panel_diario.parquet \\
        --output-s3-path s3://airsense-mx/models/v1.0/ \\
        --instance-type ml.m5.large

REQUISITOS
==========
- Imagen ya pusheada a ECR (ver scripts/build_and_push_ecr.sh)
- Gold parquet ya en S3
- Rol de ejecución SageMaker con permisos a S3, ECR y CloudWatch Logs
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def lanzar_training_job(
    image_uri: str,
    gold_s3_path: str,
    output_s3_path: str,
    role: str | None = None,
    instance_type: str = "ml.m5.large",
    instance_count: int = 1,
    job_name: str | None = None,
    horizonte: int = 1,
    train_inicio: str = "2021-01-01",
    train_fin: str = "2024-12-31",
    val_inicio: str = "2025-01-01",
    val_fin: str = "2025-09-30",
    test_inicio: str = "2025-10-01",
    test_fin: str = "2026-02-28",
    max_run_seconds: int = 3600,
    wait: bool = True,
) -> dict:
    """Lanza un Training Job en SageMaker usando la imagen BYOC.

    Args:
        image_uri: URI completa de la imagen en ECR.
        gold_s3_path: ruta S3 al Gold parquet de entrada.
        output_s3_path: ruta S3 donde guardar los artefactos del modelo.
        role: ARN del rol de ejecución SageMaker. Si None, lo detecta del entorno.
        instance_type: tipo de instancia (default ml.m5.large).
        instance_count: número de instancias (1 para LightGBM).
        job_name: nombre del job. Si None, se genera con timestamp.
        horizonte: días hacia adelante a predecir (1-7).
        train_inicio..test_fin: ventanas del split temporal.
        max_run_seconds: timeout del job en segundos (default 1h).
        wait: si True, bloquea hasta que el job termine.

    Returns:
        Dict con job_name, status, model_path, métricas.
    """
    # Imports lazy para que el módulo se pueda importar sin sagemaker instalado
    import sagemaker
    from sagemaker.estimator import Estimator

    session = sagemaker.Session()

    # Detectar role automáticamente si no se pasa
    if role is None:
        try:
            role = sagemaker.get_execution_role()
            logger.info(f"Detectado rol SageMaker: {role}")
        except Exception as e:
            raise RuntimeError(
                "No se pudo detectar el rol SageMaker. "
                "Pásalo explícitamente con --role o ejecuta desde SageMaker Studio."
            ) from e

    # Generar nombre del job si no se pasa
    if job_name is None:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        job_name = f"airsense-mx-train-h{horizonte}-{ts}"

    logger.info(f"Lanzando training job: {job_name}")
    logger.info(f"  Image:    {image_uri}")
    logger.info(f"  Gold:     {gold_s3_path}")
    logger.info(f"  Output:   {output_s3_path}")
    logger.info(f"  Instance: {instance_type} × {instance_count}")

    # Hyperparameters que se pasan al contenedor vía hyperparameters.json
    hyperparameters = {
        "horizonte": horizonte,
        "train_inicio": train_inicio,
        "train_fin": train_fin,
        "val_inicio": val_inicio,
        "val_fin": val_fin,
        "test_inicio": test_inicio,
        "test_fin": test_fin,
    }

    estimator = Estimator(
        image_uri=image_uri,
        role=role,
        instance_count=instance_count,
        instance_type=instance_type,
        output_path=output_s3_path,
        sagemaker_session=session,
        hyperparameters=hyperparameters,
        max_run=max_run_seconds,
        # Metrics que SageMaker capturará desde los logs del entrypoint
        # (regex sobre cada línea del log)
        metric_definitions=[
            {"Name": "o3_test_mae",   "Regex": r"O3:\s+MAE=([0-9.]+)"},
            {"Name": "pm25_test_mae", "Regex": r"PM25:\s+MAE=([0-9.]+)"},
            {"Name": "pm10_test_mae", "Regex": r"PM10:\s+MAE=([0-9.]+)"},
        ],
        tags=[
            {"Key": "Project", "Value": "AirSense-MX"},
            {"Key": "Owner", "Value": "Gustavo"},
            {"Key": "Course", "Value": "MetodosGranEscala"},
        ],
    )

    # Lanzar el job
    estimator.fit(
        inputs={"training": gold_s3_path},
        job_name=job_name,
        wait=wait,
        logs="All" if wait else None,
    )

    return {
        "job_name": job_name,
        "model_data": estimator.model_data if wait else None,
        "training_job_arn": (
            estimator.latest_training_job.describe()["TrainingJobArn"]
            if wait else None
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Launcher SageMaker Training Job")
    parser.add_argument("--image-uri", required=True,
                        help="URI completa de la imagen en ECR")
    parser.add_argument("--gold-s3-path", required=True,
                        help="Path S3 al Gold parquet de entrada")
    parser.add_argument("--output-s3-path", required=True,
                        help="Path S3 para guardar artefactos del modelo")
    parser.add_argument("--role", default=None,
                        help="ARN del rol SageMaker (default: detectar)")
    parser.add_argument("--instance-type", default="ml.m5.large",
                        help="Tipo de instancia (default: ml.m5.large)")
    parser.add_argument("--horizonte", type=int, default=1)
    parser.add_argument("--no-wait", action="store_true",
                        help="No esperar a que termine el job")
    args = parser.parse_args()

    result = lanzar_training_job(
        image_uri=args.image_uri,
        gold_s3_path=args.gold_s3_path,
        output_s3_path=args.output_s3_path,
        role=args.role,
        instance_type=args.instance_type,
        horizonte=args.horizonte,
        wait=not args.no_wait,
    )

    logger.info(f"✓ Job lanzado: {result['job_name']}")
    if result.get("model_data"):
        logger.info(f"  Model data: {result['model_data']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
