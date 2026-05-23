"""Evaluación del modelo contra el golden set del PCAA-SEDEMA.

Este paquete contiene:
    - golden_set: parser del PDF oficial de contingencias PCAA con mapeo
      auditado de nombres PDF → station_id SIMAT.
    - metrics: métricas zonal y por estación (recall, precision, F1,
      lead time) comparando predicciones del modelo vs golden set.

API pública:
    from evaluation import cargar_golden_set, evaluar_modelo

Uso típico:
    from evaluation import cargar_golden_set, evaluar_modelo

    golden = cargar_golden_set("data/raw/pcaa.pdf", fecha_inicio="2025-10-01")
    resultado = evaluar_modelo(predicciones, golden, horizonte_dias=1)
    resultado.imprimir_resumen()
"""

from __future__ import annotations


from evaluation.golden_set import (
    ESTACION_PDF_A_SIMAT,
    cargar_golden_set,
    mapear_estacion_a_station_id,
    parsear_pdf_pcaa,
)
from evaluation.metrics import (
    MetricasBinarias,
    ResultadoEvaluacion,
    evaluar_modelo,
    evaluar_multi_horizonte,
)

__all__ = [
    # golden_set
    "ESTACION_PDF_A_SIMAT",
    "cargar_golden_set",
    "mapear_estacion_a_station_id",
    "parsear_pdf_pcaa",
    # metrics
    "MetricasBinarias",
    "ResultadoEvaluacion",
    "evaluar_modelo",
    "evaluar_multi_horizonte",
]

