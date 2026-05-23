"""Métricas de evaluación del modelo contra el golden set del PCAA.

Compara las predicciones del modelo (gold.predicciones_diarias) contra las
contingencias reales documentadas por SEDEMA (golden set parseado del PDF
oficial), produciendo métricas operacionales útiles para reportar en la
presentación final.

DOS EVALUACIONES COMPLEMENTARIAS
================================

1. EVALUACIÓN ZONAL (primaria)
   Para cada contingencia real (fecha, zona, contaminante):
   ¿Alguna estación de esa zona predijo cruce del umbral en esa fecha?

   Esta es la métrica que vende: refleja cómo SEDEMA activa contingencias
   (a nivel zonal) y cómo el producto alerta al usuario final (por zona).

2. EVALUACIÓN POR ESTACIÓN (rigurosa)
   Para cada contingencia con station_id mapeado (excluyendo "unknown"):
   ¿La predicción del modelo para esa station_id específica cruzó umbral?

   Esta es más estricta. Penaliza al modelo si predice contingencia en
   la zona correcta pero en la estación incorrecta.

MÉTRICAS REPORTADAS
===================
- Recall: % de contingencias reales detectadas (lo más importante)
- Precision: % de predicciones positivas que fueron reales (falsas alarmas)
- F1: balance entre las anteriores
- Confusion matrix: TP/FP/FN (excluimos TN; no usamos accuracy por
  desbalance — la mayoría de días-estaciones-contaminantes son negativos)
- Lead time promedio: días de anticipación en los TP
- Detalle por evento: para cada contingencia del golden set, si fue
  acertada y con qué confianza

DECISIONES DE DISEÑO
====================
- Predicción positiva = probabilidad_contingencia >= threshold (default 0.5).
  Configurable para curvas precision-recall.
- Agregación zonal: una zona se considera "alerta positiva" si CUALQUIER
  estación de la zona supera el threshold para ese contaminante.
- Manejo de NULLs en predicciones: si la predicción es NaN (estación con
  outage), se omite — no cuenta como FN ni como TN.
- Eventos con mapeo unknown: se incluyen en evaluación zonal, se excluyen
  de evaluación por estación.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTES
# =============================================================================

# Threshold default para considerar "predicción positiva"
THRESHOLD_DEFAULT = 0.5

# Contaminantes evaluados (los que el modelo predice en gold)
CONTAMINANTES_EVAL = ["O3", "PM25", "PM10"]


# =============================================================================
# ESTRUCTURAS DE RESULTADOS
# =============================================================================

@dataclass
class MetricasBinarias:
    """Métricas binarias de clasificación para una evaluación específica."""

    tp: int = 0
    fp: int = 0
    fn: int = 0
    lead_time_dias: list[int] = field(default_factory=list)

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom > 0 else float("nan")

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom > 0 else float("nan")

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        if pd.isna(p) or pd.isna(r) or (p + r) == 0:
            return float("nan")
        return 2 * p * r / (p + r)

    @property
    def lead_time_promedio(self) -> float:
        return float(np.mean(self.lead_time_dias)) if self.lead_time_dias else float("nan")

    def como_dict(self) -> dict:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "recall": round(self.recall, 4) if not pd.isna(self.recall) else None,
            "precision": round(self.precision, 4) if not pd.isna(self.precision) else None,
            "f1": round(self.f1, 4) if not pd.isna(self.f1) else None,
            "lead_time_promedio_dias": (
                round(self.lead_time_promedio, 2)
                if not pd.isna(self.lead_time_promedio) else None
            ),
            "n_eventos_evaluados": self.tp + self.fn,
        }


@dataclass
class ResultadoEvaluacion:
    """Resultado completo de evaluar el modelo contra el golden set."""

    zonal: MetricasBinarias = field(default_factory=MetricasBinarias)
    por_estacion: MetricasBinarias = field(default_factory=MetricasBinarias)
    eventos_detalle: pd.DataFrame = field(default_factory=pd.DataFrame)
    falsas_alarmas: pd.DataFrame = field(default_factory=pd.DataFrame)
    horizonte_dias: int = 1
    threshold: float = THRESHOLD_DEFAULT
    n_eventos_golden: int = 0
    n_eventos_excluidos_mapeo: int = 0

    def resumen(self) -> dict:
        return {
            "horizonte_dias": self.horizonte_dias,
            "threshold": self.threshold,
            "n_eventos_golden": self.n_eventos_golden,
            "n_eventos_excluidos_mapeo": self.n_eventos_excluidos_mapeo,
            "zonal": self.zonal.como_dict(),
            "por_estacion": self.por_estacion.como_dict(),
        }

    def imprimir_resumen(self) -> None:
        """Imprime un resumen legible para revisar en notebook o terminal."""
        r = self.resumen()
        print(f"=" * 60)
        print(f"EVALUACIÓN AirSense MX — horizonte {self.horizonte_dias} día(s)")
        print(f"=" * 60)
        print(f"Threshold de probabilidad: {self.threshold}")
        print(f"Eventos en golden set:     {self.n_eventos_golden}")
        if self.n_eventos_excluidos_mapeo > 0:
            print(f"  Excluidos por mapeo:     {self.n_eventos_excluidos_mapeo}")

        print(f"\n--- MÉTRICA ZONAL (primaria) ---")
        z = r["zonal"]
        print(f"  Recall:    {z['recall']}")
        print(f"  Precision: {z['precision']}")
        print(f"  F1:        {z['f1']}")
        print(f"  TP={z['tp']}, FP={z['fp']}, FN={z['fn']}")
        print(f"  Lead time promedio: {z['lead_time_promedio_dias']} días")

        print(f"\n--- MÉTRICA POR ESTACIÓN (rigurosa) ---")
        e = r["por_estacion"]
        print(f"  Recall:    {e['recall']}")
        print(f"  Precision: {e['precision']}")
        print(f"  F1:        {e['f1']}")
        print(f"  TP={e['tp']}, FP={e['fp']}, FN={e['fn']}")
        print(f"  Lead time promedio: {e['lead_time_promedio_dias']} días")


# =============================================================================
# VALIDACIÓN DE INPUTS
# =============================================================================

REQUIRED_COLS_PREDICCIONES = [
    "fecha_prediccion", "fecha_objetivo", "horizonte_dias",
    "station_id", "zone", "contaminante",
    "valor_predicho", "probabilidad_contingencia",
]

REQUIRED_COLS_GOLDEN = [
    "fecha_activacion", "contaminante", "zona",
    "station_id_activacion", "mapeo_calidad_activacion",
]


def _validar_predicciones(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLS_PREDICCIONES if c not in df.columns]
    if missing:
        raise ValueError(
            f"Faltan columnas en predicciones: {missing}. "
            f"Esperado: {REQUIRED_COLS_PREDICCIONES}"
        )


def _validar_golden(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLS_GOLDEN if c not in df.columns]
    if missing:
        raise ValueError(
            f"Faltan columnas en golden set: {missing}. "
            f"Esperado: {REQUIRED_COLS_GOLDEN}"
        )


# =============================================================================
# EVALUACIÓN ZONAL
# =============================================================================

def _evaluar_zonal(
    predicciones: pd.DataFrame,
    golden_set: pd.DataFrame,
    horizonte_dias: int,
    threshold: float,
) -> tuple[MetricasBinarias, pd.DataFrame]:
    """Evalúa el modelo a nivel (fecha, zona, contaminante)."""
    metricas = MetricasBinarias()

    # Filtrar predicciones al horizonte de interés
    pred_horizonte = predicciones[
        predicciones["horizonte_dias"] == horizonte_dias
    ].copy()

    # Para cada fecha objetivo, identificar qué zonas predijo el modelo
    # como "alerta" (cualquier estación de la zona con prob >= threshold).
    pred_horizonte["alerta_modelo"] = (
        pred_horizonte["probabilidad_contingencia"] >= threshold
    )
    alertas_zonales = (
        pred_horizonte.groupby(
            ["fecha_objetivo", "zone", "contaminante"], dropna=False
        )["alerta_modelo"]
        .any()
        .reset_index()
        .rename(columns={"alerta_modelo": "modelo_predijo_alerta"})
    )

    # Para construir eventos_detalle: por cada contingencia del golden set,
    # marcar si el modelo la predijo
    detalles = []

    for _, evt in golden_set.iterrows():
        fecha_evt = pd.Timestamp(evt["fecha_activacion"]).normalize()
        cont = evt["contaminante"]
        zona = evt["zona"]

        # Manejar zonas compuestas en el golden set (ej. "CE,SO")
        zonas_evt = (
            [z.strip() for z in zona.split(",")] if zona and "," in zona
            else [zona]
        )

        # ¿El modelo predijo alerta para esa zona/cont/fecha?
        match = alertas_zonales[
            (alertas_zonales["fecha_objetivo"] == fecha_evt)
            & (alertas_zonales["zone"].isin(zonas_evt))
            & (alertas_zonales["contaminante"] == cont)
        ]
        predicho = bool(match["modelo_predijo_alerta"].any()) if len(match) > 0 else False

        if predicho:
            metricas.tp += 1
            metricas.lead_time_dias.append(horizonte_dias)
            estado = "TP"
        else:
            metricas.fn += 1
            estado = "FN"

        detalles.append({
            "fecha_objetivo": fecha_evt,
            "contaminante": cont,
            "zona": zona,
            "estacion_pcaa": evt.get("estacion_activacion"),
            "valor_pcaa": evt.get("valor_activacion"),
            "modelo_predijo_zonal": predicho,
            "estado_zonal": estado,
        })

    # Contar falsos positivos zonales: alertas del modelo que NO corresponden
    # a ninguna contingencia real del golden set.
    fechas_zonas_reales = set()
    for _, evt in golden_set.iterrows():
        f = pd.Timestamp(evt["fecha_activacion"]).normalize()
        cont = evt["contaminante"]
        zona = evt["zona"]
        zonas = (
            [z.strip() for z in zona.split(",")] if zona and "," in zona
            else [zona]
        )
        for z in zonas:
            fechas_zonas_reales.add((f, z, cont))

    falsas_alarmas_list = []
    for _, alerta in alertas_zonales[alertas_zonales["modelo_predijo_alerta"]].iterrows():
        clave = (
            pd.Timestamp(alerta["fecha_objetivo"]).normalize(),
            alerta["zone"],
            alerta["contaminante"],
        )
        if clave not in fechas_zonas_reales:
            metricas.fp += 1
            falsas_alarmas_list.append({
                "fecha_objetivo": alerta["fecha_objetivo"],
                "zone": alerta["zone"],
                "contaminante": alerta["contaminante"],
                "tipo": "zonal",
            })

    detalle_df = pd.DataFrame(detalles)
    return metricas, detalle_df


# =============================================================================
# EVALUACIÓN POR ESTACIÓN
# =============================================================================

def _evaluar_por_estacion(
    predicciones: pd.DataFrame,
    golden_set: pd.DataFrame,
    horizonte_dias: int,
    threshold: float,
) -> tuple[MetricasBinarias, int]:
    """Evalúa el modelo a nivel (fecha, station_id, contaminante).

    Solo se evalúan eventos del golden set con station_id_activacion mapeado
    (excluyendo 'unknown' y 'regional_aggregate'). Retorna también el número
    de eventos excluidos.
    """
    metricas = MetricasBinarias()

    # Filtrar golden set a eventos con mapeo utilizable
    mapeable = golden_set[
        golden_set["station_id_activacion"].notna()
    ].copy()
    n_excluidos = len(golden_set) - len(mapeable)

    # Filtrar predicciones al horizonte
    pred = predicciones[predicciones["horizonte_dias"] == horizonte_dias].copy()
    pred["alerta_modelo"] = pred["probabilidad_contingencia"] >= threshold

    # Para cada contingencia con station_id, buscar la predicción específica
    for _, evt in mapeable.iterrows():
        fecha_evt = pd.Timestamp(evt["fecha_activacion"]).normalize()
        cont = evt["contaminante"]
        sid = evt["station_id_activacion"]

        match = pred[
            (pred["fecha_objetivo"] == fecha_evt)
            & (pred["station_id"] == sid)
            & (pred["contaminante"] == cont)
        ]

        if len(match) == 0:
            # No hay predicción para esa (fecha, station, cont) — probablemente
            # estación caída ese día o fuera del periodo del modelo. La
            # convención conservadora es marcarlo como FN.
            metricas.fn += 1
            continue

        if bool(match["alerta_modelo"].any()):
            metricas.tp += 1
            metricas.lead_time_dias.append(horizonte_dias)
        else:
            metricas.fn += 1

    # Falsos positivos por estación: predicciones positivas que no corresponden
    # a ninguna contingencia real (a nivel station_id específico).
    fechas_estaciones_reales = {
        (pd.Timestamp(r["fecha_activacion"]).normalize(),
         r["station_id_activacion"], r["contaminante"])
        for _, r in mapeable.iterrows()
    }

    pred_positivas = pred[pred["alerta_modelo"]]
    for _, p in pred_positivas.iterrows():
        clave = (
            pd.Timestamp(p["fecha_objetivo"]).normalize(),
            p["station_id"],
            p["contaminante"],
        )
        if clave not in fechas_estaciones_reales:
            metricas.fp += 1

    return metricas, n_excluidos


# =============================================================================
# API PRINCIPAL
# =============================================================================

def evaluar_modelo(
    predicciones: pd.DataFrame,
    golden_set: pd.DataFrame,
    horizonte_dias: int = 1,
    threshold: float = THRESHOLD_DEFAULT,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
) -> ResultadoEvaluacion:
    """Evalúa el modelo comparando sus predicciones contra el golden set PCAA.

    Args:
        predicciones: DataFrame de gold.predicciones_diarias con columnas:
            fecha_prediccion, fecha_objetivo, horizonte_dias, station_id,
            zone, contaminante, valor_predicho, probabilidad_contingencia.
        golden_set: DataFrame de evaluation.golden_set con columnas:
            fecha_activacion, contaminante, zona, station_id_activacion,
            mapeo_calidad_activacion.
        horizonte_dias: con cuántos días de anticipación se evaluó la predicción.
        threshold: corte de probabilidad para considerar "predicción positiva".
        fecha_inicio: filtro opcional para restringir el periodo evaluado.
        fecha_fin: filtro opcional para restringir el periodo evaluado.

    Returns:
        ResultadoEvaluacion con métricas zonales, por estación, y detalle de eventos.
    """
    _validar_predicciones(predicciones)
    _validar_golden(golden_set)

    # Normalizar tipos de fecha
    predicciones = predicciones.copy()
    predicciones["fecha_objetivo"] = pd.to_datetime(predicciones["fecha_objetivo"]).dt.normalize()
    golden_set = golden_set.copy()
    golden_set["fecha_activacion"] = pd.to_datetime(golden_set["fecha_activacion"]).dt.normalize()

    # Filtrar período si se especifica
    if fecha_inicio:
        ts_inicio = pd.Timestamp(fecha_inicio)
        predicciones = predicciones[predicciones["fecha_objetivo"] >= ts_inicio]
        golden_set = golden_set[golden_set["fecha_activacion"] >= ts_inicio]
    if fecha_fin:
        ts_fin = pd.Timestamp(fecha_fin)
        predicciones = predicciones[predicciones["fecha_objetivo"] <= ts_fin]
        golden_set = golden_set[golden_set["fecha_activacion"] <= ts_fin]

    # Filtrar a contaminantes que el modelo predice
    golden_set = golden_set[golden_set["contaminante"].isin(CONTAMINANTES_EVAL)]

    logger.info(
        f"Evaluando modelo: {len(predicciones):,} predicciones contra "
        f"{len(golden_set)} eventos del golden set "
        f"(horizonte={horizonte_dias}d, threshold={threshold})"
    )

    # Evaluación zonal
    metricas_zonal, detalle_zonal = _evaluar_zonal(
        predicciones, golden_set, horizonte_dias, threshold
    )

    # Evaluación por estación
    metricas_est, n_excluidos = _evaluar_por_estacion(
        predicciones, golden_set, horizonte_dias, threshold
    )

    # Construir resultado
    resultado = ResultadoEvaluacion(
        zonal=metricas_zonal,
        por_estacion=metricas_est,
        eventos_detalle=detalle_zonal,
        horizonte_dias=horizonte_dias,
        threshold=threshold,
        n_eventos_golden=len(golden_set),
        n_eventos_excluidos_mapeo=n_excluidos,
    )

    logger.info(
        f"Resultado zonal: recall={metricas_zonal.recall:.3f}, "
        f"precision={metricas_zonal.precision:.3f}, "
        f"F1={metricas_zonal.f1:.3f}"
    )

    return resultado


def evaluar_multi_horizonte(
    predicciones: pd.DataFrame,
    golden_set: pd.DataFrame,
    horizontes: list[int] = [1, 3, 7],
    threshold: float = THRESHOLD_DEFAULT,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
) -> dict[int, ResultadoEvaluacion]:
    """Evalúa el modelo a múltiples horizontes y retorna un dict horizonte→resultado.

    Útil para reportar en presentación: "el modelo predice contingencias con
    recall X a 1 día, Y a 3 días, Z a 7 días".
    """
    resultados = {}
    for h in horizontes:
        resultados[h] = evaluar_modelo(
            predicciones=predicciones,
            golden_set=golden_set,
            horizonte_dias=h,
            threshold=threshold,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
        )
    return resultados
