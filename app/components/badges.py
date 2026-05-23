"""Badges de semáforo y riesgo para la UI de AirSense MX.

Genera HTML/CSS para mostrar indicadores visuales de calidad del aire.
Cada función retorna un string HTML que se renderiza con
`st.markdown(badge, unsafe_allow_html=True)`.
"""

from __future__ import annotations

import streamlit as st

from app.config import (
    SEMAFORO_COLORES,
    SEMAFORO_DESCRIPCION,
    SEMAFORO_ETIQUETAS,
    SEMAFORO_ICONOS,
)


def badge_semaforo(semaforo: str, mostrar_descripcion: bool = False) -> None:
    """Renderiza un badge coloreado con el nivel de semáforo.

    Args:
        semaforo: Valor del semáforo ('verde', 'amarillo', 'naranja', 'rojo').
        mostrar_descripcion: Si True, incluye la descripción debajo del badge.
    """
    color = SEMAFORO_COLORES.get(semaforo, "#CCCCCC")
    etiqueta = SEMAFORO_ETIQUETAS.get(semaforo, semaforo.capitalize())
    icono = SEMAFORO_ICONOS.get(semaforo, "⚪")

    html = f"""
    <div style="
        display: inline-block;
        background-color: {color};
        color: white;
        font-weight: bold;
        font-size: 1.1rem;
        padding: 6px 16px;
        border-radius: 20px;
        margin: 4px 0;
        text-shadow: 0 1px 2px rgba(0,0,0,0.3);
    ">
        {icono} {etiqueta}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

    if mostrar_descripcion:
        descripcion = SEMAFORO_DESCRIPCION.get(semaforo, "")
        st.caption(descripcion)


def badge_probabilidad(probabilidad: float, semaforo: str) -> None:
    """Renderiza un badge con la probabilidad de contingencia.

    Args:
        probabilidad: Valor entre 0 y 1.
        semaforo: Semáforo para determinar el color del badge.
    """
    color = SEMAFORO_COLORES.get(semaforo, "#CCCCCC")
    pct = round(probabilidad * 100)
    html = f"""
    <div style="
        display: inline-block;
        background-color: {color}22;
        border: 2px solid {color};
        color: {color};
        font-weight: bold;
        font-size: 1.3rem;
        padding: 8px 20px;
        border-radius: 12px;
        margin: 4px 0;
    ">
        {pct}% de contingencia
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def indicador_sin_datos() -> None:
    """Renderiza un badge neutro para indicar que no hay datos."""
    html = """
    <div style="
        display: inline-block;
        background-color: #BDC3C7;
        color: white;
        font-weight: bold;
        font-size: 1rem;
        padding: 6px 16px;
        border-radius: 20px;
        margin: 4px 0;
    ">
        ⚪ Sin datos
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)
