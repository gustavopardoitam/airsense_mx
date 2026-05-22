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
import logging.handlers
import sys
from pathlib import Path

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(module)s | %(message)s"
DEFAULT_LOG_DIR = Path("logs")
_LOGGER_INITIALIZED = False


def setup_logging(
    level: int = logging.INFO,
    log_dir: Path | None = DEFAULT_LOG_DIR,
) -> None:
    """Configura el logger raíz con salida a stdout y archivo rotado diariamente.

    Debe llamarse exactamente una vez en el entry point de la aplicación,
    antes de cualquier otro logging.

    Args:
        level: Nivel de logging (INFO, DEBUG, WARNING, ERROR).
        log_dir: Directorio donde guardar los archivos de log. Si es None,
            solo escribe a stdout (comportamiento anterior). Por defecto
            escribe en ``logs/airsense.log`` con rotación diaria (7 días).

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
    root_logger.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT)

    # Handler 1: stdout
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    root_logger.addHandler(stdout_handler)

    # Handler 2: archivo con rotación diaria (opcional)
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=log_dir / "airsense.log",
            when="midnight",
            backupCount=7,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

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
