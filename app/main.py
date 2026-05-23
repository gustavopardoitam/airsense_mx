"""AirSense MX — Aplicación principal de Streamlit.

Punto de entrada de la aplicación. Maneja la navegación entre páginas
y el setup de configuración centralizada. La lógica de negocio vive en
app/pages/ y app/components/.

Para ejecutar localmente:
    uv run streamlit run app/main.py
"""

from __future__ import annotations

import streamlit as st

from utils.logging import get_logger, setup_logging

logger = get_logger(__name__)

_PAGINAS = {
    "Panel de Calidad del Aire": "dashboard",
    "Pronóstico de Contaminantes": "pronostico",
    "Riesgo de Contingencia": "contingencias",
}

_ICONOS = {
    "Panel de Calidad del Aire": "🌫️",
    "Pronóstico de Contaminantes": "📈",
    "Riesgo de Contingencia": "⚠️",
}


def main() -> None:
    """Inicializa la aplicación y delega a las páginas correspondientes.

    Setup:
        1. Configura logging centralizado (una sola vez).
        2. Configura la página Streamlit.
        3. Presenta menú lateral con navegación en español.
        4. Importa y delega al módulo de página seleccionado.
    """
    setup_logging()
    logger.info("Iniciando AirSense MX")

    st.set_page_config(
        page_title="AirSense MX",
        page_icon="🌫️",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Sidebar
    with st.sidebar:
        st.title("🌫️ AirSense MX")
        st.caption("Calidad del aire en la ZMVM")
        st.markdown("---")

        page = st.radio(
            "Navegación",
            options=list(_PAGINAS.keys()),
            format_func=lambda p: f"{_ICONOS.get(p, '')} {p}",
            label_visibility="collapsed",
        )

        st.markdown("---")
        st.caption("Datos: SIMAT/RAMA · Open-Meteo")
        st.caption("Modelo: LightGBM v1.0")
        st.caption("Zona horaria: CDMX UTC-6")

    logger.info("Página seleccionada", extra={"page": page})

    # Enrutamiento: importa y llama render() de la página seleccionada
    modulo = _PAGINAS.get(page, "dashboard")
    try:
        if modulo == "dashboard":
            from app.views.dashboard import render
        elif modulo == "pronostico":
            from app.views.pronostico import render
        elif modulo == "contingencias":
            from app.views.contingencias import render
        else:
            render = _pagina_no_encontrada  # type: ignore[assignment]

        render()
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Error renderizando página",
            extra={"page": page, "error": str(exc)},
        )
        st.error(
            "Ocurrió un problema al cargar esta página. "
            "Por favor intenta de nuevo o contacta al equipo."
        )


def _pagina_no_encontrada() -> None:
    """Muestra mensaje amigable para páginas no implementadas."""
    st.info("🚧 Esta sección está en desarrollo. Vuelve pronto.")


if __name__ == "__main__":
    main()
