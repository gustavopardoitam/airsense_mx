"""Logging estructurado y centralizado para AirSense MX.

Configuración única de logger en toda la aplicación para garantizar
salidas consistentes en CloudWatch y logs locales.

Uso:
    from utils.logging import setup_logging, get_logger

    # En el entry point (main.py, __main__.py)
    setup_logging()

    # En cualquier módulo
    logger = get_logger(__name__)
    logger.info("Mensaje con contexto", extra={"station_id": "XAL", "rows": 100})
"""

from __future__ import annotations

import logging
import sys

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(module)s | %(message)s"
_LOGGER_INITIALIZED = False


def setup_logging(level: int = logging.INFO) -> None:
    """Configura el logger raíz para logging estructurado compatible con CloudWatch.

    Debe llamarse exactamente una vez en el entry point de la aplicación,
    antes de cualquier otro logging.

    Args:
        level: Nivel de logging (INFO, DEBUG, WARNING, ERROR).

    Example:
        >>> setup_logging()
        >>> logger = get_logger(__name__)
        >>> logger.info("Aplicación iniciada")
    """
    global _LOGGER_INITIALIZED
    if _LOGGER_INITIALIZED:
        return
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    # Reducir verbosidad de librerías externas
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    _LOGGER_INITIALIZED = True


def get_logger(name: str | None = None) -> logging.Logger:
    """Obtiene un logger configurado con el nombre del módulo.

    Asegúrate de llamar setup_logging() en el entry point antes de usar esto.

    Args:
        name: Nombre del logger (típicamente __name__).
              Si es None, retorna el logger raíz.

    Returns:
        Logger configurado.

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.warning("Estación sin datos", extra={"station_id": "XAL"})
    """
    return logging.getLogger(name)
