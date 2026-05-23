"""Página: Pronóstico de Contaminantes.

Flujo macro → micro: el usuario elige zona, luego contaminante,
luego estación. Muestra KPIs, gráfica de serie de tiempo con banda
de incertidumbre, probabilidad de contingencia, ranking por zona
y tabla ejecutiva. Consume gold/predicciones_diarias.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.components.cards import aviso_sin_datos
from app.components.charts import (
    grafico_prob_por_fecha,
    grafico_pronostico_por_fecha,
    grafico_ranking_estaciones_zona,
)
from app.config import (
    CONTAMINANTE_NOMBRES_COMPLETOS,
    CONTAMINANTE_UMBRAL_PCAA,
    CONTAMINANTE_UNIDADES,
    CONTAMINANTES_PREDICHOS,
    SEMAFORO_COLORES,
    SEMAFORO_ETIQUETAS,
    SEMAFORO_ICONOS,
    ZONAS_NOMBRES,
    ZONAS_ORDEN,
)
from app.data.s3_loader import (
    cargar_dim_estaciones,
    cargar_predicciones,
    construir_mapa_nombres_estaciones,
)
from utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# HELPERS PRIVADOS
# =============================================================================


def _obtener_contaminantes(df: pd.DataFrame) -> list[str]:
    """Extrae contaminantes disponibles, priorizando los predichos en v1.

    Args:
        df: DataFrame de predicciones.

    Returns:
        Lista ordenada de contaminantes disponibles.
    """
    if "contaminante" not in df.columns:
        return []
    disponibles = set(df["contaminante"].dropna().unique())
    ordenados = [c for c in CONTAMINANTES_PREDICHOS if c in disponibles]
    otros = sorted(disponibles - set(ordenados))
    return ordenados + otros


def _formatear_semaforo(valor: str) -> str:
    """Convierte código de semáforo a emoji + etiqueta en español.

    Args:
        valor: Código de semáforo ('verde', 'amarillo', 'naranja', 'rojo').

    Returns:
        Cadena con emoji y etiqueta legible.
    """
    icono = SEMAFORO_ICONOS.get(valor, "⚪")
    etiqueta = SEMAFORO_ETIQUETAS.get(valor, valor.capitalize())
    return f"{icono} {etiqueta}"


def _render_kpis(row: pd.Series, contaminante: str) -> None:
    """Muestra las 4 tarjetas KPI de la predicción seleccionada.

    Args:
        row: Fila más reciente del DataFrame de predicciones.
        contaminante: Código del contaminante activo.
    """
    unidad = CONTAMINANTE_UNIDADES.get(contaminante, "")
    semaforo = str(row.get("semaforo", "verde"))
    color = SEMAFORO_COLORES.get(semaforo, "#CCCCCC")
    etiqueta = SEMAFORO_ETIQUETAS.get(semaforo, semaforo.capitalize())
    icono = SEMAFORO_ICONOS.get(semaforo, "⚪")
    valor = row.get("valor_predicho")
    prob = row.get("probabilidad_contingencia")

    umbral_raw = row.get("umbral_contingencia")
    umbral: float | None = (
        float(umbral_raw)
        if umbral_raw is not None and not pd.isna(umbral_raw)
        else CONTAMINANTE_UMBRAL_PCAA.get(contaminante)
    )

    fecha_raw = row.get("fecha_objetivo")
    fecha_str = (
        pd.to_datetime(fecha_raw).strftime("%d %b %Y")
        if fecha_raw is not None
        else "—"
    )

    st.caption(f"Última predicción disponible — fecha objetivo: **{fecha_str}**")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(
            label=f"Valor predicho ({unidad})",
            value=f"{valor:.1f}" if valor is not None else "—",
        )
    with c2:
        prob_str = f"{prob * 100:.0f}%" if prob is not None else "—"
        st.metric(label="Prob. contingencia", value=prob_str)
    with c3:
        st.metric(label="Semáforo de riesgo", value=f"{icono} {etiqueta}")
        st.markdown(
            f"<div style='height:4px; background:{color};"
            "border-radius:2px; margin-top:4px;'></div>",
            unsafe_allow_html=True,
        )
    with c4:
        umbral_str = f"{umbral:.0f} {unidad}" if umbral is not None else "—"
        st.metric(label="Umbral PCAA", value=umbral_str)


def _preparar_tabla_ejecutiva(
    df_zona: pd.DataFrame,
    mapa_nombres: dict[str, str],
) -> pd.DataFrame:
    """Prepara la tabla ejecutiva con la predicción más reciente por estación.

    Ordena por probabilidad de contingencia descendente y formatea
    columnas numéricas y de semáforo para el usuario no técnico.

    Args:
        df_zona: DataFrame filtrado por zona y contaminante.
        mapa_nombres: Mapa station_id → nombre legible.

    Returns:
        DataFrame formateado listo para st.dataframe, o vacío si sin datos.
    """
    if df_zona.empty:
        return pd.DataFrame()

    df_latest = (
        df_zona.sort_values("fecha_objetivo")
        .groupby("station_id", as_index=False)
        .last()
        .sort_values("probabilidad_contingencia", ascending=False)
        .reset_index(drop=True)
    )

    df_out = df_latest.copy()
    df_out.insert(
        0, "Estación", df_out["station_id"].map(lambda s: mapa_nombres.get(s, s))
    )
    df_out["Zona"] = df_out["zone"].map(lambda z: ZONAS_NOMBRES.get(z, z))

    for col in ["valor_predicho", "valor_p10", "valor_p90", "umbral_contingencia"]:
        if col in df_out.columns:
            df_out[col] = df_out[col].apply(
                lambda x: f"{x:.1f}" if pd.notna(x) else "—"
            )
    if "probabilidad_contingencia" in df_out.columns:
        df_out["probabilidad_contingencia"] = df_out[
            "probabilidad_contingencia"
        ].apply(lambda x: f"{x * 100:.0f}%" if pd.notna(x) else "—")
    if "semaforo" in df_out.columns:
        df_out["semaforo"] = df_out["semaforo"].apply(_formatear_semaforo)
    if "fecha_objetivo" in df_out.columns:
        df_out["fecha_objetivo"] = pd.to_datetime(
            df_out["fecha_objetivo"]
        ).dt.strftime("%d %b %Y")

    cols_map = {
        "fecha_objetivo": "Fecha",
        "Estación": "Estación",
        "station_id": "Código",
        "Zona": "Zona",
        "contaminante": "Contaminante",
        "valor_predicho": "Valor predicho",
        "valor_p10": "P10",
        "valor_p90": "P90",
        "umbral_contingencia": "Umbral PCAA",
        "probabilidad_contingencia": "Prob. contingencia",
        "semaforo": "Semáforo",
        "modelo_version": "Versión modelo",
    }
    presentes = [c for c in cols_map if c in df_out.columns]
    return df_out[presentes].rename(columns=cols_map)


# =============================================================================
# RENDERIZADO PRINCIPAL
# =============================================================================


def render() -> None:
    """Renderiza la página de Pronóstico de Contaminantes."""
    st.title("📈 Pronóstico de Contaminantes")
    st.markdown(
        "Consulta el pronóstico de calidad del aire por estación y "
        "contaminante. Los valores se comparan contra los **umbrales "
        "oficiales de contingencia ambiental** (PCAA)."
    )

    # ── Carga de datos ─────────────────────────────────────────────────
    with st.spinner("Cargando datos…"):
        df_total = cargar_predicciones()
        df_dim = cargar_dim_estaciones()

    if df_total.empty:
        aviso_sin_datos()
        return

    df_total = df_total.copy()
    df_total["fecha_objetivo"] = pd.to_datetime(df_total["fecha_objetivo"])
    df_total["fecha_prediccion"] = pd.to_datetime(df_total["fecha_prediccion"])

    mapa_estaciones = construir_mapa_nombres_estaciones(df_dim)

    # ── Sidebar: selección zona → contaminante → estación ──────────────
    st.sidebar.subheader("Filtros de pronóstico")

    zonas_disp = [
        z
        for z in ZONAS_ORDEN
        if "zone" in df_total.columns and z in df_total["zone"].unique()
    ]
    if not zonas_disp:
        aviso_sin_datos("No se encontraron zonas en los datos.")
        return

    zona = st.sidebar.selectbox(
        "Zona",
        options=zonas_disp,
        format_func=lambda z: ZONAS_NOMBRES.get(z, z),
    )
    contaminante = st.sidebar.selectbox(
        "Contaminante",
        options=_obtener_contaminantes(df_total),
        format_func=lambda c: CONTAMINANTE_NOMBRES_COMPLETOS.get(c, c),
    )

    df_zona_cont = df_total[
        (df_total["zone"] == zona) & (df_total["contaminante"] == contaminante)
    ].copy()

    estaciones_disp = sorted(df_zona_cont["station_id"].dropna().unique().tolist())
    if not estaciones_disp:
        st.warning("No hay estaciones disponibles para esta zona y contaminante.")
        return

    estacion = st.sidebar.selectbox(
        "Estación",
        options=estaciones_disp,
        format_func=lambda s: mapa_estaciones.get(s, s),
    )

    n_dias = st.sidebar.slider(
        "Predicciones a mostrar", min_value=7, max_value=90, value=30, step=7
    )

    logger.info(
        "Pronóstico consultado",
        extra={"zona": zona, "contaminante": contaminante, "estacion": estacion},
    )

    # ── Filtrado por estación ──────────────────────────────────────────
    df_estacion = (
        df_zona_cont[df_zona_cont["station_id"] == estacion]
        .sort_values("fecha_objetivo")
        .tail(n_dias)
        .reset_index(drop=True)
    )

    if df_estacion.empty:
        st.warning(
            f"No hay predicciones para **{mapa_estaciones.get(estacion, estacion)}**."
        )
        return

    # ── KPIs ────────────────────────────────────────────────────────────
    try:
        _render_kpis(df_estacion.iloc[-1], contaminante)
    except Exception as exc:
        st.error(f"Error al mostrar los indicadores: {exc}")
        logger.error("Error KPIs pronóstico", extra={"error": str(exc)})

    st.divider()

    # ── Gráfica principal: serie de tiempo con banda p10-p90 ───────────
    nombre_est = mapa_estaciones.get(estacion, estacion)
    st.subheader(f"Predicciones — {nombre_est}")
    try:
        fig_pron = grafico_pronostico_por_fecha(df_estacion, contaminante, nombre_est)
        st.plotly_chart(fig_pron, use_container_width=True)
    except Exception as exc:
        st.error(f"Error al generar la gráfica de pronóstico: {exc}")
        logger.error("Error gráfica pronóstico", extra={"error": str(exc)})

    st.divider()

    # ── Probabilidad de contingencia + Ranking zona ────────────────────
    col_prob, col_rank = st.columns([3, 2])

    with col_prob:
        st.subheader("Probabilidad de contingencia")
        try:
            fig_prob = grafico_prob_por_fecha(df_estacion, contaminante)
            st.plotly_chart(fig_prob, use_container_width=True)
        except Exception as exc:
            st.warning(f"Error al generar gráfica de probabilidad: {exc}")
            logger.warning("Error prob chart", extra={"error": str(exc)})

    with col_rank:
        zona_nombre = ZONAS_NOMBRES.get(zona, zona)
        st.subheader(f"Riesgo en {zona_nombre}")
        try:
            df_rank = df_zona_cont.copy()
            if (
                not df_dim.empty
                and "station_name" in df_dim.columns
                and "station_name" not in df_rank.columns
            ):
                df_rank = df_rank.merge(
                    df_dim[["station_id", "station_name"]],
                    on="station_id",
                    how="left",
                    suffixes=("", "_dim"),
                )
            fig_rank = grafico_ranking_estaciones_zona(
                df_rank, contaminante, zona_nombre
            )
            st.plotly_chart(fig_rank, use_container_width=True)
        except Exception as exc:
            st.warning(f"Error al generar el ranking: {exc}")
            logger.warning("Error ranking chart", extra={"error": str(exc)})

    st.divider()

    # ── Tabla ejecutiva ────────────────────────────────────────────────
    with st.expander("📋 Ver tabla — todas las estaciones de la zona"):
        try:
            df_tabla = _preparar_tabla_ejecutiva(df_zona_cont, mapa_estaciones)
            if df_tabla.empty:
                st.info("No hay datos disponibles para la tabla.")
            else:
                st.dataframe(df_tabla, use_container_width=True, hide_index=True)
        except Exception as exc:
            st.error(f"Error al mostrar la tabla: {exc}")
            logger.error("Error tabla ejecutiva", extra={"error": str(exc)})

