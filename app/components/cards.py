"""Tarjetas métricas para la UI de AirSense MX.

Componentes de presentación para mostrar valores de contaminantes,
semáforos por zona y resúmenes de calidad del aire. Cada función
encapsula un bloque de Streamlit que puede reutilizarse en páginas.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.components.badges import badge_semaforo, indicador_sin_datos
from app.config import (
    CONTAMINANTE_NOMBRES_COMPLETOS,
    CONTAMINANTE_UNIDADES,
    SEMAFORO_COLORES,
    SEMAFORO_ETIQUETAS,
    SEMAFORO_ICONOS,
    ZONAS_NOMBRES,
)


def tarjeta_zona(
    zone: str,
    semaforo: str,
    prob_contingencia: float,
    contaminante_critico: str,
) -> None:
    """Renderiza la tarjeta de calidad del aire para una zona.

    Args:
        zone: Código de zona ('NO', 'NE', etc.).
        semaforo: Nivel de semáforo de la zona.
        prob_contingencia: Probabilidad de contingencia [0-100] (ya en %).
        contaminante_critico: Nombre del contaminante con mayor riesgo.
    """
    color = SEMAFORO_COLORES.get(semaforo, "#CCCCCC")
    etiqueta = SEMAFORO_ETIQUETAS.get(semaforo, semaforo.capitalize())
    icono = SEMAFORO_ICONOS.get(semaforo, "⚪")
    nombre_zona = ZONAS_NOMBRES.get(zone, zone)

    st.markdown(
        f"""
        <div style="
            border-left: 5px solid {color};
            padding: 12px 16px;
            border-radius: 8px;
            background-color: {color}11;
            margin-bottom: 8px;
        ">
            <div style="font-weight: bold; font-size: 1.05rem;">{nombre_zona}</div>
            <div style="font-size: 1.3rem; margin: 4px 0;">
                {icono} <span style="color:{color}; font-weight:bold;">{etiqueta}</span>
            </div>
            <div style="font-size: 0.85rem; color: #555;">
                Prob. contingencia: <b>{prob_contingencia:.0f}%</b>
                &nbsp;·&nbsp; {contaminante_critico}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def tarjeta_contaminante(
    contaminante: str,
    valor: float | None,
    semaforo: str,
    umbral: float,
) -> None:
    """Renderiza una tarjeta métrica para un contaminante específico.

    Args:
        contaminante: Código del contaminante ('O3', 'PM25', 'PM10').
        valor: Valor predicho, o None si no hay datos.
        semaforo: Nivel del semáforo para este contaminante.
        umbral: Umbral PCAA para referencia visual.
    """
    nombre = CONTAMINANTE_NOMBRES_COMPLETOS.get(contaminante, contaminante)
    unidad = CONTAMINANTE_UNIDADES.get(contaminante, "")
    color = SEMAFORO_COLORES.get(semaforo, "#CCCCCC")

    with st.container():
        st.markdown(f"**{nombre}**")
        if valor is None:
            indicador_sin_datos()
        else:
            col_val, col_badge = st.columns([1, 2])
            with col_val:
                st.metric(
                    label=f"Pronóstico ({unidad})",
                    value=f"{valor:.1f}",
                    delta=f"Umbral: {umbral:.0f}",
                    delta_color="off",
                )
            with col_badge:
                badge_semaforo(semaforo, mostrar_descripcion=False)
                st.markdown(
                    f"<span style='color:{color}; font-size:0.8rem;'>"
                    f"{'⚠️ Sobre el umbral' if valor >= umbral else '✓ Bajo el umbral'}"
                    f"</span>",
                    unsafe_allow_html=True,
                )


def tabla_resumen_zonas(df_resumen: pd.DataFrame) -> None:
    """Muestra la tabla de resumen por zonas con formato visual.

    Args:
        df_resumen: DataFrame con columnas zone_nombre, etiqueta, icono,
                    prob_contingencia_max, contaminante_critico.
    """
    if df_resumen.empty:
        st.info("No hay datos de predicción disponibles para las zonas.")
        return

    columnas_mostrar = {
        "zone_nombre": "Zona",
        "icono": "Estado",
        "etiqueta": "Calidad",
        "prob_contingencia_max": "Prob. Contingencia (%)",
        "contaminante_critico": "Contaminante Crítico",
    }
    cols_presentes = {
        k: v for k, v in columnas_mostrar.items() if k in df_resumen.columns
    }
    st.dataframe(
        df_resumen[list(cols_presentes.keys())].rename(columns=cols_presentes),
        use_container_width=True,
        hide_index=True,
    )


def aviso_sin_datos(mensaje: str | None = None) -> None:
    """Renderiza un mensaje amigable cuando no hay datos disponibles.

    Args:
        mensaje: Texto personalizado. Si None usa el mensaje por defecto.
    """
    texto = mensaje or (
        "Los datos de pronóstico aún no están disponibles. "
        "El modelo se actualiza una vez al día. Vuelve más tarde."
    )
    st.warning(f"📭 {texto}")
