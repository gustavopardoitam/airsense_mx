"""Schema de base de datos RDS para AirSense MX.

Tablas definidas con SQLAlchemy Core (no ORM).

Uso:
    from sqlalchemy import create_engine
    from db.schema import metadata, stations, predictions

    engine = create_engine("postgresql+psycopg://...")
    metadata.create_all(engine)

Todo:
    - Implementar todas las tablas
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
)

metadata = MetaData()

# Catálogo de estaciones
stations = Table(
    "stations",
    metadata,
    Column("station_id", String(10), primary_key=True),
    Column("station_name", String(200), nullable=False),
    Column("municipality", String(100), nullable=False),
    Column("latitude", Float, nullable=True),
    Column("longitude", Float, nullable=True),
)

# Predicciones
predictions = Table(
    "predictions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("station_id", String(10), ForeignKey("stations.station_id")),
    Column("pollutant", String(10), nullable=False),
    Column("forecast_date", String(10), nullable=False),
    Column("predicted_value", Float, nullable=False),
    Column("actual_value", Float, nullable=True),
    Column("contingency_phase", Integer, nullable=True),
    Column("created_at", DateTime, nullable=False),
)

# Métricas de evaluación
metrics = Table(
    "metrics",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("pollutant", String(10), nullable=False),
    Column("station_id", String(10), nullable=True),
    Column("n_obs", Integer, nullable=False),
    Column("mae", Float, nullable=False),
    Column("rmse", Float, nullable=False),
    Column("mae_naive", Float, nullable=False),
    Column("rmse_naive", Float, nullable=False),
    Column("computed_at", DateTime, nullable=False),
)
