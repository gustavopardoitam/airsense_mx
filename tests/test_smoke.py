"""Smoke tests del proyecto.

Verifica que módulos pueden importarse y structuras básicas existen.
"""

from __future__ import annotations

from pathlib import Path

from config import ContaminantConfig, PathsConfig, find_repo_root


def test_config_importable() -> None:
    """Verifica que config.py puede importarse sin errores."""
    assert ContaminantConfig is not None
    assert PathsConfig is not None


def test_find_repo_root() -> None:
    """Verifica que find_repo_root() funciona desde varios puntos."""
    repo_root = find_repo_root(Path(__file__))
    assert repo_root.exists()
    assert (repo_root / "pyproject.toml").exists()
    assert (repo_root / "data").exists()


def test_paths_config_from_repo_root() -> None:
    """Verifica que PathsConfig se construye correctamente."""
    repo_root = find_repo_root(Path(__file__))
    paths = PathsConfig.from_repo_root(repo_root)
    assert paths.repo_root.exists()
    assert paths.artifacts_dir.exists()


def test_contaminant_config_defaults() -> None:
    """Verifica que ContaminantConfig tiene valores por defecto válidos."""
    cfg = ContaminantConfig()
    assert cfg.pm25_threshold_phase1 == 150.0
    assert cfg.train_quantile_cutoff == 0.8
    assert len(cfg.lags) == 4
    assert len(cfg.rolls) == 2
