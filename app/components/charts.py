"""Gráficos interactivos con Plotly para la app AirSense MX.

Cada función recibe DataFrames ya preparados y retorna figuras de Plotly
listas para `st.plotly_chart()`. No hace consultas S3 ni lógica de negocio.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from app.config import (
    CONTAMINANTE_NOMBRES,
    CONTAMINANTE_UMBRAL_PCAA,
    CONTAMINANTE_UNIDADES,
    SEMAFORO_COLORES,
)

# Paleta de colores consistente con el semáforo
_COLOR_PRINCIPAL = "#2C7BB6"
_COLOR_INTERVALO = "rgba(44,123,182,0.15)"


def grafico_pronostico_linea(
    df: pd.DataFrame,
    contaminante: str,
    station_id: str,
) -> go.Figure:
    """Gráfico de línea para el pronóstico 1-7 días de un contaminante.

    Muestra valor predicho con intervalo de incertidumbre (p10-p90) y
    una línea horizontal para el umbral PCAA.

    Args:
        df: DataFrame con columnas horizonte_dias, valor_predicho, valor_p10,
            valor_p90. Debe estar ordenado por horizonte_dias.
        contaminante: Código del contaminante ('O3', 'PM25', 'PM10').
        station_id: ID de la estación para el título.

    Returns:
        Figura de Plotly lista para renderizar.
    """
    nombre = CONTAMINANTE_NOMBRES.get(contaminante, contaminante)
    unidad = CONTAMINANTE_UNIDADES.get(contaminante, "")
    umbral = CONTAMINANTE_UMBRAL_PCAA.get(contaminante)

    fig = go.Figure()

    # Intervalo de incertidumbre (sombreado)
    if "valor_p10" in df.columns and "valor_p90" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=pd.concat(
                    [df["horizonte_dias"], df["horizonte_dias"].iloc[::-1]]
                ),
                y=pd.concat([df["valor_p90"], df["valor_p10"].iloc[::-1]]),
                fill="toself",
                fillcolor=_COLOR_INTERVALO,
                line={"color": "rgba(0,0,0,0)"},
                name="Intervalo P10–P90",
                hoverinfo="skip",
            )
        )

    # Línea principal de predicción
    fig.add_trace(
        go.Scatter(
            x=df["horizonte_dias"],
            y=df["valor_predicho"],
            mode="lines+markers",
            name="Pronóstico",
            line={"color": _COLOR_PRINCIPAL, "width": 2.5},
            marker={"size": 8},
            hovertemplate=f"Día %{{x}}: %{{y:.1f}} {unidad}<extra></extra>",
        )
    )

    # Línea del umbral PCAA
    if umbral is not None:
        fig.add_hline(
            y=umbral,
            line_dash="dash",
            line_color="#E74C3C",
            annotation_text=f"Umbral PCAA ({umbral:.0f} {unidad})",
            annotation_position="right",
        )

    fig.update_layout(
        title=f"Pronóstico {nombre} — Estación {station_id}",
        xaxis_title="Días hacia adelante",
        yaxis_title=f"{nombre} ({unidad})",
        xaxis={"tickmode": "linear", "dtick": 1},
        legend={"orientation": "h", "y": -0.2},
        hovermode="x unified",
        margin={"t": 50, "b": 60},
    )
    return fig


def grafico_probabilidad_contingencia(
    df: pd.DataFrame,
    contaminante: str,
) -> go.Figure:
    """Gráfico de barras para la probabilidad de contingencia por horizonte.

    Args:
        df: DataFrame con columnas horizonte_dias, probabilidad_contingencia,
            semaforo. Ya filtrado por estación y contaminante.
        contaminante: Código del contaminante para el título.

    Returns:
        Figura de Plotly.
    """
    nombre = CONTAMINANTE_NOMBRES.get(contaminante, contaminante)
    colores = [
        SEMAFORO_COLORES.get(s, "#CCCCCC") for s in df.get("semaforo", [])
    ]

    fig = go.Figure(
        go.Bar(
            x=df["horizonte_dias"],
            y=df["probabilidad_contingencia"] * 100,
            marker_color=colores if colores else _COLOR_PRINCIPAL,
            text=[f"{v:.0f}%" for v in df["probabilidad_contingencia"] * 100],
            textposition="outside",
            hovertemplate="Día %{x}: %{y:.1f}% de contingencia<extra></extra>",
        )
    )
    fig.add_hline(
        y=50,
        line_dash="dot",
        line_color="#888",
        annotation_text="50% umbral de alerta",
        annotation_position="right",
    )
    fig.update_layout(
        title=f"Probabilidad de Contingencia — {nombre}",
        xaxis_title="Días hacia adelante",
        yaxis_title="Probabilidad (%)",
        yaxis={"range": [0, 110]},
        xaxis={"tickmode": "linear", "dtick": 1},
        margin={"t": 50, "b": 40},
    )
    return fig


def grafico_mapa_calor_zonas(df_resumen: pd.DataFrame) -> go.Figure:
    """Mapa de calor de riesgo por zona y contaminante.

    Args:
        df_resumen: DataFrame con columnas zone, contaminante,
                    probabilidad_contingencia.

    Returns:
        Figura de Plotly tipo heatmap.
    """
    if df_resumen.empty or not {
        "zone",
        "contaminante",
        "probabilidad_contingencia",
    }.issubset(df_resumen.columns):
        return go.Figure()

    pivot = (
        df_resumen.groupby(["zone", "contaminante"])["probabilidad_contingencia"]
        .mean()
        .unstack(fill_value=0)
        * 100
    )

    zona_nombres = {
        "CE": "Centro",
        "NO": "Noroeste",
        "NE": "Noreste",
        "SO": "Suroeste",
        "SE": "Sureste",
    }
    pivot.index = [zona_nombres.get(z, z) for z in pivot.index]

    fig = px.imshow(
        pivot,
        color_continuous_scale=[
            [0, "#2ECC71"],
            [0.35, "#F1C40F"],
            [0.65, "#E67E22"],
            [1, "#E74C3C"],
        ],
        zmin=0,
        zmax=100,
        text_auto=".0f",
        aspect="auto",
        labels={"color": "Prob. Contingencia (%)"},
        title="Probabilidad de Contingencia por Zona y Contaminante (%)",
    )
    fig.update_traces(hovertemplate="%{y} — %{x}: %{z:.1f}%<extra></extra>")
    fig.update_layout(margin={"t": 60, "b": 20})
    return fig
