"""AirSense MX — Aplicación principal de Streamlit.

Punto de entrada de la aplicación. Maneja navegación entre páginas y
setup de configuración centralizada. La lógica de negocio vive en
app/pages/ y app/components/.

Para ejecutar localmente:
    uv run streamlit run app/main.py
"""

from __future__ import annotations

import streamlit as st

from utils.logging import get_logger, setup_logging

logger = get_logger(__name__)


def main() -> None:
    """Inicializa la aplicación y maneja la navegación entre páginas.

    Setup:
        1. Configura logging centralizado
        2. Define página principal de Streamlit
        3. Presenta menu lateral con navegación en español
        4. Delega a módulos de página específicos
    """
    setup_logging()
    logger.info("Iniciando AirSense MX")

    st.set_page_config(
        page_title="AirSense MX",
        page_icon="🌫️",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.sidebar.title("🌫️ AirSense MX")
    st.sidebar.markdown("---")

    # Menú de navegación en español
    page = st.sidebar.radio(
        "Menú Principal",
        [
            "Panel de Calidad del Aire",
            "Pronóstico de Contaminantes",
            "Riesgo de Contingencia",
            "Recomendaciones",
        ],
    )

    logger.info("Página seleccionada: %s", page)

    # Placeholder para páginas (serán implementadas después)
    st.markdown(f"# {page}")
    st.info("🚧 Página en desarrollo. Vuelve pronto.")


if __name__ == "__main__":
    main()
