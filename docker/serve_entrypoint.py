#!/usr/bin/env python
"""Entrypoint de serving para SageMaker Batch Transform.

SageMaker espera dos modos de serving:
    1. Real-time endpoint (HTTP server) — requiere Flask/Gunicorn
    2. Batch Transform — lee de S3, escribe a S3, sin HTTP

USAMOS BATCH TRANSFORM porque:
    - El modelo predice una vez al día (no en tiempo real)
    - Más barato (no necesitamos endpoint prendido 24/7)
    - Streamlit consume desde S3/Athena la tabla generada
    - Coincide con el patrón "Familia 2: Sistemas de Scoring en Batch"
      del material del curso (capítulo 11)

PROTOCOLO BATCH TRANSFORM
=========================
SageMaker monta:
    /opt/ml/model/                  ← donde están los modelos del training job
    /opt/ml/input/data/             ← features Gold de entrada
    /opt/ml/output/                 ← donde guardar predicciones

Y ejecuta `serve` (sin argumentos). Por eso este archivo se instala en
/usr/local/bin/serve dentro del contenedor.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from pathlib import Path


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# =============================================================================
# PATHS ESTÁNDAR DE SAGEMAKER (BATCH TRANSFORM)
# =============================================================================
MODEL_DIR = Path(os.environ.get("SM_MODEL_DIR", "/opt/ml/model"))
INPUT_DIR = Path("/opt/ml/input/data")
OUTPUT_DIR = Path("/opt/ml/output")
FAILURE_PATH = Path("/opt/ml/output/failure")


def main() -> int:
    try:
        logger.info("=" * 60)
        logger.info("SageMaker Batch Transform — AirSense MX")
        logger.info("=" * 60)
        logger.info(f"Model dir: {MODEL_DIR}")
        logger.info(f"Input:     {INPUT_DIR}")
        logger.info(f"Output:    {OUTPUT_DIR}")

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # Localizar archivo(s) de Gold a procesar
        input_files = list(INPUT_DIR.rglob("*.parquet"))
        if not input_files:
            raise FileNotFoundError(
                f"No se encontró ningún .parquet en {INPUT_DIR}. "
                "Verifica el input del Batch Transform Job."
            )
        logger.info(f"Encontrados {len(input_files)} archivo(s) de entrada")

        # Hyperparams: para batch transform los pasamos como env vars
        # (SageMaker no inyecta hyperparameters.json en transform jobs)
        horizonte = int(os.environ.get("HORIZONTE", "1"))
        modelo_version = os.environ.get("MODELO_VERSION", "lgbm_v1.0")
        fecha_inicio = os.environ.get("FECHA_INICIO", None)
        fecha_fin = os.environ.get("FECHA_FIN", None)

        import pandas as pd
        from inference.predict import construir_predicciones

        # Leer Gold
        if len(input_files) == 1:
            gold = pd.read_parquet(input_files[0])
        else:
            gold = pd.concat(
                [pd.read_parquet(f) for f in input_files], ignore_index=True
            )
        logger.info(f"Gold cargado: {len(gold):,} filas")

        # Generar predicciones
        predicciones = construir_predicciones(
            gold=gold,
            models_dir=MODEL_DIR,
            horizonte=horizonte,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            modelo_version=modelo_version,
        )

        # Escribir output (SageMaker lo sube automáticamente a S3 si el job
        # se configuró con S3OutputPath)
        output_file = OUTPUT_DIR / "predicciones_diarias.parquet"
        predicciones.to_parquet(output_file, compression="snappy", index=False)
        logger.info(f"✓ Predicciones escritas: {output_file} ({len(predicciones):,} filas)")

        # Resumen
        resumen = {
            "n_predictions": len(predicciones),
            "fechas_objetivo_min": str(predicciones["fecha_objetivo"].min()),
            "fechas_objetivo_max": str(predicciones["fecha_objetivo"].max()),
            "estaciones": predicciones["station_id"].nunique(),
            "contaminantes": sorted(predicciones["contaminante"].unique()),
            "semaforo_dist": predicciones["semaforo"].value_counts().to_dict(),
        }
        with open(OUTPUT_DIR / "transform_summary.json", "w") as f:
            json.dump(resumen, f, indent=2, default=str)
        logger.info(f"Resumen: {resumen}")

        return 0

    except Exception as e:
        logger.error(f"Batch transform falló: {e}")
        logger.error(traceback.format_exc())
        FAILURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(FAILURE_PATH, "w") as f:
            f.write(f"{e}\n\n{traceback.format_exc()}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
