"""Página: Riesgo de Contingencia Ambiental.

Muestra la probabilidad de contingencia por zona, permite seleccionar
una zona para obtener una explicación en lenguaje natural vía Bedrock,
y presenta el mapa de calor de riesgo por zona y contaminante.
"""

from __future__ import annotations

import streamlit as st

from app.components.badges import badge_probabilidad, badge_semaforo
from app.components.cards import aviso_sin_datos
from app.components.charts import grafico_mapa_calor_zonas
from app.config import CONTAMINANTE_NOMBRES, CONTAMINANTE_UNIDADES, ZONAS_NOMBRES
from app.data.s3_loader import (
    cargar_predicciones,
    filtrar_por_fecha_prediccion,
    filtrar_por_horizonte,
    obtener_fecha_prediccion_mas_reciente,
)
from app.models.bedrock_explainer import generar_explicacion
from app.models.risk_analyzer import obtener_resumen_zona
from utils.logging import get_logger

logger = get_logger(__name__)


def render() -> None:
    """Renderiza la página de Riesgo de Contingencia."""
    st.title("⚠️ Riesgo de Contingencia Ambiental")
    st.markdown(
        "Probabilidad de que mañana se active una "
        "**Contingencia Ambiental Atmosférica** "
        "según el Programa de Contingencias Ambientales (PCAA) de la ZMVM."
    )

    # Carga de datos
    with st.spinner("Cargando datos de riesgo..."):
        df_total = cargar_predicciones()

    if df_total.empty:
        aviso_sin_datos()
        _mostrar_informacion_pcaa()
        return

    fecha_reciente = obtener_fecha_prediccion_mas_reciente(df_total)
    df_base = filtrar_por_fecha_prediccion(df_total, fecha_reciente or "")
    df_manana = filtrar_por_horizonte(df_base, horizonte=1)

    if df_manana.empty:
        aviso_sin_datos("No hay datos de riesgo para mañana.")
        return

    # Resumen por zona
    df_resumen = obtener_resumen_zona(df_manana)
    _mostrar_resumen_por_zona(df_resumen)

    st.divider()

    # Mapa de calor
    st.subheader("Riesgo por zona y contaminante")
    fig_calor = grafico_mapa_calor_zonas(df_manana)
    if fig_calor.data:
        st.plotly_chart(fig_calor, use_container_width=True)
    else:
        st.info("No hay suficientes datos para generar el mapa de calor.")

    st.divider()

    # Explicación con Bedrock
    _mostrar_explicacion_bedrock(df_resumen, df_manana)

    st.divider()
    _mostrar_informacion_pcaa()


def _mostrar_resumen_por_zona(df_resumen: object) -> None:
    """Muestra tarjetas de riesgo para cada zona.

    Args:
        df_resumen: DataFrame con columnas zone, semaforo,
                    prob_contingencia_max, contaminante_critico.
    """
    import pandas as pd

    if not isinstance(df_resumen, pd.DataFrame) or df_resumen.empty:
        st.info("No hay datos de riesgo por zona disponibles.")
        return

    st.subheader("Estado por zona — mañana")
    cols = st.columns(min(len(df_resumen), 5))

    for i, (_, row) in enumerate(df_resumen.iterrows()):
        with cols[i % len(cols)]:
            zone = row.get("zone", "")
            semaforo = row.get("semaforo", "verde")
            prob = row.get("prob_contingencia_max", 0)
            zona_nombre = ZONAS_NOMBRES.get(zone, zone)

            st.markdown(f"**{zona_nombre}**")
            badge_semaforo(semaforo)
            badge_probabilidad(prob / 100, semaforo)
            st.markdown(
                f"<small>Contaminante crítico: "
                f"{row.get('contaminante_critico', '—')}</small>",
                unsafe_allow_html=True,
            )


def _mostrar_explicacion_bedrock(
    df_resumen: object,
    df_manana: object,
) -> None:
    """Permite obtener una explicación en lenguaje natural vía Bedrock.

    El usuario selecciona una zona y el sistema consulta a Claude Haiku
    para generar una explicación accionable.

    Args:
        df_resumen: DataFrame de resumen por zona.
        df_manana: DataFrame de predicciones para mañana.
    """
    import pandas as pd

    st.subheader("🤖 Explicación en lenguaje natural")
    st.markdown(
        "Selecciona una zona para recibir una explicación sobre el riesgo de mañana."
    )

    if not isinstance(df_resumen, pd.DataFrame) or df_resumen.empty:
        st.info("No hay datos para generar una explicación.")
        return

    zonas_disponibles = (
        df_resumen["zone"].tolist() if "zone" in df_resumen.columns else []
    )
    if not zonas_disponibles:
        return

    zona_sel = st.selectbox(
        "Zona",
        options=zonas_disponibles,
        format_func=lambda z: ZONAS_NOMBRES.get(z, z),
        key="zona_bedrock",
    )

    if st.button("Generar explicación", type="primary"):
        fila_zona = df_resumen[df_resumen["zone"] == zona_sel].iloc[0]
        semaforo = str(fila_zona.get("semaforo", "verde"))
        prob = float(fila_zona.get("prob_contingencia_max", 0)) / 100

        # Obtener el contaminante más crítico y su valor predicho
        if isinstance(df_manana, pd.DataFrame) and not df_manana.empty:
            subset_zona = df_manana[df_manana["zone"] == zona_sel]
            col_contingencia = "probabilidad_contingencia"
            if not subset_zona.empty and col_contingencia in subset_zona.columns:
                idx_critico = subset_zona[col_contingencia].idxmax()
                fila_critica = subset_zona.loc[idx_critico]
                contaminante = str(fila_critica.get("contaminante", "O3"))
                valor = float(fila_critica.get("valor_predicho", 0))
            else:
                contaminante, valor = "O3", 0.0
        else:
            contaminante, valor = "O3", 0.0

        nombre_contaminante = CONTAMINANTE_NOMBRES.get(contaminante, contaminante)
        unidad = CONTAMINANTE_UNIDADES.get(contaminante, "")
        nombre_zona = ZONAS_NOMBRES.get(zona_sel, zona_sel)

        with st.spinner("Consultando Amazon Bedrock..."):
            explicacion = generar_explicacion(
                zona=nombre_zona,
                semaforo=semaforo,
                contaminante=nombre_contaminante,
                valor=valor,
                unidad=unidad,
                probabilidad_contingencia=prob,
            )

        st.info(f"💬 {explicacion}")
        logger.info(
            "Explicación Bedrock generada",
            extra={"zona": zona_sel, "semaforo": semaforo},
        )


def _mostrar_informacion_pcaa() -> None:
    """Muestra información contextual sobre el programa PCAA."""
    with st.expander("¿Qué es una Contingencia Ambiental?", expanded=False):
        st.markdown(
            """
            El **Programa de Contingencias Ambientales Atmosféricas (PCAA)** de la ZMVM
            se activa cuando las concentraciones de contaminantes superan umbrales
            establecidos por la SEDEMA.

            | Contaminante | Métrica | Umbral Fase I |
            |---|---|---|
            | Ozono (O₃) | Máximo 1 hora | 140 ppb |
            | PM2.5 | Promedio 24 horas | 79 µg/m³ |
            | PM10 | Promedio 24 horas | 146 µg/m³ |
            | NO₂ | Máximo 1 hora | 188 ppb |
            | SO₂ | Máximo 1 hora | 185 ppb |

            **Recomendaciones durante contingencia:**
            - Reducir el uso del automóvil.
            - Evitar actividades físicas intensas al aire libre.
            - Grupos sensibles (niños, adultos mayores, personas con enfermedades
              respiratorias) deben permanecer en interiores.
            """
        )
