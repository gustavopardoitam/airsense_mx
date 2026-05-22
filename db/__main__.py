"""Entry point para inicializar base de datos.

Uso:
    python -m db

Todo:
    - Crear todas las tablas
    - Cargar catálogos iniciales (estaciones, contaminantes)
    - Cargar predicciones iniciales
"""

from __future__ import annotations

from utils.logging import get_logger, setup_logging

logger = get_logger(__name__)


def main() -> None:
    """Inicializa la base de datos RDS.

    TODO: Implementar
        1. Conectar a RDS
        2. Crear todas las tablas desde schema.py
        3. Cargar catálogos iniciales
    """
    setup_logging()
    logger.info("Inicializando base de datos")
    logger.warning("DB initialization no implementado. Placeholder funcional.")


if __name__ == "__main__":
    main()
