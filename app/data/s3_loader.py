"""Carga de datos Gold desde S3 con caché para la app Streamlit.

Responsabilidad única: leer las tablas Gold y dimensiones desde S3 y
exponer DataFrames listos para consumo por las páginas. No contiene
lógica de negocio ni transformaciones de dominio.

Compatibilidad:
    - Ejecución local: credenciales vía ~/.aws/credentials o variables de entorno.
    - SageMaker: credenciales vía IAM Role del execution role.
    - ECS/Fargate: credenciales vía IAM Task Role (sin configuración adicional).
"""

from __future__ import annotations

import awswrangler as wr
import pandas as pd
import streamlit as st

from app.config import (
    CACHE_TTL_SEGUNDOS,
    DIM_ESTACIONES_S3_PATH,
    DIM_ESTACIONES_SCHEMA_MINIMO,
    GOLD_PREDICCIONES_SCHEMA_MINIMO,
    GOLD_S3_PATH,
    PANEL_DIARIO_S3_PATH,
)
from utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# VALIDACIÓN DE SCHEMA
# =============================================================================


def _validar_schema_minimo(df: pd.DataFrame, columnas: list[str], nombre: str) -> bool:
    """Verifica que el DataFrame tenga las columnas mínimas requeridas.

    Args:
        df: DataFrame a validar.
        columnas: Lista de columnas obligatorias.
        nombre: Nombre descriptivo de la tabla (para logging).

    Returns:
        True si todas las columnas están presentes, False si faltan.
    """
    faltantes = [c for c in columnas if c not in df.columns]
    if faltantes:
        logger.warning(
            "Schema incompleto en tabla Gold",
            extra={"tabla": nombre, "columnas_faltantes": faltantes},
        )
        return False
    return True


# =============================================================================
# LOADERS CON CACHÉ
# =============================================================================


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS)
def cargar_predicciones() -> pd.DataFrame:
    """Carga la tabla gold.predicciones_diarias desde S3.

    Usa awswrangler para leer todos los Parquets particionados por
    year/month. Retorna DataFrame vacío si S3 no está disponible o
    el schema mínimo no se cumple, permitiendo que la UI muestre un
    mensaje amigable sin lanzar excepciones.

    Returns:
        DataFrame con columnas del contrato gold.predicciones_diarias,
        o DataFrame vacío si los datos no están disponibles.
    """
    try:
        df = wr.s3.read_parquet(path=GOLD_S3_PATH, dataset=True)
        schema_ok = _validar_schema_minimo(
            df, GOLD_PREDICCIONES_SCHEMA_MINIMO, "predicciones_diarias",
        )
        if not schema_ok:
            return pd.DataFrame()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "No se pudo cargar predicciones_diarias desde S3",
            extra={"error": str(exc), "path": GOLD_S3_PATH},
        )
        return pd.DataFrame()
    else:
        logger.info(
            "Predicciones Gold cargadas desde S3",
            extra={"rows": len(df), "path": GOLD_S3_PATH},
        )
        return df


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS)
def cargar_panel_diario() -> pd.DataFrame:
    """Carga la tabla gold.panel_diario desde S3.

    Returns:
        DataFrame con columnas del contrato gold.panel_diario,
        o DataFrame vacío si los datos no están disponibles.
    """
    try:
        df = wr.s3.read_parquet(path=PANEL_DIARIO_S3_PATH, dataset=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "No se pudo cargar panel_diario desde S3",
            extra={"error": str(exc), "path": PANEL_DIARIO_S3_PATH},
        )
        return pd.DataFrame()
    else:
        logger.info(
            "Panel diario Gold cargado desde S3",
            extra={"rows": len(df), "path": PANEL_DIARIO_S3_PATH},
        )
        return df


@st.cache_data(ttl=CACHE_TTL_SEGUNDOS)
def cargar_dim_estaciones() -> pd.DataFrame:
    """Carga la tabla dimensional de estaciones desde S3.

    Lee dim/dim_estaciones.csv del bucket de Gustavo. Retorna DataFrame
    vacío con fallback amigable si el archivo no está disponible.

    Returns:
        DataFrame con al menos station_id y nombre de estación,
        o DataFrame vacío si no está disponible.
    """
    try:
        df = wr.s3.read_csv(path=DIM_ESTACIONES_S3_PATH)
        schema_ok = _validar_schema_minimo(
            df, DIM_ESTACIONES_SCHEMA_MINIMO, "dim_estaciones",
        )
        if not schema_ok:
            return pd.DataFrame()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "No se pudo cargar dim_estaciones desde S3",
            extra={"error": str(exc), "path": DIM_ESTACIONES_S3_PATH},
        )
        return pd.DataFrame()
    else:
        logger.info(
            "Dimensión de estaciones cargada desde S3",
            extra={"rows": len(df), "path": DIM_ESTACIONES_S3_PATH},
        )
        return df


# =============================================================================
# HELPERS DE FILTRADO
# =============================================================================


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


# =============================================================================
# HELPERS DE DIMENSIONES
# =============================================================================


def obtener_nombre_estacion(df_dim: pd.DataFrame, station_id: str) -> str:
    """Devuelve el nombre legible de una estación dado su station_id.

    Busca en las columnas 'station_name_full' o 'station_name' (en ese orden).
    Si no hay datos de dimensión disponibles, retorna el station_id.

    Args:
        df_dim: DataFrame de dim_estaciones.
        station_id: Identificador de la estación.

    Returns:
        Nombre legible de la estación, o station_id si no se encuentra.
    """
    if df_dim.empty or "station_id" not in df_dim.columns:
        return station_id
    fila = df_dim[df_dim["station_id"] == station_id]
    if fila.empty:
        return station_id
    for col in ("station_name_full", "station_name"):
        if col in fila.columns:
            valor = fila.iloc[0][col]
            if pd.notna(valor) and str(valor).strip():
                return str(valor)
    return station_id


def construir_mapa_nombres_estaciones(df_dim: pd.DataFrame) -> dict[str, str]:
    """Construye un dict {station_id: nombre} para uso en selectboxes.

    Args:
        df_dim: DataFrame de dim_estaciones.

    Returns:
        Diccionario de mapeo station_id → nombre legible.
        Vacío si df_dim no tiene datos válidos.
    """
    if df_dim.empty or "station_id" not in df_dim.columns:
        return {}
    col_nombre = next(
        (c for c in ("station_name_full", "station_name") if c in df_dim.columns),
        None,
    )
    if col_nombre is None:
        return {}
    return dict(
        zip(
            df_dim["station_id"].astype(str),
            df_dim[col_nombre].astype(str),
            strict=False,
        ),
    )

