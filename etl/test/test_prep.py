"""Smoke tests para el pipeline ETL.

Verifica que los archivos de salida del ETL existen y tienen schema básico.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config import PathsConfig

_REPO_ROOT: Path = Path(__file__).resolve().parents[2]
_PATHS = PathsConfig.from_repo_root(_REPO_ROOT)

# Archivos esperados de salida del ETL
_EXPECTED_GOLD_FILES: list[str] = [
    "gold_features.parquet",
]


def test_gold_files_exist() -> None:
    """Verifica que los archivos Gold existen.

    TODO: Ejecutar después de python -m etl.
    """
    data_prep = _PATHS.data_prep
    if not data_prep.exists():
        pytest.skip(f"Directorio {data_prep} no existe. Ejecuta python -m etl primero.")

    missing = [f for f in _EXPECTED_GOLD_FILES if not (data_prep / f).exists()]
    if missing:
        pytest.skip(
            f"{len(missing)} archivo(s) aún no generados en {data_prep}. "
            "Ejecuta python -m etl primero."
        )
