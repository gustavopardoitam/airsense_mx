"""Entrenamiento de modelos LightGBM para predicción de calidad del aire.

Entrena un modelo de regresión por cada contaminante predecible (O3, PM2.5,
PM10) usando quantile regression para producir intervalos predictivos (p10,
p50, p90).

ARQUITECTURA
============
Para cada contaminante {O3, PM25, PM10}:
    Entrena 3 sub-modelos LightGBM con objective=quantile:
        - quantile=0.10 → predicción p10 (límite inferior del intervalo)
        - quantile=0.50 → predicción mediana (valor esperado robusto)
        - quantile=0.90 → predicción p90 (límite superior, usado para alertas)

    Salida: 3 .pkl + metadata.json en artifacts/models/{contaminante}/

JUSTIFICACIÓN DEL DISEÑO
========================
1. Quantile regression vs regresión clásica:
   - El producto necesita intervalos (probabilidad de cruzar umbral), no solo
     valor puntual. Quantile loss optimiza directamente para cuantiles.
   - LightGBM soporta nativamente quantile objective.

2. Tres modelos separados (uno por contaminante):
   - Más interpretable (feature importance específica por contaminante)
   - Hyperparams independientes
   - Fallas aisladas en producción

3. Multi-horizon en una sola corrida:
   - Entrenamos un solo modelo que recibe `horizon_dias` como feature.
   - El target es el valor del contaminante en t+horizonte.
   - LightGBM aprende que la incertidumbre crece con horizonte.

USO COMO MÓDULO
===============
    from training.train import entrenar_modelos
    resultados = entrenar_modelos(gold_df, output_dir="artifacts/models/")

USO COMO CLI
============
    python -m training.train \\
        --gold-path artifacts/gold/panel_diario.parquet \\
        --output-dir artifacts/models/ \\
        --horizontes 1 3 7
"""

from __future__ import annotations

import argparse
import json
import logging
import pickle
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from training.build_features import (
    DatasetEntrenamiento,
    SplitTemporal,
    TARGETS,
    construir_dataset,
)


logger = logging.getLogger(__name__)


# =============================================================================
# HYPERPARÁMETROS POR DEFECTO
# =============================================================================
# Valores iniciales razonables basados en literatura de pronóstico atmosférico
# y experimentación del equipo del parcial. NO están optimizados con Optuna.
# Se podrían tunear como iteración 2 si hay tiempo.

LGBM_PARAMS_DEFAULT = {
    "objective": "quantile",        # se sobrescribe con alpha por modelo
    "n_estimators": 500,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "max_depth": 6,
    "min_child_samples": 20,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.1,
    "reg_lambda": 0.1,
    "random_state": 42,
    "n_jobs": -1,
    "verbose": -1,
}

QUANTILES = [0.10, 0.50, 0.90]
QUANTILE_LABELS = {0.10: "p10", 0.50: "median", 0.90: "p90"}

# Mejora mínima esperada del modelo entrenado vs baseline naïve.
# Si el modelo no mejora al menos este % en MAE sobre el baseline, levantamos
# una bandera de calidad (no romemos el flujo, pero queda registrado).
# Idea original del stub de Toño: "modelo >= baseline + 10% relativo en MAE".
MEJORA_MINIMA_PCT = 10.0


# =============================================================================
# ESTRUCTURAS DE RESULTADOS
# =============================================================================

@dataclass
class MetricasModelo:
    """Métricas de regresión de un modelo en un split dado."""

    mae: float
    rmse: float
    bias: float        # mean(pred - true): positivo = sobreestima
    n_samples: int


@dataclass
class MetricasBaseline:
    """Métricas del baseline naïve (predicción = último valor observado).

    El baseline naïve predice y[t+h] = y[t]. Es la referencia mínima que
    cualquier modelo entrenado debe superar. Si el modelo no le gana al
    naïve por un margen razonable, no aporta valor sobre el dato crudo.
    """

    mae: float
    rmse: float
    n_samples: int


@dataclass
class ResultadoEntrenamiento:
    """Resultado completo del entrenamiento de los 3 modelos para un contaminante."""

    contaminante: str
    horizonte: int
    metricas_train: MetricasModelo
    metricas_val: MetricasModelo
    metricas_test: MetricasModelo
    metricas_baseline_test: MetricasBaseline
    mejora_vs_baseline_pct: float    # (1 - mae_modelo / mae_baseline) * 100
    paso_validacion_baseline: bool   # True si mejora_vs_baseline >= MEJORA_MINIMA_PCT
    feature_importance_top20: list[tuple[str, float]]
    paths_modelos: dict[str, str]   # quantile_label -> path al .pkl
    hyperparams: dict
    fecha_entrenamiento: str
    n_features: int
    periodo_train: tuple[str, str]
    periodo_val: tuple[str, str]
    periodo_test: tuple[str, str]


# =============================================================================
# UTILIDADES DE MÉTRICAS
# =============================================================================

def _calcular_metricas(y_true: pd.Series, y_pred: np.ndarray) -> MetricasModelo:
    """Calcula MAE, RMSE, bias para una predicción (sobre la mediana del modelo)."""
    diff = y_pred - y_true.values
    return MetricasModelo(
        mae=float(np.mean(np.abs(diff))),
        rmse=float(np.sqrt(np.mean(diff ** 2))),
        bias=float(np.mean(diff)),
        n_samples=int(len(y_true)),
    )


def _baseline_naive(
    dataset: DatasetEntrenamiento,
    split: str = "test",
) -> MetricasBaseline:
    """Calcula el baseline naïve: predicción = último valor observado del target.

    Para predecir el día t+h, este baseline simplemente predice el valor del
    target en el día t. Si el modelo no le gana a este predictor trivial,
    el modelo no aporta valor sobre los datos crudos.

    Implementación: la columna `{contaminante}_lag_1d` en X contiene exactamente
    el valor del día t cuando el target es del día t+1. Para horizonte > 1 no
    es perfecta pero sigue siendo una aproximación útil ("usar lo más reciente").

    Args:
        dataset: DatasetEntrenamiento completo con metadata.
        split: 'train', 'val' o 'test'.

    Returns:
        MetricasBaseline con MAE, RMSE, n_samples sobre el split indicado.
    """
    if split == "train":
        X, y = dataset.X_train, dataset.y_train
    elif split == "val":
        X, y = dataset.X_val, dataset.y_val
    elif split == "test":
        X, y = dataset.X_test, dataset.y_test
    else:
        raise ValueError(f"Split inválido: {split}")

    # El lag_1d del contaminante es la predicción naïve para horizonte 1
    col_baseline = f"{dataset.contaminante.lower()}_lag_1d"

    if col_baseline not in X.columns:
        logger.warning(
            f"No se encontró columna '{col_baseline}' para baseline naïve, "
            f"saltando cálculo"
        )
        return MetricasBaseline(mae=float("nan"), rmse=float("nan"), n_samples=0)

    y_pred = X[col_baseline].values
    # Filtrar nulls (filas donde lag_1d es NaN)
    mask = pd.notna(y_pred) & y.notna().values
    if mask.sum() == 0:
        return MetricasBaseline(mae=float("nan"), rmse=float("nan"), n_samples=0)

    y_pred_valid = y_pred[mask]
    y_true_valid = y.values[mask]
    diff = y_pred_valid - y_true_valid

    return MetricasBaseline(
        mae=float(np.mean(np.abs(diff))),
        rmse=float(np.sqrt(np.mean(diff ** 2))),
        n_samples=int(mask.sum()),
    )


# =============================================================================
# ENTRENAMIENTO DE UN MODELO (un contaminante × un horizonte)
# =============================================================================

def entrenar_un_modelo(
    dataset: DatasetEntrenamiento,
    output_dir: Path,
    hyperparams: Optional[dict] = None,
    early_stopping_rounds: int = 50,
) -> ResultadoEntrenamiento:
    """Entrena 3 sub-modelos quantile (p10, p50, p90) para un dataset dado.

    Args:
        dataset: DatasetEntrenamiento del módulo build_features.
        output_dir: carpeta donde guardar los .pkl y metadata.json.
        hyperparams: override de hyperparams (usa LGBM_PARAMS_DEFAULT si None).
        early_stopping_rounds: parar entrenamiento si no mejora val por N rondas.

    Returns:
        ResultadoEntrenamiento con métricas y paths a los modelos guardados.
    """
    # Lazy import para no requerir lightgbm en módulos que solo definen contratos
    import lightgbm as lgb

    hyperparams = {**LGBM_PARAMS_DEFAULT, **(hyperparams or {})}
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        f"Entrenando {dataset.contaminante} horizonte {dataset.horizonte}d: "
        f"train={len(dataset.X_train):,}, val={len(dataset.X_val):,}, "
        f"test={len(dataset.X_test):,}"
    )

    paths_modelos = {}
    predicciones_val = {}    # {quantile: predicciones}
    predicciones_test = {}
    predicciones_train = {}

    for q in QUANTILES:
        params = {**hyperparams, "objective": "quantile", "alpha": q}
        label = QUANTILE_LABELS[q]

        # LightGBM admite categóricas como columnas con dtype category
        model = lgb.LGBMRegressor(**params)
        model.fit(
            dataset.X_train,
            dataset.y_train,
            eval_set=[(dataset.X_val, dataset.y_val)],
            callbacks=[
                lgb.early_stopping(stopping_rounds=early_stopping_rounds, verbose=False),
                lgb.log_evaluation(period=0),  # silencia el log de cada ronda
            ],
            categorical_feature=dataset.categoricas,
        )

        # Guardar modelo
        path_modelo = output_dir / f"model_{dataset.contaminante.lower()}_{label}.pkl"
        with open(path_modelo, "wb") as f:
            pickle.dump(model, f)
        paths_modelos[label] = str(path_modelo)

        # Predicciones para métricas
        predicciones_train[label] = model.predict(dataset.X_train)
        predicciones_val[label] = model.predict(dataset.X_val)
        predicciones_test[label] = model.predict(dataset.X_test)

        logger.info(
            f"  {label} (alpha={q}) - "
            f"best iter: {model.best_iteration_}, "
            f"val MAE: {np.mean(np.abs(predicciones_val[label] - dataset.y_val.values)):.2f}"
        )

    # Métricas se calculan sobre el modelo mediana (p50)
    metricas_train = _calcular_metricas(dataset.y_train, predicciones_train["median"])
    metricas_val = _calcular_metricas(dataset.y_val, predicciones_val["median"])
    metricas_test = _calcular_metricas(dataset.y_test, predicciones_test["median"])

    # Baseline naïve: "predicción = último valor observado".
    # Si el modelo no le gana al baseline por MEJORA_MINIMA_PCT, levantamos
    # bandera (no rompemos el entrenamiento, pero queda registrado).
    metricas_baseline_test = _baseline_naive(dataset, split="test")
    if metricas_baseline_test.n_samples > 0 and metricas_baseline_test.mae > 0:
        mejora_pct = (
            (metricas_baseline_test.mae - metricas_test.mae)
            / metricas_baseline_test.mae * 100
        )
    else:
        mejora_pct = float("nan")
    paso_validacion = (
        not pd.isna(mejora_pct) and mejora_pct >= MEJORA_MINIMA_PCT
    )

    if not paso_validacion and not pd.isna(mejora_pct):
        logger.warning(
            f"⚠️  {dataset.contaminante} h={dataset.horizonte}d: "
            f"el modelo mejora solo {mejora_pct:.1f}% sobre baseline naïve "
            f"(esperado >= {MEJORA_MINIMA_PCT}%). "
            f"Modelo MAE={metricas_test.mae:.2f}, baseline MAE={metricas_baseline_test.mae:.2f}"
        )
    elif paso_validacion:
        logger.info(
            f"✓ {dataset.contaminante} h={dataset.horizonte}d: "
            f"modelo mejora {mejora_pct:.1f}% sobre baseline naïve"
        )

    # Feature importance del modelo mediana (el "principal")
    with open(paths_modelos["median"], "rb") as f:
        model_median = pickle.load(f)
    fi = pd.DataFrame({
        "feature": dataset.features,
        "importance": model_median.feature_importances_,
    }).sort_values("importance", ascending=False)
    top_features = [(row.feature, float(row.importance)) for row in fi.head(20).itertuples()]

    resultado = ResultadoEntrenamiento(
        contaminante=dataset.contaminante,
        horizonte=dataset.horizonte,
        metricas_train=metricas_train,
        metricas_val=metricas_val,
        metricas_test=metricas_test,
        metricas_baseline_test=metricas_baseline_test,
        mejora_vs_baseline_pct=float(mejora_pct) if not pd.isna(mejora_pct) else float("nan"),
        paso_validacion_baseline=paso_validacion,
        feature_importance_top20=top_features,
        paths_modelos=paths_modelos,
        hyperparams=hyperparams,
        fecha_entrenamiento=datetime.now().isoformat(),
        n_features=len(dataset.features),
        periodo_train=(str(dataset.train_meta["fecha"].min()),
                       str(dataset.train_meta["fecha"].max())),
        periodo_val=(str(dataset.val_meta["fecha"].min()),
                     str(dataset.val_meta["fecha"].max())),
        periodo_test=(str(dataset.test_meta["fecha"].min()),
                      str(dataset.test_meta["fecha"].max())),
    )

    # Persistir metadata
    metadata = {
        "contaminante": resultado.contaminante,
        "horizonte": resultado.horizonte,
        "fecha_entrenamiento": resultado.fecha_entrenamiento,
        "n_features": resultado.n_features,
        "features": dataset.features,
        "categoricas": dataset.categoricas,
        "hyperparams": resultado.hyperparams,
        "paths_modelos": resultado.paths_modelos,
        "periodo_train": resultado.periodo_train,
        "periodo_val": resultado.periodo_val,
        "periodo_test": resultado.periodo_test,
        "metricas": {
            "train": asdict(resultado.metricas_train),
            "val": asdict(resultado.metricas_val),
            "test": asdict(resultado.metricas_test),
            "baseline_naive_test": asdict(resultado.metricas_baseline_test),
        },
        "validacion_baseline": {
            "mejora_vs_baseline_pct": resultado.mejora_vs_baseline_pct,
            "mejora_minima_esperada_pct": MEJORA_MINIMA_PCT,
            "paso_validacion": resultado.paso_validacion_baseline,
        },
        "feature_importance_top20": resultado.feature_importance_top20,
    }
    with open(output_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2, default=str)

    logger.info(
        f"✓ {dataset.contaminante} h={dataset.horizonte}d - "
        f"val MAE: {metricas_val.mae:.2f}, test MAE: {metricas_test.mae:.2f}, "
        f"baseline naïve MAE: {metricas_baseline_test.mae:.2f}, "
        f"mejora: {mejora_pct:+.1f}%"
    )

    return resultado


# =============================================================================
# PIPELINE PRINCIPAL: ENTRENAR LOS 3 CONTAMINANTES
# =============================================================================

def entrenar_modelos(
    gold: pd.DataFrame,
    output_dir: Path | str = "artifacts/models",
    horizonte: int = 1,
    split: Optional[SplitTemporal] = None,
    hyperparams: Optional[dict] = None,
) -> dict[str, ResultadoEntrenamiento]:
    """Entrena los 3 modelos (O3, PM25, PM10) para un horizonte dado.

    Args:
        gold: DataFrame del panel diario Gold.
        output_dir: directorio raíz de salida (creará subcarpetas por contaminante).
        horizonte: días hacia adelante a predecir (1, 3 o 7).
        split: configuración de split temporal.
        hyperparams: override de hyperparams base.

    Returns:
        Dict {contaminante: ResultadoEntrenamiento}.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    resultados = {}
    for contaminante in TARGETS.keys():
        sub_dir = output_dir / contaminante.lower() / f"h{horizonte}"
        try:
            dataset = construir_dataset(
                gold=gold,
                contaminante=contaminante,
                horizonte=horizonte,
                split=split,
            )

            if len(dataset.X_train) < 100:
                logger.warning(
                    f"Muy pocos datos para entrenar {contaminante} h={horizonte}d "
                    f"({len(dataset.X_train)} filas). Skipping."
                )
                continue

            resultados[contaminante] = entrenar_un_modelo(
                dataset=dataset,
                output_dir=sub_dir,
                hyperparams=hyperparams,
            )
        except Exception as e:
            logger.error(f"Error entrenando {contaminante} h={horizonte}d: {e}")
            raise

    return resultados


# =============================================================================
# WRAPPER COMPATIBLE CON STUB ORIGINAL
# =============================================================================

def train_pipeline(
    input_parquet: Path,
    output_model: Path,
    cfg: Optional[object] = None,
    split: Optional[SplitTemporal] = None,
) -> dict:
    """Wrapper compatible con la firma del stub original del proyecto.

    Mantiene retrocompatibilidad si algún script externo importa esta función.
    Internamente delega a entrenar_modelos() que es la implementación real.

    Diferencias con el stub:
        - output_model se interpreta como DIRECTORIO raíz (porque generamos
          3 modelos × 3 quantiles = 9 archivos, no uno solo).
        - El dict de retorno resume los 3 contaminantes en lugar de uno.

    Args:
        input_parquet: ruta al Gold parquet de entrada.
        output_model: directorio raíz donde guardar los modelos.
        cfg: ContaminantConfig (opcional, no usado actualmente).
        split: SplitTemporal opcional. Si None, usa defaults del módulo
               (2021-01-01..2026-02-28).

    Returns:
        Dict con resumen agregado:
            {
                "models_dir": str(output_model),
                "n_models_trained": int,
                "summary": {
                    "O3": {"mae_test": ..., "mae_baseline": ..., "mejora_pct": ...},
                    "PM25": {...},
                    "PM10": {...},
                },
                "all_passed_baseline": bool,
            }
    """
    input_parquet = Path(input_parquet)
    output_model = Path(output_model)

    if not input_parquet.exists():
        raise FileNotFoundError(
            f"No existe el dataset preparado: {input_parquet}. "
            "Ejecuta primero el ETL Silver→Gold."
        )

    logger.info(f"train_pipeline: leyendo {input_parquet}")
    gold = pd.read_parquet(input_parquet)

    resultados = entrenar_modelos(
        gold=gold,
        output_dir=output_model,
        horizonte=1,
        split=split,
    )

    summary = {
        cont: {
            "mae_test": res.metricas_test.mae,
            "rmse_test": res.metricas_test.rmse,
            "mae_baseline_naive": res.metricas_baseline_test.mae,
            "mejora_vs_baseline_pct": res.mejora_vs_baseline_pct,
            "paso_validacion_baseline": res.paso_validacion_baseline,
            "n_features": res.n_features,
        }
        for cont, res in resultados.items()
    }

    return {
        "models_dir": str(output_model),
        "n_models_trained": len(resultados),
        "summary": summary,
        "all_passed_baseline": all(
            r.paso_validacion_baseline for r in resultados.values()
        ),
    }


# =============================================================================
# CLI
# =============================================================================

def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _leer_gold(path: str) -> pd.DataFrame:
    """Lee Gold desde S3 o local."""
    if path.startswith("s3://"):
        import awswrangler as wr
        logger.info(f"Leyendo Gold desde S3: {path}")
        return wr.s3.read_parquet(path)
    logger.info(f"Leyendo Gold desde local: {path}")
    p = Path(path)
    if p.is_dir():
        return pd.read_parquet(p)
    return pd.read_parquet(p)


def main() -> None:
    _setup_logging()

    parser = argparse.ArgumentParser(
        description="Entrenamiento de modelos LightGBM AirSense MX"
    )
    parser.add_argument("--gold-path", required=True, help="Path a Gold (S3 o local)")
    parser.add_argument("--output-dir", default="artifacts/models",
                        help="Directorio raíz de salida")
    parser.add_argument("--horizontes", type=int, nargs="+", default=[1],
                        help="Horizontes de predicción a entrenar (default: solo 1)")
    args = parser.parse_args()

    gold = _leer_gold(args.gold_path)
    logger.info(f"Gold cargado: {len(gold):,} filas, {len(gold.columns)} columnas")

    for h in args.horizontes:
        logger.info(f"\n{'='*60}\n=== HORIZONTE {h} DÍA(S) ===\n{'='*60}")
        resultados = entrenar_modelos(
            gold=gold,
            output_dir=args.output_dir,
            horizonte=h,
        )
        for cont, res in resultados.items():
            logger.info(
                f"{cont} h={h}d: "
                f"train MAE={res.metricas_train.mae:.2f}, "
                f"val MAE={res.metricas_val.mae:.2f}, "
                f"test MAE={res.metricas_test.mae:.2f}"
            )

    logger.info("\n✓ Entrenamiento completado")


if __name__ == "__main__":
    main()
