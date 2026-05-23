"""Página: Pronóstico de Contaminantes (1–7 días).

Permite al usuario seleccionar una estación y contaminante para ver
el pronóstico detallado de los próximos 7 días, incluyendo intervalo
de incertidumbre y probabilidad de contingencia.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.components.cards import aviso_sin_datos, tarjeta_contaminante
from app.components.charts import (
    grafico_probabilidad_contingencia,
    grafico_pronostico_linea,
)
from app.config import (
    CONTAMINANTE_NOMBRES_COMPLETOS,
    CONTAMINANTE_UMBRAL_PCAA,
    CONTAMINANTES_PREDICHOS,
)
from app.data.s3_loader import (
    cargar_predicciones,
    filtrar_por_fecha_prediccion,
    obtener_fecha_prediccion_mas_reciente,
)
from app.models.risk_analyzer import obtener_pronostico_estacion
from utils.logging import get_logger

logger = get_logger(__name__)


def render() -> None:
    """Renderiza la página de Pronóstico 1–7 días."""
    st.title("📈 Pronóstico de Contaminantes")
    st.markdown(
        "Consulta el pronóstico de calidad del aire para los próximos "
        "**7 días** por estación y contaminante."
    )

    # Carga de datos
    with st.spinner("Cargando datos..."):
        df_total = cargar_predicciones()

    if df_total.empty:
        aviso_sin_datos()
        return

    fecha_reciente = obtener_fecha_prediccion_mas_reciente(df_total)
    df_base = filtrar_por_fecha_prediccion(df_total, fecha_reciente or "")

    if df_base.empty:
        aviso_sin_datos("No hay pronóstico para la fecha más reciente.")
        return

    # Controles de selección
    st.sidebar.subheader("Filtros de pronóstico")
    estaciones_disponibles = _obtener_estaciones(df_base)
    contaminantes_disponibles = _obtener_contaminantes(df_base)

    if not estaciones_disponibles or not contaminantes_disponibles:
        aviso_sin_datos("Los datos no contienen estaciones o contaminantes válidos.")
        return

    estacion = st.sidebar.selectbox(
        "Estación",
        options=estaciones_disponibles,
        format_func=lambda s: s,
    )
    contaminante = st.sidebar.selectbox(
        "Contaminante",
        options=contaminantes_disponibles,
        format_func=lambda c: CONTAMINANTE_NOMBRES_COMPLETOS.get(c, c),
    )

    logger.info(
        "Pronóstico solicitado",
        extra={"estacion": estacion, "contaminante": contaminante},
    )

    # Pronóstico para la selección
    df_pronostico = obtener_pronostico_estacion(df_base, estacion, contaminante)

    if df_pronostico.empty:
        st.warning(
            f"No hay pronóstico disponible para la estación **{estacion}** "
            f"y contaminante "
            f"**{CONTAMINANTE_NOMBRES_COMPLETOS.get(contaminante, contaminante)}**."
        )
        return

    # Métrica del día 1 (mañana)
    _mostrar_resumen_manana(df_pronostico, contaminante)

    st.divider()

    # Gráfico principal de pronóstico
    col_grafico, col_prob = st.columns([3, 2])
    with col_grafico:
        fig_linea = grafico_pronostico_linea(df_pronostico, contaminante, estacion)
        st.plotly_chart(fig_linea, use_container_width=True)
    with col_prob:
        if "probabilidad_contingencia" in df_pronostico.columns:
            fig_prob = grafico_probabilidad_contingencia(df_pronostico, contaminante)
            st.plotly_chart(fig_prob, use_container_width=True)

    st.divider()

    # Tabla detallada
    with st.expander("Ver datos del pronóstico", expanded=False):
        _mostrar_tabla_pronostico(df_pronostico, contaminante)


def _mostrar_resumen_manana(df: pd.DataFrame, contaminante: str) -> None:
    """Muestra la tarjeta de resumen para el día 1 (mañana).

    Args:
        df: DataFrame de pronóstico ordenado por horizonte_dias.
        contaminante: Código del contaminante.
    """
    st.subheader("Resumen — mañana (día 1)")
    fila_d1 = df[df["horizonte_dias"] == 1]
    if fila_d1.empty:
        st.info("No hay predicción para mañana.")
        return

    row = fila_d1.iloc[0]
    valor = row.get("valor_predicho")
    semaforo = row.get("semaforo", "verde")
    umbral = CONTAMINANTE_UMBRAL_PCAA.get(contaminante, 0)

    tarjeta_contaminante(
        contaminante=contaminante,
        valor=float(valor) if valor is not None else None,
        semaforo=str(semaforo),
        umbral=umbral,
    )


def _mostrar_tabla_pronostico(df: pd.DataFrame, contaminante: str) -> None:
    """Renderiza la tabla detallada con formato amigable.

    Args:
        df: DataFrame de pronóstico.
        contaminante: Código del contaminante para etiquetas.
    """
    cols_mostrar = {
        "horizonte_dias": "Día",
        "fecha_objetivo": "Fecha",
        "valor_predicho": "Valor predicho",
        "valor_p10": "Mínimo (P10)",
        "valor_p90": "Máximo (P90)",
        "probabilidad_contingencia": "Prob. Contingencia",
        "semaforo": "Semáforo",
    }
    cols_presentes = {k: v for k, v in cols_mostrar.items() if k in df.columns}
    df_display = df[list(cols_presentes.keys())].rename(columns=cols_presentes).copy()

    if "Prob. Contingencia" in df_display.columns:
        df_display["Prob. Contingencia"] = df_display["Prob. Contingencia"].apply(
            lambda x: f"{x * 100:.0f}%" if pd.notna(x) else "—"
        )

    st.dataframe(df_display, use_container_width=True, hide_index=True)


def _obtener_estaciones(df: pd.DataFrame) -> list[str]:
    """Extrae la lista de estaciones disponibles en el DataFrame."""
    if "station_id" not in df.columns:
        return []
    return sorted(df["station_id"].dropna().unique().tolist())


def _obtener_contaminantes(df: pd.DataFrame) -> list[str]:
    """Extrae la lista de contaminantes disponibles, priorizando los predichos."""
    if "contaminante" not in df.columns:
        return []
    disponibles = set(df["contaminante"].dropna().unique())
    ordenados = [c for c in CONTAMINANTES_PREDICHOS if c in disponibles]
    otros = sorted(disponibles - set(ordenados))
    return ordenados + otros
