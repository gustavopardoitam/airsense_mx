"""AirSense MX — Configuración de la capa de presentación Streamlit.

Constantes de UI: colores semáforo, etiquetas, nombres de contaminantes
y parámetros de comportamiento de la app. No contiene lógica de negocio.
"""

from __future__ import annotations

# =============================================================================
# SEMÁFORO DE CALIDAD DEL AIRE
# Basado en los valores del contrato de datos (gold.predicciones_diarias)
# y la paleta visual definida en copilot-instructions.md
# =============================================================================

SEMAFORO_COLORES: dict[str, str] = {
    "verde": "#2ECC71",
    "amarillo": "#F1C40F",
    "naranja": "#E67E22",
    "rojo": "#E74C3C",
}

SEMAFORO_ETIQUETAS: dict[str, str] = {
    "verde": "Buena",
    "amarillo": "Aceptable",
    "naranja": "Mala",
    "rojo": "Muy mala",
}

SEMAFORO_ICONOS: dict[str, str] = {
    "verde": "🟢",
    "amarillo": "🟡",
    "naranja": "🟠",
    "rojo": "🔴",
}

SEMAFORO_DESCRIPCION: dict[str, str] = {
    "verde": "No se esperan afectaciones a la salud.",
    "amarillo": "Grupos sensibles deben reducir actividad intensa al aire libre.",
    "naranja": "Evitar actividades prolongadas al aire libre.",
    "rojo": "Contingencia ambiental activa. Evitar salir.",
}

# Orden para ordenar de mejor a peor
SEMAFORO_ORDEN: dict[str, int] = {
    "verde": 0,
    "amarillo": 1,
    "naranja": 2,
    "rojo": 3,
}

# =============================================================================
# CONTAMINANTES
# =============================================================================

CONTAMINANTE_NOMBRES: dict[str, str] = {
    "O3": "Ozono",
    "PM25": "Part. PM2.5",
    "PM10": "Part. PM10",
}

CONTAMINANTE_NOMBRES_COMPLETOS: dict[str, str] = {
    "O3": "Ozono (O₃)",
    "PM25": "Partículas finas PM2.5",
    "PM10": "Partículas gruesas PM10",
}

CONTAMINANTE_UNIDADES: dict[str, str] = {
    "O3": "ppb",
    "PM25": "µg/m³",
    "PM10": "µg/m³",
}

CONTAMINANTE_UMBRAL_PCAA: dict[str, float] = {
    "O3": 140.0,  # ppb, máx 1h
    "PM25": 79.0,  # µg/m³, prom 24h
    "PM10": 146.0,  # µg/m³, prom 24h
}

# Contaminantes predichos en v1.0 (según contrato Gold)
CONTAMINANTES_PREDICHOS: list[str] = ["O3", "PM25", "PM10"]

# =============================================================================
# ZONAS DE LA ZMVM
# =============================================================================

ZONAS_NOMBRES: dict[str, str] = {
    "NO": "Noroeste",
    "NE": "Noreste",
    "SE": "Sureste",
    "SO": "Suroeste",
    "CE": "Centro",
}

ZONAS_ORDEN: list[str] = ["CE", "NO", "NE", "SO", "SE"]

# =============================================================================
# RUTAS S3
# =============================================================================

GOLD_S3_PATH: str = (
    "s3://itam-analytics-antonio/air-sense-mx/gold/predicciones_diarias/"
)

# =============================================================================
# COMPORTAMIENTO DE LA APP
# =============================================================================

CACHE_TTL_SEGUNDOS: int = 300  # 5 minutos
HORIZONTE_MAX_DIAS: int = 7
BEDROCK_REGION: str = "us-east-1"
BEDROCK_MODEL_ID: str = "anthropic.claude-haiku-20240307-v1:0"
BEDROCK_MAX_TOKENS: int = 512
