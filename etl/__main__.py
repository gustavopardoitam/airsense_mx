"""Entry point para ejecutar el pipeline ETL completo.

Uso:
    python -m etl
"""

from __future__ import annotations

from utils.logging import get_logger, setup_logging

logger = get_logger(__name__)


def main() -> None:
    """Orquestador del pipeline ETL completo.

    Fases:
        1. Bronze: Ingestión desde RAMA/SIMAT, Open-Meteo, PCAA
        2. Silver: Normalización y validación
        3. Gold: Feature engineering y panel analítico

    TODO: Implementar orquestación
    """
    setup_logging()
    logger.info("Iniciando pipeline ETL")
    logger.warning("ETL pipeline no implementado. Placeholder funcional.")


if __name__ == "__main__":
    main()
