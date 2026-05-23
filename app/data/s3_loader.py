"""Carga de datos Gold desde S3 con caché para la app Streamlit.

Responsabilidad única: leer `gold.predicciones_diarias` desde S3 y
exponer DataFrames listos para consumo por las páginas. No contiene
lógica de negocio ni transformaciones.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.config import CACHE_TTL_SEGUNDOS, GOLD_S3_PATH
from utils.logging import get_logger

logger = get_logger(__name__)


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS)
def cargar_predicciones() -> pd.DataFrame:
    """Carga la tabla Gold completa desde S3.

    Usa awswrangler para leer todos los Parquets particionados por
    year/month. Retorna DataFrame vacío si S3 no está disponible o
    la tabla aún no existe, permitiendo que la UI muestre un mensaje
    amigable sin lanzar excepciones.

    Returns:
        DataFrame con columnas del contrato gold.predicciones_diarias,
        o DataFrame vacío si los datos no están disponibles.
    """
    try:
        import awswrangler as wr  # importación diferida para no bloquear la app

        df = wr.s3.read_parquet(path=GOLD_S3_PATH, dataset=True)
        logger.info(
            "Predicciones Gold cargadas desde S3",
            extra={"rows": len(df), "path": GOLD_S3_PATH},
        )
        return df
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "No se pudo cargar Gold desde S3",
            extra={"error": str(exc), "path": GOLD_S3_PATH},
        )
        return pd.DataFrame()


def filtrar_por_fecha_prediccion(
    df: pd.DataFrame,
    fecha: str,
) -> pd.DataFrame:
    """Filtra filas donde fecha_prediccion == fecha.

    Args:
        df: DataFrame completo de predicciones.
        fecha: Fecha en formato 'YYYY-MM-DD'.

    Returns:
        Subconjunto filtrado, o df vacío si columna no existe.
    """
    if df.empty or "fecha_prediccion" not in df.columns:
        return pd.DataFrame()
    return df[df["fecha_prediccion"].astype(str) == fecha].copy()


def filtrar_por_horizonte(
    df: pd.DataFrame,
    horizonte: int,
) -> pd.DataFrame:
    """Filtra filas por horizonte_dias.

    Args:
        df: DataFrame de predicciones.
        horizonte: Número de días hacia adelante (1-7).

    Returns:
        Subconjunto filtrado.
    """
    if df.empty or "horizonte_dias" not in df.columns:
        return pd.DataFrame()
    return df[df["horizonte_dias"] == horizonte].copy()


def obtener_fecha_prediccion_mas_reciente(df: pd.DataFrame) -> str | None:
    """Devuelve la fecha_prediccion más reciente disponible.

    Args:
        df: DataFrame completo de predicciones.

    Returns:
        Fecha como string 'YYYY-MM-DD', o None si df está vacío.
    """
    if df.empty or "fecha_prediccion" not in df.columns:
        return None
    return str(df["fecha_prediccion"].max())
