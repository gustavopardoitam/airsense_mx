"""Página: Panel de Calidad del Aire (Dashboard principal).

Muestra el estado actual de la calidad del aire en la ZMVM por zona,
el semáforo de riesgo de hoy, y las métricas clave por contaminante.
"""

from __future__ import annotations

import datetime

import streamlit as st

from app.components.badges import badge_semaforo
from app.components.cards import aviso_sin_datos, tabla_resumen_zonas, tarjeta_zona
from app.data.s3_loader import (
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

    # Carga de datos
    with st.spinner("Cargando pronóstico..."):
        df_total = cargar_predicciones()

    if df_total.empty:
        aviso_sin_datos()
        _mostrar_estado_sistema()
        return

    # Filtrar por la fecha de predicción más reciente y horizonte 1 (mañana)
    fecha_reciente = obtener_fecha_prediccion_mas_reciente(df_total)
    df_hoy = filtrar_por_fecha_prediccion(df_total, fecha_reciente or "")
    df_manana = filtrar_por_horizonte(df_hoy, horizonte=1)

    if df_manana.empty:
        aviso_sin_datos(
            "No hay predicciones para mañana. El modelo se actualiza diariamente."
        )
        return

    logger.info(
        "Dashboard cargado",
        extra={"fecha": fecha_reciente, "rows": len(df_manana)},
    )

    # Encabezado con fecha
    col_fecha, col_alerta = st.columns([3, 1])
    with col_fecha:
        fecha_str = _formatear_fecha(fecha_reciente)
        st.markdown(f"**Predicción para mañana** — basada en datos del {fecha_str}")
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


def _mostrar_semaforo_general(
    df_resumen: object,
) -> None:
    """Muestra el semáforo general basado en el peor estado de la ZMVM."""
    import pandas as pd

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
