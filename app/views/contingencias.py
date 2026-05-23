"""Página: Riesgo de Contingencia Ambiental.

Semáforo simplificado que responde a una sola pregunta:
¿Habrá contingencia en la ZMVM en los próximos días?
Flujo: semáforo global → tira día a día → Bedrock → info PCAA.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.components.cards import aviso_sin_datos
from app.config import (
    CONTAMINANTE_NOMBRES,
    CONTAMINANTE_UNIDADES,
    SEMAFORO_COLORES,
    SEMAFORO_DESCRIPCION,
    SEMAFORO_ETIQUETAS,
    SEMAFORO_ICONOS,
    SEMAFORO_ORDEN,
    ZONAS_NOMBRES,
    ZONAS_ORDEN,
)
from app.data.s3_loader import cargar_predicciones
from app.models.bedrock_explainer import generar_explicacion
from app.models.risk_analyzer import obtener_resumen_zona
from utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# HELPERS PRIVADOS
# =============================================================================


def _semaforo_global(df: pd.DataFrame) -> str:
    """Devuelve el semáforo con mayor riesgo en el DataFrame.

    Args:
        df: DataFrame con columna 'semaforo'.

    Returns:
        Código del semáforo más crítico encontrado, o 'verde' si vacío.
    """
    if df.empty or "semaforo" not in df.columns:
        return "verde"
    idx = df["semaforo"].map(SEMAFORO_ORDEN).fillna(0).idxmax()
    return str(df.loc[idx, "semaforo"])


def _mensaje_accion(semaforo: str) -> str:
    """Devuelve la recomendación accionable para el usuario.

    Args:
        semaforo: Código del nivel de riesgo.

    Returns:
        Cadena con recomendación en español para usuario no técnico.
    """
    mensajes: dict[str, str] = {
        "verde": (
            "✅ Sin restricciones. Actividades al aire libre con normalidad."
        ),
        "amarillo": (
            "⚠️ Grupos sensibles (niños, adultos mayores, personas con "
            "enfermedades respiratorias) deben reducir actividad física "
            "intensa al aire libre."
        ),
        "naranja": (
            "🚫 Se recomienda evitar actividades físicas prolongadas al "
            "aire libre para toda la población."
        ),
        "rojo": (
            "🔴 Alto riesgo de Contingencia Ambiental. Se recomienda "
            "permanecer en interiores y suspender actividades al aire "
            "libre. Siga las alertas de SEDEMA."
        ),
    }
    return mensajes.get(semaforo, "")


def _render_semaforo_principal(
    semaforo: str,
    prob_max: float,
    cont_critico: str,
    zona_critica: str,
) -> None:
    """Renderiza el semáforo principal con mensaje ejecutivo y contexto.

    Args:
        semaforo: Código del semáforo global.
        prob_max: Probabilidad máxima de contingencia (en porcentaje).
        cont_critico: Código del contaminante con mayor riesgo.
        zona_critica: Código de la zona con mayor riesgo.
    """
    color = SEMAFORO_COLORES.get(semaforo, "#CCCCCC")
    etiqueta = SEMAFORO_ETIQUETAS.get(semaforo, semaforo.capitalize())
    icono = SEMAFORO_ICONOS.get(semaforo, "⚪")
    descripcion = SEMAFORO_DESCRIPCION.get(semaforo, "")
    nombre_cont = CONTAMINANTE_NOMBRES.get(cont_critico, cont_critico)
    nombre_zona = ZONAS_NOMBRES.get(zona_critica, zona_critica)
    accion = _mensaje_accion(semaforo)

    st.markdown(
        f"<div style='"
        f"background:linear-gradient(135deg,{color}22 0%,{color}0d 100%);"
        f"border-left:8px solid {color};"
        f"border-radius:12px;"
        f"padding:28px 32px;"
        f"margin:16px 0;"
        f"'>"
        f"<div style='font-size:0.8rem;color:#888;text-transform:uppercase;"
        f"letter-spacing:0.06em;margin-bottom:8px;'>Nivel de riesgo general</div>"
        f"<div style='display:flex;align-items:center;gap:14px;margin-bottom:10px;'>"
        f"<span style='font-size:3rem;'>{icono}</span>"
        f"<span style='font-size:2.4rem;font-weight:700;color:{color};'>"
        f"{etiqueta}</span></div>"
        f"<div style='font-size:1rem;color:#444;margin-bottom:12px;'>"
        f"{descripcion}</div>"
        f"<div style='font-size:0.9rem;color:#555;"
        f"border-top:1px solid {color}33;padding-top:10px;'>"
        f"📍 Mayor riesgo en <b>{nombre_zona}</b> · "
        f"Contaminante: <b>{nombre_cont}</b> · "
        f"Probabilidad máx.: <b>{prob_max:.0f}%</b></div>"
        f"<div style='font-size:0.88rem;color:#333;margin-top:10px;"
        f"font-style:italic;'>{accion}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _render_tira_7dias(df: pd.DataFrame, fechas: list[pd.Timestamp]) -> None:
    """Renderiza la tira horizontal de tarjetas, una por fecha objetivo.

    Cada tarjeta muestra la fecha, semáforo del día (el peor entre todas
    las zonas y contaminantes disponibles) y el nivel en texto.

    Args:
        df: DataFrame con todos los registros de las fechas disponibles.
        fechas: Lista de timestamps a mostrar, en orden ascendente.
    """
    if not fechas:
        return

    cols = st.columns(len(fechas))
    for i, fecha in enumerate(fechas):
        df_dia = df[df["fecha_objetivo"] == fecha]
        sem = _semaforo_global(df_dia)
        color = SEMAFORO_COLORES.get(sem, "#CCCCCC")
        icono = SEMAFORO_ICONOS.get(sem, "⚪")
        etiqueta = SEMAFORO_ETIQUETAS.get(sem, "—")
        label = pd.Timestamp(fecha).strftime("%d %b")
        bg = (
            f"linear-gradient(180deg,{color}33 0%,{color}11 100%)"
            if i == 0
            else f"{color}0d"
        )
        with cols[i]:
            st.markdown(
                f"<div style='border:2px solid {color};"
                f"border-radius:10px;"
                f"padding:12px 4px;"
                f"text-align:center;"
                f"background:{bg};'>"
                f"<div style='font-size:0.72rem;color:#666;"
                f"margin-bottom:4px;'>{label}</div>"
                f"<div style='font-size:1.9rem;'>{icono}</div>"
                f"<div style='font-size:0.68rem;color:{color};"
                f"font-weight:700;margin-top:4px;'>{etiqueta}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )


def _mostrar_zona_cards(df_resumen: pd.DataFrame) -> None:
    """Muestra tarjetas compactas de riesgo por zona.

    Args:
        df_resumen: DataFrame con columnas zone, semaforo,
                    prob_contingencia_max, contaminante_critico.
    """
    cols = st.columns(min(len(df_resumen), 5))
    for i, (_, row) in enumerate(df_resumen.iterrows()):
        zona = row.get("zone", "")
        sem = row.get("semaforo", "verde")
        color = SEMAFORO_COLORES.get(sem, "#CCCCCC")
        icono = SEMAFORO_ICONOS.get(sem, "⚪")
        etiqueta = SEMAFORO_ETIQUETAS.get(sem, "—")
        prob = float(row.get("prob_contingencia_max", 0))
        nombre_zona = ZONAS_NOMBRES.get(zona, zona)
        with cols[i % len(cols)]:
            st.markdown(
                f"<div style='border-left:4px solid {color};"
                f"background:{color}11;"
                f"border-radius:8px;"
                f"padding:12px 14px;"
                f"margin-bottom:6px;'>"
                f"<div style='font-weight:700;font-size:0.95rem;'>"
                f"{nombre_zona}</div>"
                f"<div style='font-size:1.2rem;color:{color};"
                f"font-weight:600;margin:4px 0;'>{icono} {etiqueta}</div>"
                f"<div style='font-size:0.8rem;color:#666;'>"
                f"Prob. contingencia: <b>{prob:.0f}%</b></div>"
                f"</div>",
                unsafe_allow_html=True,
            )


def _mostrar_explicacion_bedrock(
    df_resumen: pd.DataFrame,
    df_datos: pd.DataFrame,
) -> None:
    """Permite obtener una explicación en lenguaje natural vía Bedrock.

    Args:
        df_resumen: DataFrame de resumen por zona.
        df_datos: DataFrame de predicciones del período analizado.
    """
    st.subheader("🤖 Explicación en lenguaje natural")
    st.markdown(
        "Selecciona una zona para recibir una explicación sobre el "
        "riesgo de contingencia."
    )

    if df_resumen.empty or "zone" not in df_resumen.columns:
        st.info("No hay datos para generar una explicación.")
        return

    zonas_disp = df_resumen["zone"].tolist()
    zona_sel = st.selectbox(
        "Zona",
        options=zonas_disp,
        format_func=lambda z: ZONAS_NOMBRES.get(z, z),
        key="zona_bedrock",
    )

    if st.button("Generar explicación", type="primary"):
        fila = df_resumen[df_resumen["zone"] == zona_sel].iloc[0]
        semaforo = str(fila.get("semaforo", "verde"))
        prob = float(fila.get("prob_contingencia_max", 0)) / 100
        subset = (
            df_datos[df_datos["zone"] == zona_sel]
            if not df_datos.empty
            else pd.DataFrame()
        )
        if not subset.empty and "probabilidad_contingencia" in subset.columns:
            fila_c = subset.loc[subset["probabilidad_contingencia"].idxmax()]
            contaminante = str(fila_c.get("contaminante", "O3"))
            valor = float(fila_c.get("valor_predicho", 0))
        else:
            contaminante, valor = "O3", 0.0

        with st.spinner("Consultando Amazon Bedrock…"):
            explicacion = generar_explicacion(
                zona=ZONAS_NOMBRES.get(zona_sel, zona_sel),
                semaforo=semaforo,
                contaminante=CONTAMINANTE_NOMBRES.get(contaminante, contaminante),
                valor=valor,
                unidad=CONTAMINANTE_UNIDADES.get(contaminante, ""),
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
se activa cuando las concentraciones superan umbrales establecidos por la SEDEMA.

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


# =============================================================================
# RENDERIZADO PRINCIPAL
# =============================================================================


def render() -> None:
    """Renderiza la página de Riesgo de Contingencia Ambiental."""
    st.title("⚠️ Riesgo de Contingencia Ambiental")
    st.markdown(
        "¿Habrá **contingencia ambiental** en la ZMVM en los próximos días? "
        "El semáforo resume el riesgo según el modelo predictivo de AirSense MX."
    )

    with st.spinner("Cargando datos…"):
        df_total = cargar_predicciones()

    if df_total.empty:
        aviso_sin_datos()
        _mostrar_informacion_pcaa()
        return

    df_total = df_total.copy()
    df_total["fecha_objetivo"] = pd.to_datetime(df_total["fecha_objetivo"])

    # ── Sidebar: filtro de zona ────────────────────────────────────────
    st.sidebar.subheader("Filtrar por zona")
    zonas_disp = [z for z in ZONAS_ORDEN if z in df_total["zone"].unique()]
    zona_sel: str | None = st.sidebar.selectbox(
        "Zona",
        options=[None, *zonas_disp],
        format_func=lambda z: "Todas las zonas"
        if z is None
        else ZONAS_NOMBRES.get(z, z),
    )

    df_filtrado = (
        df_total[df_total["zone"] == zona_sel].copy()
        if zona_sel
        else df_total.copy()
    )

    fechas_7 = sorted(df_filtrado["fecha_objetivo"].unique())[-7:]
    df_7dias = df_filtrado[df_filtrado["fecha_objetivo"].isin(fechas_7)]

    if df_7dias.empty:
        aviso_sin_datos("No hay datos disponibles para el período seleccionado.")
        _mostrar_informacion_pcaa()
        return

    logger.info(
        "Contingencias consultadas",
        extra={"zona": zona_sel or "todas", "n_fechas": len(fechas_7)},
    )

    # ── Semáforo principal ─────────────────────────────────────────────
    semaforo = _semaforo_global(df_7dias)
    prob_max = float(df_7dias["probabilidad_contingencia"].max()) * 100
    idx_crit = df_7dias["probabilidad_contingencia"].idxmax()
    cont_crit = str(df_7dias.loc[idx_crit, "contaminante"])
    zona_crit = str(df_7dias.loc[idx_crit, "zone"])

    _render_semaforo_principal(semaforo, prob_max, cont_crit, zona_crit)

    st.divider()

    # ── Tira día a día ─────────────────────────────────────────────────
    st.subheader("Día a día")
    _render_tira_7dias(df_7dias, [pd.Timestamp(f) for f in fechas_7])

    st.divider()

    # ── Desglose por zona (solo en vista "todas") ──────────────────────
    df_ultimo = df_7dias[df_7dias["fecha_objetivo"] == max(fechas_7)]
    df_resumen = obtener_resumen_zona(df_ultimo)
    if not df_resumen.empty and zona_sel is None:
        st.subheader("Por zona — período analizado")
        _mostrar_zona_cards(df_resumen)
        st.divider()

    # ── Explicación Bedrock ────────────────────────────────────────────
    _mostrar_explicacion_bedrock(df_resumen, df_ultimo)

    st.divider()
    _mostrar_informacion_pcaa()
