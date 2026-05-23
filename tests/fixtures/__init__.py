"""Fixtures sintéticas para desarrollo y testing.

Genera datos sintéticos que cumplen el contrato de Silver para desarrollar
Gold y el modelo sin depender de Silver real de S3.

Uso:
    from tests.fixtures import generate_silver_fixtures

    obs, meteo = generate_silver_fixtures(seed=42)
"""

from __future__ import annotations


from tests.fixtures.generate_synthetic_silver import generate_silver_fixtures

__all__ = ["generate_silver_fixtures"]


