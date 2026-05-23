#!/usr/bin/env python
"""Entrypoint de training para SageMaker.

Este script es invocado por SageMaker dentro del contenedor cuando se lanza
un Training Job. Su responsabilidad es ser un adaptador delgado entre el
protocolo de SageMaker y nuestra función de training real.

PROTOCOLO SAGEMAKER
===================
SageMaker monta paths fijos dentro del contenedor:

    /opt/ml/input/data/training/    ← Gold parquet (channel "training")
    /opt/ml/input/config/           ← hyperparameters.json, resourceconfig.json
    /opt/ml/model/                  ← DEBE guardar el modelo aquí
    /opt/ml/output/                 ← logs y artefactos secundarios
    /opt/ml/output/failure          ← si existe al terminar, el job se marca como FAILED

Y ejecuta `train` (sin argumentos). Por eso este archivo se instala en
/usr/local/bin/train dentro del contenedor.

VARIABLES DE ENTORNO ESTÁNDAR DE SAGEMAKER
==========================================
SageMaker inyecta automáticamente:
    SM_CHANNEL_TRAINING   = /opt/ml/input/data/training
    SM_MODEL_DIR          = /opt/ml/model
    SM_OUTPUT_DATA_DIR    = /opt/ml/output/data
    SM_HPS                = JSON con hyperparámetros pasados al Estimator
    SM_NUM_GPUS, SM_HOSTS, etc.

Las usamos para no hardcodear paths.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from pathlib import Path


# =============================================================================
# CONFIGURACIÓN DE LOGGING
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# =============================================================================
# PATHS ESTÁNDAR DE SAGEMAKER
# =============================================================================
INPUT_DATA_DIR = Path(os.environ.get("SM_CHANNEL_TRAINING", "/opt/ml/input/data/training"))
MODEL_DIR = Path(os.environ.get("SM_MODEL_DIR", "/opt/ml/model"))
OUTPUT_DIR = Path(os.environ.get("SM_OUTPUT_DATA_DIR", "/opt/ml/output/data"))
HYPERPARAMS_PATH = Path("/opt/ml/input/config/hyperparameters.json")
FAILURE_PATH = Path("/opt/ml/output/failure")


# =============================================================================
# LECTURA DE HYPERPARAMS
# =============================================================================

def cargar_hyperparams() -> dict:
    """Lee hyperparámetros pasados al training job.

    SageMaker los inyecta en /opt/ml/input/config/hyperparameters.json,
    como dict de strings (SageMaker convierte todo a string).
    Hacemos casting aquí donde sabemos los tipos esperados.
    """
    if not HYPERPARAMS_PATH.exists():
        logger.info("No hay hyperparameters.json, usando defaults")
        return {}

    with open(HYPERPARAMS_PATH) as f:
        raw = json.load(f)

    # Casting de tipos (SageMaker los pasa como string)
    hp = {}
    for k, v in raw.items():
        # Intentar int, luego float, luego dejar como string
        try:
            hp[k] = int(v)
            continue
        except (ValueError, TypeError):
            pass
        try:
            hp[k] = float(v)
            continue
        except (ValueError, TypeError):
            pass
        # Bool especial (SageMaker manda "true"/"false")
        if isinstance(v, str) and v.lower() in ("true", "false"):
            hp[k] = v.lower() == "true"
            continue
        hp[k] = v

    logger.info(f"Hyperparameters cargados: {hp}")
    return hp


# =============================================================================
# MAIN
# =============================================================================

def main() -> int:
    try:
        logger.info("=" * 60)
        logger.info("SageMaker Training Job — AirSense MX")
        logger.info("=" * 60)
        logger.info(f"Input data: {INPUT_DATA_DIR}")
        logger.info(f"Model out:  {MODEL_DIR}")
        logger.info(f"Output:     {OUTPUT_DIR}")

        # Asegurar directorios de salida
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # Cargar hyperparams desde SageMaker
        hp = cargar_hyperparams()
        horizonte = hp.get("horizonte", 1)

        # Localizar el archivo de Gold
        # SageMaker puede montar uno o varios archivos en el channel
        gold_files = list(INPUT_DATA_DIR.rglob("*.parquet"))
        if not gold_files:
            raise FileNotFoundError(
                f"No se encontró ningún .parquet en {INPUT_DATA_DIR}. "
                "Verifica el channel 'training' del Estimator."
            )
        logger.info(f"Encontrados {len(gold_files)} archivo(s) Gold: {gold_files}")

        # Importar después de validar el entorno
        import pandas as pd
        from training.train import entrenar_modelos
        from training.build_features import SplitTemporal

        # Leer Gold (concatenando si hay varios archivos)
        if len(gold_files) == 1:
            gold = pd.read_parquet(gold_files[0])
        else:
            gold = pd.concat([pd.read_parquet(f) for f in gold_files], ignore_index=True)
        logger.info(f"Gold cargado: {len(gold):,} filas, {len(gold.columns)} columnas")

        # Construir split desde hyperparams (con defaults razonables)
        split = SplitTemporal(
            train_inicio=hp.get("train_inicio", "2021-01-01"),
            train_fin=hp.get("train_fin", "2024-12-31"),
            val_inicio=hp.get("val_inicio", "2025-01-01"),
            val_fin=hp.get("val_fin", "2025-09-30"),
            test_inicio=hp.get("test_inicio", "2025-10-01"),
            test_fin=hp.get("test_fin", "2026-02-28"),
        )

        # Entrenar
        resultados = entrenar_modelos(
            gold=gold,
            output_dir=MODEL_DIR,    # ← /opt/ml/model/, SageMaker lo recoge automáticamente
            horizonte=horizonte,
            split=split,
        )

        # Resumen para los logs de SageMaker (CloudWatch)
        logger.info("=" * 60)
        logger.info("RESULTADOS DEL ENTRENAMIENTO")
        logger.info("=" * 60)
        resumen = {}
        for cont, res in resultados.items():
            resumen[cont] = {
                "test_mae": res.metricas_test.mae,
                "test_rmse": res.metricas_test.rmse,
                "baseline_mae": res.metricas_baseline_test.mae,
                "mejora_vs_baseline_pct": res.mejora_vs_baseline_pct,
                "paso_validacion": res.paso_validacion_baseline,
                "n_features": res.n_features,
            }
            logger.info(
                f"{cont}: MAE={res.metricas_test.mae:.2f}, "
                f"baseline={res.metricas_baseline_test.mae:.2f}, "
                f"mejora={res.mejora_vs_baseline_pct:+.1f}%, "
                f"paso_baseline={res.paso_validacion_baseline}"
            )

        # Guardar resumen en OUTPUT_DIR (lo recoge SageMaker como output adicional)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_DIR / "training_summary.json", "w") as f:
            json.dump(resumen, f, indent=2, default=str)

        logger.info("✓ Training completado exitosamente")
        return 0

    except Exception as e:
        # SageMaker marca el job como FAILED si existe /opt/ml/output/failure
        logger.error(f"Training falló: {e}")
        logger.error(traceback.format_exc())
        FAILURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(FAILURE_PATH, "w") as f:
            f.write(f"{e}\n\n{traceback.format_exc()}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
