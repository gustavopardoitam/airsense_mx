"""Inicialización de base de datos.

Todo:
    - Crear tablas
    - Cargar catálogos
"""

from __future__ import annotations

from utils.logging import get_logger

logger = get_logger(__name__)


def init_db() -> None:
    """Crea todas las tablas en RDS.

    TODO: Implementar
        1. Conectar a RDS (desde Secrets Manager)
        2. Crear tablas desde schema.py
    """
    logger.info("TODO: init_db()")
