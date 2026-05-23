"""Lógica de análisis de riesgo y calidad del aire para la UI.

Transforma los datos crudos de gold.predicciones_diarias en estructuras
listas para mostrar: resúmenes por zona, peor contaminante del día,
nivel de alerta general. No hace predicciones ni consulta AWS.
"""

from __future__ import annotations

import pandas as pd

from app.config import (
    CONTAMINANTE_NOMBRES,
    SEMAFORO_ETIQUETAS,
    SEMAFORO_ICONOS,
    SEMAFORO_ORDEN,
    ZONAS_NOMBRES,
)
from utils.logging import get_logger

logger = get_logger(__name__)


def obtener_semaforo_zona(
    df: pd.DataFrame,
    zone: str,
    contaminante: str | None = None,
) -> str:
    """Devuelve el semáforo más alto (peor) para una zona y fecha.

    Toma todas las filas del DataFrame (ya filtradas por fecha/horizonte
    si aplica) para la zona dada y devuelve el semáforo predominante.

    Args:
        df: DataFrame de predicciones ya filtrado por fecha.
        zone: Código de zona ('NO', 'NE', 'SE', 'SO', 'CE').
        contaminante: Si se especifica, filtra solo ese contaminante.

    Returns:
        Valor del semáforo ('verde', 'amarillo', 'naranja', 'rojo'),
        o 'verde' si no hay datos para la zona.
    """
    if df.empty or "zone" not in df.columns or "semaforo" not in df.columns:
        return "verde"

    subset = df[df["zone"] == zone]
    if contaminante:
        subset = subset[subset["contaminante"] == contaminante]

    if subset.empty:
        return "verde"

    # El peor semáforo tiene el orden más alto
    peor = subset["semaforo"].map(SEMAFORO_ORDEN).fillna(0).idxmax()
    return str(subset.loc[peor, "semaforo"])


def obtener_resumen_zona(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula el resumen de riesgo por zona para el horizonte dado.

    Args:
        df: DataFrame de predicciones filtrado por fecha y horizonte.

    Returns:
        DataFrame con columnas: zone, zone_nombre, semaforo, etiqueta,
        icono, prob_contingencia_max, contaminante_critico.
        Vacío si df está vacío.
    """
    if df.empty or "zone" not in df.columns:
        return pd.DataFrame()

    columnas_necesarias = {
        "zone",
        "semaforo",
        "probabilidad_contingencia",
        "contaminante",
    }
    if not columnas_necesarias.issubset(df.columns):
        return pd.DataFrame()

    registros = []
    for zone in df["zone"].unique():
        subset = df[df["zone"] == zone]
        semaforo = _peor_semaforo(subset["semaforo"])
        prob_max = float(subset["probabilidad_contingencia"].max())
        contaminante_critico = _contaminante_critico(subset)

        registros.append(
            {
                "zone": zone,
                "zone_nombre": ZONAS_NOMBRES.get(zone, zone),
                "semaforo": semaforo,
                "etiqueta": SEMAFORO_ETIQUETAS.get(semaforo, semaforo),
                "icono": SEMAFORO_ICONOS.get(semaforo, "⚪"),
                "prob_contingencia_max": round(prob_max * 100, 1),
                "contaminante_critico": CONTAMINANTE_NOMBRES.get(
                    contaminante_critico, contaminante_critico
                ),
            }
        )

    return pd.DataFrame(registros).sort_values(
        "semaforo",
        key=lambda s: s.map(SEMAFORO_ORDEN),
        ascending=False,
    )


def obtener_pronostico_estacion(
    df: pd.DataFrame,
    station_id: str,
    contaminante: str,
) -> pd.DataFrame:
    """Devuelve el pronóstico 1-7 días para una estación y contaminante.

    Args:
        df: DataFrame completo de predicciones (todos los horizontes).
        station_id: ID de la estación (ej. 'PED').
        contaminante: Código del contaminante ('O3', 'PM25', 'PM10').

    Returns:
        DataFrame con columnas horizonte_dias, fecha_objetivo, valor_predicho,
        valor_p10, valor_p90, probabilidad_contingencia, semaforo.
        Ordenado por horizonte ascendente.
    """
    if df.empty:
        return pd.DataFrame()

    mask = (df["station_id"] == station_id) & (df["contaminante"] == contaminante)
    subset = df[mask].copy()

    if subset.empty:
        return pd.DataFrame()

    cols = [
        "horizonte_dias",
        "fecha_objetivo",
        "valor_predicho",
        "valor_p10",
        "valor_p90",
        "probabilidad_contingencia",
        "semaforo",
    ]
    cols_presentes = [c for c in cols if c in subset.columns]
    return subset[cols_presentes].sort_values("horizonte_dias").reset_index(drop=True)


def hay_contingencia_activa(df: pd.DataFrame, umbral_prob: float = 0.5) -> bool:
    """Indica si alguna predicción supera el umbral de probabilidad.

    Args:
        df: DataFrame de predicciones filtrado por fecha/horizonte.
        umbral_prob: Probabilidad mínima para considerar contingencia activa.

    Returns:
        True si alguna predicción tiene probabilidad_contingencia > umbral.
    """
    if df.empty or "probabilidad_contingencia" not in df.columns:
        return False
    return bool((df["probabilidad_contingencia"] >= umbral_prob).any())


# ---------------------------------------------------------------------------
# Funciones auxiliares privadas
# ---------------------------------------------------------------------------


def _peor_semaforo(serie: pd.Series) -> str:
    """Devuelve el valor de semáforo con mayor nivel de riesgo."""
    if serie.empty:
        return "verde"
    orden = serie.map(SEMAFORO_ORDEN).fillna(0)
    return str(serie.iloc[orden.idxmax()])


def _contaminante_critico(subset: pd.DataFrame) -> str:
    """Identifica el contaminante con mayor probabilidad de contingencia."""
    if "probabilidad_contingencia" not in subset.columns:
        return ""
    idx = subset["probabilidad_contingencia"].idxmax()
    if "contaminante" not in subset.columns:
        return ""
    return str(subset.loc[idx, "contaminante"])
