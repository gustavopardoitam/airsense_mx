"""AirSense MX — Configuración centralizada del proyecto.

Define rutas del repositorio, parámetros de modelo y umbrales de dominio.
Todos los módulos importan esta configuración en lugar de hardcodear valores.

Uso:
    from config import PathsConfig, ContaminantConfig, find_repo_root

    repo_root = find_repo_root(Path(__file__))
    paths = PathsConfig.from_repo_root(repo_root)
    cfg = ContaminantConfig()
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def find_repo_root(start: Path) -> Path:
    """Encuentra el root del proyecto buscando pyproject.toml y data/.

    Args:
        start: Ruta base (típicamente __file__).

    Returns:
        Ruta al root del proyecto.

    Raises:
        RuntimeError: Si no se encuentra el root después de 15 directorios.
    """
    current = start.resolve()
    for _ in range(15):
        if (current / "pyproject.toml").exists() and (current / "data").exists():
            return current
        current = current.parent
    raise RuntimeError(
        "No se encontró el root del proyecto (pyproject.toml + data/). "
        "Ejecuta desde dentro del repositorio."
    )


@dataclass(frozen=True)
class PathsConfig:
    """Rutas estándar del proyecto (inmutable)."""

    repo_root: Path
    data_raw: Path
    data_prep: Path
    data_inference: Path
    artifacts_dir: Path
    logs_dir: Path
    models_dir: Path
    predictions_dir: Path
    reports_dir: Path

    @staticmethod
    def from_repo_root(repo_root: Path) -> PathsConfig:
        """Construye la configuración de rutas a partir del root.

        Args:
            repo_root: Ruta al root del proyecto.

        Returns:
            PathsConfig con todas las rutas configuradas.
        """
        artifacts_dir = repo_root / "artifacts"
        return PathsConfig(
            repo_root=repo_root,
            data_raw=repo_root / "data" / "raw",
            data_prep=repo_root / "data" / "prep",
            data_inference=repo_root / "data" / "inference",
            artifacts_dir=artifacts_dir,
            logs_dir=artifacts_dir / "logs",
            models_dir=artifacts_dir / "models",
            predictions_dir=artifacts_dir / "predictions",
            reports_dir=artifacts_dir / "reports",
        )


@dataclass(frozen=True)
class ContaminantConfig:
    """Parámetros de dominio: thresholds y configuración de features (inmutable).

    Define umbrales NOM-172-SEMARNAT-2019 para contingencias ambientales,
    parámetros de feature engineering y nombres de columnas estándar.
    """

    # Umbrales NOM-172-SEMARNAT-2019 para contingencia fase I (µg/m³ o ppb)
    pm25_threshold_phase1: float = 150.0
    pm10_threshold_phase1: float = 214.0
    o3_threshold_phase1: float = 155.0
    co_threshold_phase1: float = 15.0

    # Split temporal para train/valid
    train_quantile_cutoff: float = 0.8

    # Features de serie de tiempo: lags y rolling windows
    lags: tuple[int, ...] = (1, 3, 6, 24)
    rolls: tuple[int, ...] = (8, 24)

    # Nombres de columnas estándar
    target_col: str = "contingency_phase"
    time_col: str = "timestamp"
    station_col: str = "station_id"
    pollutant_col: str = "pollutant"

    # Dataset de salida del ETL
    dataset_filename: str = "gold_features.parquet"
