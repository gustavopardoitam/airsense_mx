"""Página: Panel de Calidad del Aire (Dashboard principal).

Muestra el estado actual de la calidad del aire en la ZMVM por zona,
el semáforo de riesgo de hoy, y las métricas clave por contaminante.
"""

from __future__ import annotations

import datetime

import pandas as pd
import streamlit as st

from app.components.badges import badge_semaforo
from app.components.cards import aviso_sin_datos, tabla_resumen_zonas, tarjeta_zona
from app.components.charts import grafico_mapa_estaciones, grafico_tendencia_historica
from app.data.s3_loader import (
    cargar_dim_estaciones,
    cargar_panel_diario,
    cargar_predicciones,
    filtrar_por_fecha_prediccion,
    filtrar_por_horizonte,
    obtener_fecha_prediccion_mas_reciente,
)
from app.models.risk_analyzer import hay_contingencia_activa, obtener_resumen_zona
from utils.logging import get_logger

logger = get_logger(__name__)


def render() -> None:
    """Renderiza la página de Dashboard principal."""
    st.title("🌫️ Panel de Calidad del Aire — ZMVM")
    st.markdown(
        "Estado del pronóstico para el día de mañana en la "
        "Zona Metropolitana del Valle de México."
    )

    # Carga de datos de predicciones
    with st.spinner("Cargando pronóstico..."):
        df_total = cargar_predicciones()

    if df_total.empty:
        aviso_sin_datos()
        _mostrar_estado_sistema()
    else:
        # Filtrar por la fecha de predicción más reciente y horizonte 1 (mañana)
        fecha_reciente = obtener_fecha_prediccion_mas_reciente(df_total)
        df_hoy = filtrar_por_fecha_prediccion(df_total, fecha_reciente or "")
        df_manana = filtrar_por_horizonte(df_hoy, horizonte=1)

        if not df_manana.empty:
            logger.info(
                "Dashboard cargado",
                extra={"fecha": fecha_reciente, "rows": len(df_manana)},
            )

            # Encabezado con fecha
            col_fecha, col_alerta = st.columns([3, 1])
            with col_fecha:
                fecha_str = _formatear_fecha(fecha_reciente)
                st.markdown(
                    f"**Predicción para mañana** — basada en datos del {fecha_str}"
                )
            with col_alerta:
                if hay_contingencia_activa(df_manana):
                    st.error("⚠️ Riesgo de contingencia")
                else:
                    st.success("✅ Sin contingencia prevista")

            st.divider()

            # Semáforo general (peor zona)
            df_resumen = obtener_resumen_zona(df_manana)
            _mostrar_semaforo_general(df_resumen)

            st.divider()

            # Tarjetas por zona
            st.subheader("Estado por zona")
            if df_resumen.empty:
                st.info("No hay datos por zona.")
            else:
                cols = st.columns(min(len(df_resumen), 5))
                for idx, row in df_resumen.iterrows():
                    with cols[int(idx) % len(cols)]:
                        tarjeta_zona(
                            zone=row.get("zone", ""),
                            semaforo=row.get("semaforo", "verde"),
                            prob_contingencia=row.get("prob_contingencia_max", 0),
                            contaminante_critico=row.get("contaminante_critico", "—"),
                        )

            st.divider()

            # Tabla resumen
            with st.expander("Ver tabla completa por zona", expanded=False):
                tabla_resumen_zonas(df_resumen)
        else:
            aviso_sin_datos(
                "No hay predicciones para mañana. El modelo se actualiza diariamente."
            )

    # Histórico — se carga siempre, independiente del pronóstico
    with st.spinner("Cargando histórico..."):
        df_panel = cargar_panel_diario()
        df_dim = cargar_dim_estaciones()
    if not df_panel.empty:
        _render_historico_panel(df_panel, df_dim)


# =============================================================================
# HISTÓRICO CON DRILL-DOWN GEOGRÁFICO
# =============================================================================

_PANEL_CONTAMINANTES: dict[str, tuple[str, str, float | None]] = {
    "O3 — Máx. 1h (ppb)": ("o3_max_1h", "ppb", 140.0),
    "PM2.5 — Prom. 24h (µg/m³)": ("pm25_avg_24h", "µg/m³", 79.0),
    "PM10 — Prom. 24h (µg/m³)": ("pm10_avg_24h", "µg/m³", 146.0),
    "NO₂ — Máx. 1h (ppb)": ("no2_max_1h", "ppb", None),
}

_ZONA_NOMBRES_PANEL: dict[str, str] = {
    "CE": "Centro", "NO": "Noroeste", "NE": "Noreste",
    "SO": "Suroeste", "SE": "Sureste",
}


def _preparar_df_zona_panel(df: pd.DataFrame, col_valor: str) -> pd.DataFrame:
    """Agrega panel_diario por zona: promedio diario de todas las estaciones.

    Args:
        df: DataFrame de panel_diario ya filtrado por rango de fechas.
        col_valor: Columna del contaminante a agregar.

    Returns:
        DataFrame con columnas fecha, zone (nombre legible), col_valor.
    """
    df_agg = df.groupby(["fecha", "zone"])[col_valor].mean().reset_index()
    df_agg["zone"] = df_agg["zone"].map(_ZONA_NOMBRES_PANEL).fillna(df_agg["zone"])
    return df_agg


def _preparar_df_estacion_panel(
    df: pd.DataFrame,
    col_valor: str,
    zona_code: str,
    df_dim: pd.DataFrame,
) -> pd.DataFrame:
    """Filtra panel_diario por zona y une nombres de estación para drill-down.

    Args:
        df: DataFrame de panel_diario.
        col_valor: Columna del contaminante.
        zona_code: Código de zona ('CE', 'NO', etc.).
        df_dim: DataFrame de dim_estaciones con station_name.

    Returns:
        DataFrame con columnas fecha, station_id (nombre legible), col_valor.
    """
    df_est = df[df["zone"] == zona_code][["fecha", "station_id", col_valor]].copy()
    nombre_col = next(
        (c for c in ("station_name", "station_name_full") if c in df_dim.columns),
        None,
    )
    if not df_dim.empty and nombre_col:
        df_est = df_est.merge(
            df_dim[["station_id", nombre_col]], on="station_id", how="left"
        )
        df_est["station_id"] = df_est[nombre_col].fillna(df_est["station_id"])
        df_est = df_est.drop(columns=[nombre_col])
    return df_est


def _preparar_df_geo_panel(
    df: pd.DataFrame,
    col_valor: str,
    df_dim: pd.DataFrame,
    zona_code: str | None,
) -> pd.DataFrame:
    """Une el snapshot de la última fecha con coordenadas geográficas.

    Args:
        df: DataFrame de panel_diario filtrado por rango.
        col_valor: Columna del contaminante.
        df_dim: DataFrame de dim_estaciones con latitude y longitude.
        zona_code: Si se especifica, filtra solo esa zona.

    Returns:
        DataFrame listo para grafico_mapa_estaciones, o vacío si faltan datos.
    """
    if df_dim.empty or "latitude" not in df_dim.columns:
        return pd.DataFrame()
    fecha_max = df["fecha"].max()
    df_snap = df[df["fecha"] == fecha_max].copy()
    if zona_code:
        df_snap = df_snap[df_snap["zone"] == zona_code]
    cols_dim = [
        c for c in ["station_id", "latitude", "longitude", "station_name"]
        if c in df_dim.columns
    ]
    # Excluir 'zone' de dim para evitar colisión con panel_diario
    return df_snap.merge(df_dim[cols_dim], on="station_id", how="left")


def _render_historico_panel(df_panel: pd.DataFrame, df_dim: pd.DataFrame) -> None:
    """Renderiza la sección de histórico con mapa y serie temporal con drill-down.

    Nivel 1: serie temporal por zona (5 líneas).
    Nivel 2: al seleccionar una zona, muestra líneas por estación (drill-down).
    El mapa muestra el snapshot más reciente del período seleccionado.

    Args:
        df_panel: DataFrame completo de gold.panel_diario.
        df_dim: DataFrame de dim_estaciones con coordenadas geográficas.
    """
    st.divider()
    st.subheader("📊 Histórico de Calidad del Aire — Datos reales por zona y estación")

    # ── Controles ──────────────────────────────────────────────────────────
    c1, c2, c3 = st.columns([2, 2, 3])
    with c1:
        label = st.selectbox(
            "Contaminante", list(_PANEL_CONTAMINANTES.keys()), key="p_cont"
        )
    col_valor, unidad, umbral = _PANEL_CONTAMINANTES[label]
    titulo_y = f"{label.split('—')[0].strip()} ({unidad})"

    df_panel = df_panel.copy()
    df_panel["fecha"] = pd.to_datetime(df_panel["fecha"])
    fecha_min = df_panel["fecha"].min().date()
    fecha_max_global = df_panel["fecha"].max().date()
    default_inicio = fecha_max_global - datetime.timedelta(days=180)

    with c2:
        zonas_disp = sorted(df_panel["zone"].dropna().unique())
        zona_opts = ["— Todas las zonas —"] + [
            _ZONA_NOMBRES_PANEL.get(z, z) for z in zonas_disp
        ]
        zona_sel = st.selectbox("Drill-down zona", zona_opts, key="p_zona")

    with c3:
        rango = st.date_input(
            "Rango de fechas",
            value=(max(fecha_min, default_inicio), fecha_max_global),
            min_value=fecha_min,
            max_value=fecha_max_global,
            key="p_rango",
        )

    # ── Filtrar por rango ──────────────────────────────────────────────────
    if isinstance(rango, (list, tuple)) and len(rango) == 2:
        df_panel = df_panel[
            (df_panel["fecha"].dt.date >= rango[0])
            & (df_panel["fecha"].dt.date <= rango[1])
        ]

    if col_valor not in df_panel.columns or df_panel.empty:
        st.info("No hay datos disponibles para la selección.")
        return

    # ── Serie temporal ─────────────────────────────────────────────────────
    zona_inv = {v: k for k, v in _ZONA_NOMBRES_PANEL.items()}
    zona_code = zona_inv.get(zona_sel)

    if zona_code is None:
        df_plot = _preparar_df_zona_panel(df_panel, col_valor)
        color_col = "zone"
        titulo_chart = f"Tendencia por Zona — {label}"
    else:
        df_plot = _preparar_df_estacion_panel(df_panel, col_valor, zona_code, df_dim)
        color_col = "station_id"
        titulo_chart = f"Estaciones — {zona_sel} — {label}"

    st.plotly_chart(
        grafico_tendencia_historica(
            df_plot, col_valor, titulo_y, color_col, titulo_chart, umbral
        ),
        use_container_width=True,
    )

    # ── Mapa geográfico (snapshot última fecha del rango) ──────────────────
    try:
        df_geo = _preparar_df_geo_panel(df_panel, col_valor, df_dim, zona_code)
        if not df_geo.empty:
            fecha_snap = df_panel["fecha"].max().date()
            st.caption(f"Mapa: snapshot al {fecha_snap}")
            st.plotly_chart(
                grafico_mapa_estaciones(df_geo, col_valor, titulo_y),
                use_container_width=True,
            )
    except Exception as exc:
        st.warning(f"No se pudo generar el mapa geográfico: {exc}")
        logger.warning("Error en mapa histórico", extra={"error": str(exc)})

    logger.info(
        "Histórico renderizado",
        extra={"col_valor": col_valor, "zona": zona_sel, "rows": len(df_plot)},
    )


def _mostrar_semaforo_general(
    df_resumen: object,
) -> None:
    """Muestra el semáforo general basado en el peor estado de la ZMVM."""
    from app.config import SEMAFORO_ORDEN

    if not isinstance(df_resumen, pd.DataFrame) or df_resumen.empty:
        return

    if "semaforo" not in df_resumen.columns:
        return

    peor = df_resumen.loc[
        df_resumen["semaforo"].map(SEMAFORO_ORDEN).idxmax(), "semaforo"
    ]
    st.subheader("Calidad general de la ZMVM")
    badge_semaforo(peor, mostrar_descripcion=True)


def _formatear_fecha(fecha: str | None) -> str:
    """Convierte 'YYYY-MM-DD' a texto legible en español."""
    if not fecha:
        return "fecha desconocida"
    try:
        dt = datetime.date.fromisoformat(str(fecha))
        meses = [
            "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
        ]
        return f"{dt.day} de {meses[dt.month]} de {dt.year}"
    except ValueError:
        return str(fecha)


def _mostrar_estado_sistema() -> None:
    """Muestra información de estado cuando no hay datos."""
    st.markdown("---")
    st.markdown("#### ¿Por qué no hay datos?")
    st.markdown(
        """
        - El modelo de predicción genera pronósticos **una vez al día** (batch diario).
        - Si acabas de abrir la app, es posible que el pipeline aún no haya corrido.
        - Si el problema persiste, revisa la tabla `gold.predicciones_diarias` en S3.
        """
    )
