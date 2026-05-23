"""Inferencia: produce gold.predicciones_diarias desde modelos entrenados.

Es el puente entre los modelos LightGBM y la tabla que consume Streamlit
vía Athena. Toma los .pkl entrenados por training/ y features de Gold,
produce una tabla con el schema exacto del contrato de datos v1.0/1.1.

USO COMO MÓDULO
===============
    from inference.predict import construir_predicciones

    predicciones = construir_predicciones(
        gold=gold_df,
        models_dir="artifacts/models/",
        modo="batch_eval",  # o "produccion"
    )

USO COMO CLI
============
    python -m inference.predict \\
        --gold-path artifacts/gold/panel_diario.parquet \\
        --models-dir artifacts/models/ \\
        --output artifacts/predicciones/ \\
        --fecha-inicio 2025-10-01 --fecha-fin 2026-02-28

DECISIONES DE DISEÑO
====================
- Las 3 predicciones (p10, p50, p90) salen de los 3 sub-modelos quantile
  entrenados por contaminante.
- probabilidad_contingencia se deriva asumiendo distribución log-normal
  ajustada a los cuantiles. Fallback a heurística si el ajuste falla.
- valor_predicho = p50 (mediana, no media — más robusto a outliers).
- semaforo se calcula usando calcular_semaforo() del config (única autoridad).
- modelo_version se extrae del metadata.json del entrenamiento.
"""

from __future__ import annotations

import argparse
import json
import logging
import pickle
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

from config import (
    UMBRALES_PCAA,
    CONTAMINANTES_PREDECIBLES,
    calcular_semaforo,
)


logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTES
# =============================================================================

MODELO_VERSION = "lgbm_v1.0"
QUANTILE_LABELS = ["p10", "median", "p90"]

# Rangos físicos válidos para clipping (concentraciones no pueden ser negativas
# y tienen un techo razonable basado en máximos históricos).
# Idea original del stub: aplicar np.clip para validez física.
# El piso es 0 (concentraciones no-negativas). El techo es 3× el máximo
# histórico observado en CDMX para detectar predicciones absurdas sin
# truncarlas en el caso de eventos extremos legítimos.
RANGOS_FISICOS = {
    "O3":   (0.0, 600.0),    # max histórico CDMX ~400 ppb (años 90)
    "NO2":  (0.0, 500.0),
    "SO2":  (0.0, 500.0),
    "PM25": (0.0, 500.0),    # max documentado ~300 µg/m³
    "PM10": (0.0, 800.0),    # tormentas de polvo pueden empujar fuerte
    "CO":   (0.0,  50.0),
}


# =============================================================================
# CARGA DE MODELOS
# =============================================================================

@dataclass
class ModeloContaminante:
    """Empaqueta los 3 sub-modelos quantile + metadata para un contaminante."""

    contaminante: str
    horizonte: int
    model_p10: object   # LGBMRegressor entrenado
    model_p50: object
    model_p90: object
    features: list[str]
    categoricas: list[str]
    metadata: dict


def cargar_modelos(
    models_dir: Path | str,
    contaminantes: Optional[list[str]] = None,
    horizonte: int = 1,
) -> dict[str, ModeloContaminante]:
    """Carga los modelos entrenados desde disco.

    Args:
        models_dir: directorio raíz donde están las carpetas por contaminante.
        contaminantes: lista a cargar (default: O3, PM25, PM10).
        horizonte: subcarpeta hN (default 1).

    Returns:
        Dict {contaminante: ModeloContaminante}.

    Estructura esperada en disco:
        models_dir/
          o3/h1/
            model_o3_p10.pkl
            model_o3_median.pkl
            model_o3_p90.pkl
            metadata.json
          pm25/h1/...
          pm10/h1/...
    """
    models_dir = Path(models_dir)
    contaminantes = contaminantes or CONTAMINANTES_PREDECIBLES

    modelos = {}
    for cont in contaminantes:
        sub_dir = models_dir / cont.lower() / f"h{horizonte}"
        if not sub_dir.exists():
            logger.warning(f"No existe directorio de modelo: {sub_dir}, skipping {cont}")
            continue

        try:
            metadata_path = sub_dir / "metadata.json"
            with open(metadata_path) as f:
                metadata = json.load(f)

            cont_lower = cont.lower()
            with open(sub_dir / f"model_{cont_lower}_p10.pkl", "rb") as f:
                m_p10 = pickle.load(f)
            with open(sub_dir / f"model_{cont_lower}_median.pkl", "rb") as f:
                m_p50 = pickle.load(f)
            with open(sub_dir / f"model_{cont_lower}_p90.pkl", "rb") as f:
                m_p90 = pickle.load(f)

            modelos[cont] = ModeloContaminante(
                contaminante=cont,
                horizonte=horizonte,
                model_p10=m_p10,
                model_p50=m_p50,
                model_p90=m_p90,
                features=metadata["features"],
                categoricas=metadata.get("categoricas", []),
                metadata=metadata,
            )
            logger.info(f"✓ Modelo {cont} h={horizonte}d cargado ({len(m_p50.feature_name_)} features)")
        except Exception as e:
            logger.error(f"Error cargando modelo {cont}: {e}")
            raise

    if not modelos:
        raise RuntimeError(f"No se cargó ningún modelo desde {models_dir}")

    return modelos


# =============================================================================
# DERIVACIÓN DE PROBABILIDAD
# =============================================================================

def derivar_probabilidad(
    p10: float,
    p50: float,
    p90: float,
    umbral: float,
) -> float:
    """Estima P(valor >= umbral) a partir de los cuantiles p10, p50, p90.

    Método principal: ajusta una distribución log-normal a los 3 cuantiles
    y evalúa la CDF en el umbral. Justificación: las concentraciones de
    contaminantes son no-negativas y suelen mostrar asimetría positiva
    (cola larga hacia valores altos), patrón natural de la log-normal.

    Fallback: si el ajuste falla (cuantiles inconsistentes o iguales),
    usar heurística simple basada en posición relativa al umbral.

    Args:
        p10, p50, p90: cuantiles predichos por los 3 sub-modelos.
        umbral: umbral PCAA de contingencia para el contaminante.

    Returns:
        Probabilidad en [0, 1].
    """
    # Validaciones básicas
    if any(pd.isna(x) for x in (p10, p50, p90, umbral)) or umbral <= 0:
        return float("nan")

    # Cuantiles deben ser monotónicos crecientes
    if not (p10 <= p50 <= p90):
        logger.debug(f"Cuantiles no-monotónicos: p10={p10}, p50={p50}, p90={p90}")
        return _probabilidad_heuristica(p50, p90, umbral)

    # Si los valores son muy pequeños o negativos, usar heurística
    if p10 <= 0:
        # Concentración no puede ser negativa; el modelo extrapoló mal
        if p90 < umbral:
            return 0.05
        if p50 >= umbral:
            return 0.95
        return _probabilidad_heuristica(p50, p90, umbral)

    # Ajuste log-normal: tomamos logaritmos de los cuantiles
    try:
        log_p10 = np.log(max(p10, 1e-6))
        log_p50 = np.log(max(p50, 1e-6))
        log_p90 = np.log(max(p90, 1e-6))

        # En log-normal, log(valor) ~ Normal(mu, sigma).
        # log_p50 = mu (mediana coincide con media en escala log)
        # log_p90 - log_p10 ~ 2*1.2816*sigma  (Φ⁻¹(0.9) - Φ⁻¹(0.1) ≈ 2.563)
        mu = log_p50
        sigma = (log_p90 - log_p10) / 2.5631

        if sigma <= 0:
            # Modelo no diferenció entre cuantiles, usar heurística
            return _probabilidad_heuristica(p50, p90, umbral)

        # P(valor >= umbral) = 1 - Φ((log(umbral) - mu) / sigma)
        z = (np.log(umbral) - mu) / sigma
        prob = 1.0 - stats.norm.cdf(z)
        return float(np.clip(prob, 0.0, 1.0))
    except (ValueError, FloatingPointError) as e:
        logger.debug(f"Fallback heurística (error: {e})")
        return _probabilidad_heuristica(p50, p90, umbral)


def _probabilidad_heuristica(p50: float, p90: float, umbral: float) -> float:
    """Heurística simple cuando el ajuste log-normal no funciona."""
    if p90 < umbral:
        return 0.05            # muy improbable
    if p50 >= umbral:
        return 0.95            # muy probable
    # El umbral cae entre p50 y p90: interpolación lineal
    rango = p90 - p50
    if rango <= 0:
        return 0.5
    posicion = (umbral - p50) / rango
    # p50 = prob 0.5, p90 = prob 0.1 → invertir
    return float(np.clip(0.5 - 0.4 * posicion, 0.1, 0.9))


# =============================================================================
# PREDICCIÓN SOBRE UN DATASET
# =============================================================================

def predecir_dataset(
    X: pd.DataFrame,
    modelo: ModeloContaminante,
) -> pd.DataFrame:
    """Predice p10, p50, p90 para un DataFrame de features.

    Args:
        X: DataFrame con las features. Debe contener al menos las columnas
           usadas durante el entrenamiento (modelo.features).
        modelo: ModeloContaminante con los 3 sub-modelos quantile.

    Returns:
        DataFrame con columnas: valor_p10, valor_predicho, valor_p90
        (mismo índice que X).
    """
    # Verificar features
    faltantes = [c for c in modelo.features if c not in X.columns]
    if faltantes:
        raise ValueError(
            f"Features faltantes para predecir {modelo.contaminante}: {faltantes}"
        )

    # Reordenar columnas según el entrenamiento y convertir categóricas
    X_eval = X[modelo.features].copy()
    for col in modelo.categoricas:
        if col in X_eval.columns:
            X_eval[col] = X_eval[col].astype("category")

    p10 = modelo.model_p10.predict(X_eval)
    p50 = modelo.model_p50.predict(X_eval)
    p90 = modelo.model_p90.predict(X_eval)

    return pd.DataFrame({
        "valor_p10": p10,
        "valor_predicho": p50,
        "valor_p90": p90,
    }, index=X.index)


# =============================================================================
# PIPELINE PRINCIPAL: GOLD → PREDICCIONES_DIARIAS
# =============================================================================

def construir_predicciones(
    gold: pd.DataFrame,
    models_dir: Path | str,
    horizonte: int = 1,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    modelo_version: str = MODELO_VERSION,
) -> pd.DataFrame:
    """Pipeline completo: Gold + modelos → gold.predicciones_diarias.

    Para cada (fecha, station_id) en Gold dentro del rango especificado,
    genera una fila por cada contaminante predecible con la predicción
    para el día (fecha + horizonte) en formato del contrato.

    Args:
        gold: DataFrame del panel diario Gold.
        models_dir: directorio raíz con los modelos entrenados.
        horizonte: días hacia adelante (debe coincidir con el horizonte
                   con el que se entrenaron los modelos).
        fecha_inicio: filtro inclusivo sobre `fecha_prediccion` (cuándo
                      se ejecutó el modelo).
        fecha_fin: filtro inclusivo sobre `fecha_prediccion`.
        modelo_version: identificador del modelo para auditoría.

    Returns:
        DataFrame con el schema exacto de gold.predicciones_diarias.
    """
    modelos = cargar_modelos(models_dir, horizonte=horizonte)

    df = gold.copy()
    df["fecha"] = pd.to_datetime(df["fecha"])

    if fecha_inicio:
        df = df[df["fecha"] >= pd.Timestamp(fecha_inicio)]
    if fecha_fin:
        df = df[df["fecha"] <= pd.Timestamp(fecha_fin)]

    if df.empty:
        logger.warning("Sin datos en el rango especificado")
        return pd.DataFrame()

    logger.info(
        f"Generando predicciones: {len(df):,} filas Gold × "
        f"{len(modelos)} contaminantes × horizonte {horizonte}d"
    )

    predicciones_por_cont = []
    for cont, modelo in modelos.items():
        # Predecir
        preds = predecir_dataset(df, modelo)

        # Aplicar clipping a rango físico válido (concentraciones no-negativas
        # y con techo basado en máximos históricos para detectar errores extremos)
        if cont in RANGOS_FISICOS:
            piso, techo = RANGOS_FISICOS[cont]
            n_clipeadas = (
                (preds["valor_predicho"] < piso)
                | (preds["valor_predicho"] > techo)
            ).sum()
            if n_clipeadas > 0:
                logger.warning(
                    f"{cont}: {n_clipeadas} predicciones fuera de rango físico "
                    f"[{piso}, {techo}] fueron clipeadas"
                )
            preds["valor_p10"] = preds["valor_p10"].clip(piso, techo)
            preds["valor_predicho"] = preds["valor_predicho"].clip(piso, techo)
            preds["valor_p90"] = preds["valor_p90"].clip(piso, techo)

        # Armar fila de output según contrato
        umbral = UMBRALES_PCAA[cont]["valor"]
        out = pd.DataFrame({
            "fecha_prediccion": df["fecha"].values,
            "fecha_objetivo": (df["fecha"] + pd.Timedelta(days=horizonte)).values,
            "horizonte_dias": horizonte,
            "station_id": df["station_id"].values,
            "zone": df["zone"].values,
            "contaminante": cont,
            "valor_predicho": preds["valor_predicho"].values,
            "valor_p10": preds["valor_p10"].values,
            "valor_p90": preds["valor_p90"].values,
            "umbral_contingencia": umbral,
        })

        # probabilidad_contingencia y semaforo (vectorizado por row)
        out["probabilidad_contingencia"] = out.apply(
            lambda r: derivar_probabilidad(
                r["valor_p10"], r["valor_predicho"], r["valor_p90"], umbral
            ),
            axis=1,
        )
        out["semaforo"] = out["valor_predicho"].apply(
            lambda v: calcular_semaforo(v, umbral)
        )

        out["modelo_version"] = modelo_version
        out["ingestion_timestamp"] = pd.Timestamp.now()

        predicciones_por_cont.append(out)
        logger.info(
            f"  {cont}: {len(out):,} predicciones, "
            f"prob_cont media={out['probabilidad_contingencia'].mean():.3f}, "
            f"semáforo rojo: {(out['semaforo']=='rojo').sum()}"
        )

    resultado = pd.concat(predicciones_por_cont, ignore_index=True)
    resultado = resultado.sort_values(
        ["fecha_objetivo", "station_id", "contaminante"]
    ).reset_index(drop=True)

    logger.info(
        f"✓ Total predicciones generadas: {len(resultado):,} "
        f"({resultado['station_id'].nunique()} estaciones, "
        f"{resultado['fecha_objetivo'].nunique()} días objetivo)"
    )

    return resultado


# =============================================================================
# ESCRITURA AL DATA LAKE
# =============================================================================

def escribir_predicciones(df: pd.DataFrame, path: str) -> None:
    """Escribe predicciones a S3 (particionado) o local."""
    df = df.copy()
    df["year"] = pd.to_datetime(df["fecha_objetivo"]).dt.year
    df["month"] = pd.to_datetime(df["fecha_objetivo"]).dt.month

    if path.startswith("s3://"):
        import awswrangler as wr
        logger.info(f"Escribiendo predicciones a S3: {path}")
        wr.s3.to_parquet(
            df=df,
            path=path,
            dataset=True,
            partition_cols=["year", "month"],
            compression="snappy",
            mode="overwrite_partitions",
        )
    else:
        out_dir = Path(path)
        out_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Escribiendo predicciones local: {out_dir}")
        df.drop(columns=["year", "month"]).to_parquet(
            out_dir / "predicciones_diarias.parquet",
            compression="snappy",
            index=False,
        )


# =============================================================================
# WRAPPER COMPATIBLE CON STUB ORIGINAL
# =============================================================================

def predict(
    model_path: Path | str,
    gold_path: Optional[Path | str] = None,
    horizonte: int = 1,
) -> dict:
    """Wrapper compatible con la firma del stub original del proyecto.

    Mantiene retrocompatibilidad. Internamente delega a construir_predicciones()
    que es la implementación real.

    Diferencias con el stub:
        - model_path se interpreta como el DIRECTORIO raíz de modelos (donde
          viven o3/, pm25/, pm10/), no un solo .pkl, porque tenemos 9 modelos.
        - El retorno es un dict con DataFrame en 'predictions' en lugar de
          un dict plano (mantenemos compatibilidad de schema).

    Args:
        model_path: directorio raíz con los modelos entrenados.
        gold_path: path al Gold que contiene los features. Si None, intenta
                   leerlo de la ubicación estándar del proyecto.
        horizonte: días de horizonte a predecir.

    Returns:
        Dict con:
            {
                "predictions": pd.DataFrame con schema gold.predicciones_diarias,
                "n_predictions": int,
                "models_dir": str,
                "horizonte_dias": int,
            }
    """
    if gold_path is None:
        raise ValueError(
            "gold_path es requerido. Pásalo explícitamente o usa "
            "construir_predicciones() para más control."
        )

    gold = _leer_gold(str(gold_path))
    predicciones = construir_predicciones(
        gold=gold,
        models_dir=model_path,
        horizonte=horizonte,
    )

    return {
        "predictions": predicciones,
        "n_predictions": len(predicciones),
        "models_dir": str(model_path),
        "horizonte_dias": horizonte,
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
    if path.startswith("s3://"):
        import awswrangler as wr
        return wr.s3.read_parquet(path)
    p = Path(path)
    if p.is_dir():
        return pd.read_parquet(p)
    return pd.read_parquet(p)


def main() -> None:
    _setup_logging()

    parser = argparse.ArgumentParser(
        description="Inferencia AirSense MX: produce gold.predicciones_diarias"
    )
    parser.add_argument("--gold-path", required=True, help="Path a Gold (S3 o local)")
    parser.add_argument("--models-dir", required=True, help="Directorio con modelos entrenados")
    parser.add_argument("--output", required=True, help="Path de salida (S3 o local)")
    parser.add_argument("--horizonte", type=int, default=1, help="Horizonte de predicción")
    parser.add_argument("--fecha-inicio", default=None,
                        help="Filtro fecha inicio (sobre fecha_prediccion), YYYY-MM-DD")
    parser.add_argument("--fecha-fin", default=None,
                        help="Filtro fecha fin (sobre fecha_prediccion), YYYY-MM-DD")
    parser.add_argument("--modelo-version", default=MODELO_VERSION,
                        help="Identificador del modelo")
    args = parser.parse_args()

    gold = _leer_gold(args.gold_path)
    logger.info(f"Gold cargado: {len(gold):,} filas")

    predicciones = construir_predicciones(
        gold=gold,
        models_dir=args.models_dir,
        horizonte=args.horizonte,
        fecha_inicio=args.fecha_inicio,
        fecha_fin=args.fecha_fin,
        modelo_version=args.modelo_version,
    )

    escribir_predicciones(predicciones, args.output)
    logger.info("✓ Inferencia completada")


if __name__ == "__main__":
    main()
