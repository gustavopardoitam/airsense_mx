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


# =============================================================================
# HISTÓRICO CON DRILL-DOWN GEOGRÁFICO
# =============================================================================

_ZMVM_CENTRO: dict[str, float] = {"lat": 19.43, "lon": -99.13}


def grafico_tendencia_historica(
    df: pd.DataFrame,
    col_valor: str,
    titulo_y: str,
    color_col: str,
    titulo: str,
    umbral: float | None = None,
) -> go.Figure:
    """Gráfico de tendencia histórica diaria con rangeslider para zoom.

    Soporta vista por zona (nivel 1) o por estación dentro de una zona
    (nivel 2 — drill-down). El rangeslider inferior permite hacer zoom
    a períodos específicos sin perder el contexto temporal completo.

    Args:
        df: DataFrame con columnas 'fecha', col_valor y color_col.
        col_valor: Columna numérica a graficar (ej. 'o3_max_1h').
        titulo_y: Etiqueta del eje Y con unidad.
        color_col: Columna para colorear líneas ('zone' o 'station_id').
        titulo: Título del gráfico.
        umbral: Valor del umbral PCAA para trazar línea de referencia.

    Returns:
        Figura de Plotly con rangeslider y zoom habilitados.
    """
    df_sorted = df.sort_values("fecha")
    fig = px.line(
        df_sorted,
        x="fecha",
        y=col_valor,
        color=color_col,
        title=titulo,
        labels={"fecha": "Fecha", col_valor: titulo_y, color_col: ""},
    )
    if umbral is not None:
        fig.add_hline(
            y=umbral,
            line_dash="dash",
            line_color="#E74C3C",
            annotation_text=f"Umbral PCAA ({umbral:.0f})",
            annotation_position="right",
        )
    fig.update_layout(
        hovermode="x unified",
        xaxis={"rangeslider": {"visible": True}, "type": "date"},
        legend={"orientation": "h", "y": -0.35},
        margin={"t": 50, "b": 100},
        height=450,
    )
    return fig


def grafico_pronostico_por_fecha(
    df: pd.DataFrame,
    contaminante: str,
    station_name: str,
) -> go.Figure:
    """Línea de pronóstico con banda de incertidumbre usando fechas reales.

    Muestra el valor predicho diario con su intervalo p10-p90 sombreado
    y una línea punteada para el umbral PCAA. El eje X usa fechas
    reales (fecha_objetivo) en lugar de horizonte numérico.

    Args:
        df: DataFrame con columnas fecha_objetivo, valor_predicho,
            valor_p10, valor_p90, umbral_contingencia. Ordenado por fecha.
        contaminante: Código del contaminante ('O3', 'PM25', 'PM10').
        station_name: Nombre legible de la estación para el título.

    Returns:
        Figura de Plotly lista para renderizar.
    """
    nombre = CONTAMINANTE_NOMBRES.get(contaminante, contaminante)
    unidad = CONTAMINANTE_UNIDADES.get(contaminante, "")
    umbral_col = df["umbral_contingencia"].dropna()
    umbral = (
        float(umbral_col.iloc[0])
        if not umbral_col.empty
        else CONTAMINANTE_UMBRAL_PCAA.get(contaminante)
    )

    fig = go.Figure()

    if "valor_p10" in df.columns and "valor_p90" in df.columns:
        fechas_inv = df["fecha_objetivo"].iloc[::-1]
        vals_inv = df["valor_p10"].iloc[::-1]
        fig.add_trace(
            go.Scatter(
                x=pd.concat([df["fecha_objetivo"], fechas_inv]),
                y=pd.concat([df["valor_p90"], vals_inv]),
                fill="toself",
                fillcolor="rgba(44,123,182,0.12)",
                line={"color": "rgba(0,0,0,0)"},
                name="Intervalo P10–P90",
                hoverinfo="skip",
            )
        )

    fig.add_trace(
        go.Scatter(
            x=df["fecha_objetivo"],
            y=df["valor_predicho"],
            mode="lines+markers",
            name="Valor predicho",
            line={"color": "#2C7BB6", "width": 2.5},
            marker={"size": 7, "color": "#2C7BB6"},
            hovertemplate=(
                "%{x|%d %b %Y}: <b>%{y:.1f} " + unidad + "</b><extra></extra>"
            ),
        )
    )

    if umbral is not None:
        fig.add_hline(
            y=umbral,
            line_dash="dash",
            line_color="#E74C3C",
            line_width=1.5,
            annotation_text=f"Umbral PCAA {umbral:.0f} {unidad}",
            annotation_position="right",
            annotation_font_size=11,
        )

    fig.update_layout(
        title=f"Pronóstico de {nombre} — {station_name}",
        xaxis_title="Fecha",
        yaxis_title=f"{nombre} ({unidad})",
        hovermode="x unified",
        xaxis={
            "rangeslider": {"visible": True},
            "type": "date",
            "tickformat": "%d %b",
        },
        legend={"orientation": "h", "y": -0.35},
        margin={"t": 60, "b": 100},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=440,
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(0,0,0,0.06)")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(0,0,0,0.06)")
    return fig


def grafico_prob_por_fecha(
    df: pd.DataFrame,
    contaminante: str,
) -> go.Figure:
    """Barras de probabilidad de contingencia por fecha objetivo.

    Cada barra representa la probabilidad de superar el umbral PCAA,
    coloreada según el semáforo. Incluye línea de referencia al 30%.

    Args:
        df: DataFrame con columnas fecha_objetivo, probabilidad_contingencia,
            semaforo. Ordenado por fecha_objetivo.
        contaminante: Código del contaminante para el título.

    Returns:
        Figura de Plotly.
    """
    nombre = CONTAMINANTE_NOMBRES.get(contaminante, contaminante)
    colores = [
        SEMAFORO_COLORES.get(str(s), "#CCCCCC")
        for s in df.get("semaforo", pd.Series(dtype=str))
    ]
    probs = df["probabilidad_contingencia"] * 100

    fig = go.Figure(
        go.Bar(
            x=df["fecha_objetivo"],
            y=probs,
            marker_color=colores if colores else _COLOR_PRINCIPAL,
            text=[f"{v:.0f}%" for v in probs],
            textposition="outside",
            hovertemplate=(
                "%{x|%d %b %Y}: <b>%{y:.1f}%</b> de probabilidad<extra></extra>"
            ),
        )
    )
    fig.add_hline(
        y=30,
        line_dash="dot",
        line_color="#888888",
        annotation_text="30 % — umbral de alerta",
        annotation_position="right",
        annotation_font_size=10,
    )
    fig.update_layout(
        title=f"Probabilidad de contingencia — {nombre}",
        xaxis={"tickformat": "%d %b", "type": "date"},
        yaxis={"range": [0, 115], "ticksuffix": "%"},
        margin={"t": 50, "b": 40},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=320,
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(showgrid=True, gridcolor="rgba(0,0,0,0.06)")
    return fig


def grafico_ranking_estaciones_zona(
    df: pd.DataFrame,
    contaminante: str,
    zona_nombre: str,
) -> go.Figure:
    """Ranking horizontal top-10 estaciones por probabilidad de contingencia.

    Ordena estaciones de mayor a menor riesgo dentro de la zona y
    contaminante seleccionados. Colorea cada barra por semáforo.

    Args:
        df: DataFrame con station_id, station_name (si existe),
            probabilidad_contingencia y semaforo. Ya filtrado por zona
            y contaminante.
        contaminante: Código del contaminante para el título.
        zona_nombre: Nombre legible de la zona para el título.

    Returns:
        Figura de Plotly de barras horizontales.
    """
    nombre = CONTAMINANTE_NOMBRES.get(contaminante, contaminante)
    name_col = "station_name" if "station_name" in df.columns else "station_id"

    top = (
        df.groupby("station_id", as_index=False)
        .agg(
            label=(name_col, "first"),
            prob=("probabilidad_contingencia", "max"),
            semaforo=("semaforo", "first"),
        )
        .sort_values("prob", ascending=True)
        .tail(10)
    )

    colores = [
        SEMAFORO_COLORES.get(str(s), "#CCCCCC") for s in top["semaforo"]
    ]

    fig = go.Figure(
        go.Bar(
            x=top["prob"] * 100,
            y=top["label"],
            orientation="h",
            marker_color=colores,
            text=[f"{v:.0f}%" for v in top["prob"] * 100],
            textposition="outside",
            hovertemplate="<b>%{y}</b>: %{x:.1f}%<extra></extra>",
        )
    )
    fig.update_layout(
        title=f"Top estaciones — {nombre} en {zona_nombre}",
        xaxis={
            "title": "Probabilidad de contingencia (%)",
            "range": [0, 115],
            "ticksuffix": "%",
        },
        yaxis={"title": ""},
        margin={"t": 50, "b": 40, "l": 10},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=max(280, len(top) * 40),
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(0,0,0,0.06)")
    fig.update_yaxes(showgrid=False)
    return fig


def grafico_mapa_estaciones(
    df_geo: pd.DataFrame,
    col_valor: str,
    titulo_color: str,
) -> go.Figure:
    """Mapa de dispersión de estaciones RAMA coloreadas por nivel de contaminante.

    Usa open-street-map como fondo (sin API key requerida). El color de
    cada punto sigue la escala del semáforo (verde → rojo). Soporta
    zoom con scroll y arrastre del mapa.

    Args:
        df_geo: DataFrame con latitude, longitude, station_name y col_valor.
        col_valor: Columna con el valor del contaminante.
        titulo_color: Etiqueta para la barra de color y el título.

    Returns:
        Figura de Plotly scatter_mapbox centrada en la ZMVM.
    """
    cols_req = {"latitude", "longitude", col_valor}
    if df_geo.empty or not cols_req.issubset(df_geo.columns):
        return go.Figure()

    hover_name = "station_name" if "station_name" in df_geo.columns else None
    hover_extra = {"latitude": False, "longitude": False, col_valor: ":.1f"}
    if "zone" in df_geo.columns:
        hover_extra["zone"] = True

    df_valid = df_geo.dropna(subset=["latitude", "longitude", col_valor])
    fig = px.scatter_mapbox(
        df_valid,
        lat="latitude",
        lon="longitude",
        color=col_valor,
        hover_name=hover_name,
        hover_data=hover_extra,
        color_continuous_scale=[
            [0.0, "#2ECC71"],
            [0.35, "#F1C40F"],
            [0.65, "#E67E22"],
            [1.0, "#E74C3C"],
        ],
        size_max=18,
        zoom=9,
        center=_ZMVM_CENTRO,
        mapbox_style="open-street-map",
        title=f"Distribución geográfica — {titulo_color}",
    )
    fig.update_layout(
        margin={"t": 50, "b": 0},
        height=480,
        coloraxis_colorbar={"title": titulo_color},
    )
    return fig
