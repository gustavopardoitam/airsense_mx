"""ETL Silver → Gold: feature engineering para predicción de calidad del aire.

Transforma observaciones horarias y meteorología en un panel diario por
estación, listo para entrenar modelos de regresión que predicen los valores
de O3, PM2.5 y PM10 del día siguiente (con horizonte 1-7 días).

ENTRADA
=======
- silver.observaciones_horarias: una fila por (timestamp, station_id, contaminante)
- silver.meteo_horario: una fila por (timestamp, station_id), por estación

SALIDA
======
- gold.panel_diario: una fila por (fecha, station_id) con:
  - Targets: valores agregados respetando ventanas oficiales del PCAA
    * o3_max_1h, no2_max_1h, so2_max_1h     (pico horario)
    * pm25_avg_24h, pm10_avg_24h            (promedio del día)
    * co_max_8h                             (rolling 8h máximo)
  - Labels booleanas: contingencia_o3, _pm25, _pm10, _any (cruces de umbral)
  - Lags: 1, 3, 7, 14 días por cada contaminante predecible
  - Rolling stats: medias y stds de 7 y 30 días
  - Meteorología agregada del día por estación (max, min, avg según variable)
  - Features de calendario: mes, día semana, temporadas
  - Flags de calidad: cobertura del día y de los últimos 30 días

DECISIONES DE DISEÑO
====================
- Granularidad output: (fecha, station_id). NO por zona. Estación es el grano
  natural del dato y zona se denormaliza para facilitar agregaciones aguas abajo.
- Umbral de cobertura diaria: 18 de 24 horas no-nulas para considerar el día
  válido. Si una estación tiene <18h, los targets de ese día son NULL.
- Manejo de NULLs en lags: si no hay dato, el lag es NULL. LightGBM maneja
  NULLs nativamente. NO imputamos.
- Manejo de gaps >14 días en una estación: se mantienen las filas con NULLs
  en lags/rolling. El modelo decide qué hacer con ellos.
- Período por defecto: 2021-01-01 a 2026-02-28 (acordado con equipo: 2020
  tiene cobertura muy incompleta).

USO COMO MÓDULO
===============
    from etl.silver_to_gold import construir_gold
    gold_df = construir_gold(obs_df, meteo_df, dim_estaciones_df)

USO COMO CLI
============
    python -m etl.silver_to_gold \\
        --silver-obs s3://airsense-mx/silver/observaciones_horarias/ \\
        --silver-meteo s3://airsense-mx/silver/meteo_horario/ \\
        --output s3://airsense-mx/gold/panel_diario/ \\
        --fecha-inicio 2021-01-01 --fecha-fin 2026-02-28
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from config import (
    UMBRALES_PCAA,
    CONTAMINANTES_PREDECIBLES,
    CONTAMINANTES_INGESTADOS,
    ContaminantConfig,
)


logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTES DEL MÓDULO
# =============================================================================

# Mínimo de horas no-nulas en el día para considerar el agregado válido.
# Estándar internacional en monitoreo de calidad del aire (EPA, EEA): 75%.
HORAS_MINIMAS_DIA = 18

# Mínimo de horas no-nulas en ventana de 8h para CO (mismo criterio: 75%).
HORAS_MINIMAS_8H = 6

# Horario de pico de ozono en CDMX (basado en patrón fotoquímico observado).
# Usado para calcular feature "viento promedio en horas de pico O3".
HORAS_PICO_O3 = list(range(10, 19))  # 10:00 a 18:00

# Meses de temporada seca en CDMX (asociada a contingencias por inversión térmica).
MESES_TEMPORADA_SECA = {11, 12, 1, 2, 3, 4}

# Meses de temporada de ozono (pico de contingencias fotoquímicas).
MESES_TEMPORADA_O3 = {2, 3, 4, 5}


# =============================================================================
# AGREGACIÓN DIARIA DE OBSERVACIONES
# =============================================================================

def agregar_diario_obs(obs: pd.DataFrame) -> pd.DataFrame:
    """Convierte observaciones horarias a panel diario por estación×contaminante.

    Aplica la ventana de agregación correspondiente a cada contaminante según
    la tabla oficial del PCAA:
        - O3, NO2, SO2: max 1h (pico horario máximo del día)
        - PM2.5, PM10: avg 24h (promedio del día)
        - CO: max 8h (máximo del rolling de 8 horas del día)

    Args:
        obs: DataFrame con columnas [timestamp, station_id, zone, contaminante,
             valor, latitude, longitude, municipality]

    Returns:
        DataFrame en formato wide con una fila por (fecha, station_id) y
        columnas: o3_max_1h, no2_max_1h, so2_max_1h, pm25_avg_24h, pm10_avg_24h,
        co_max_8h, junto con identificadores y conteos de cobertura.
    """
    logger.info(f"Agregando {len(obs):,} observaciones horarias a panel diario")

    df = obs.copy()
    df["fecha"] = df["timestamp"].dt.date

    # Para cada (fecha, station_id, contaminante), calculamos:
    #   - max, avg según corresponda
    #   - n_horas_validas (count de valores no-nulos)
    grouped = df.groupby(["fecha", "station_id", "zone", "contaminante"], dropna=False)

    agg_horario = grouped["valor"].agg(
        valor_max="max",
        valor_avg="mean",
        n_horas_validas="count",
    ).reset_index()

    # CO requiere tratamiento especial: max sobre rolling 8h.
    # Lo calculamos por separado.
    co_max_8h_por_dia = _calcular_co_max_8h(df)

    # Pivoteamos a formato wide con la métrica correcta por contaminante
    registros = []
    grupos = agg_horario.groupby(["fecha", "station_id", "zone"], dropna=False)

    for (fecha, station_id, zone), grupo in grupos:
        fila = {"fecha": fecha, "station_id": station_id, "zone": zone}

        for cont in CONTAMINANTES_INGESTADOS:
            sub = grupo[grupo["contaminante"] == cont]
            if sub.empty:
                # No hubo ninguna observación de este contaminante ese día
                if cont in ("O3", "NO2", "SO2"):
                    fila[f"{cont.lower()}_max_1h"] = np.nan
                elif cont in ("PM25", "PM10"):
                    fila[f"{cont.lower()}_avg_24h"] = np.nan
                fila[f"{cont.lower()}_n_horas"] = 0
                continue

            n_horas = int(sub["n_horas_validas"].iloc[0])
            fila[f"{cont.lower()}_n_horas"] = n_horas

            # Aplicar threshold de cobertura
            if n_horas < HORAS_MINIMAS_DIA:
                # Marcamos NULL para no propagar agregados poco confiables
                if cont in ("O3", "NO2", "SO2"):
                    fila[f"{cont.lower()}_max_1h"] = np.nan
                elif cont in ("PM25", "PM10"):
                    fila[f"{cont.lower()}_avg_24h"] = np.nan
                continue

            if cont in ("O3", "NO2", "SO2"):
                fila[f"{cont.lower()}_max_1h"] = float(sub["valor_max"].iloc[0])
            elif cont in ("PM25", "PM10"):
                fila[f"{cont.lower()}_avg_24h"] = float(sub["valor_avg"].iloc[0])

        registros.append(fila)

    diario = pd.DataFrame(registros)

    # Pegar CO max 8h
    if not co_max_8h_por_dia.empty:
        diario = diario.merge(
            co_max_8h_por_dia, on=["fecha", "station_id"], how="left"
        )
    else:
        diario["co_max_8h"] = np.nan

    diario["fecha"] = pd.to_datetime(diario["fecha"])
    logger.info(f"Panel diario: {len(diario):,} filas, "
                f"{diario['station_id'].nunique()} estaciones")

    return diario.sort_values(["fecha", "station_id"]).reset_index(drop=True)


def _calcular_co_max_8h(df_obs: pd.DataFrame) -> pd.DataFrame:
    """Calcula el máximo del rolling 8h de CO por (fecha, station_id).

    El umbral PCAA de CO usa ventana de 8h, así que el feature debe respetar
    esa ventana. Calculamos rolling 8h horario y luego tomamos el max del día.

    Requiere al menos 6 de 8 horas válidas en cada ventana (75%).
    """
    co = df_obs[df_obs["contaminante"] == "CO"].copy()
    if co.empty:
        return pd.DataFrame(columns=["fecha", "station_id", "co_max_8h"])

    # Ordenar por estación y timestamp para rolling correcto
    co = co.sort_values(["station_id", "timestamp"])

    # Rolling 8h por estación
    co["co_roll_8h"] = (
        co.groupby("station_id")["valor"]
        .rolling(window=8, min_periods=HORAS_MINIMAS_8H)
        .mean()
        .reset_index(level=0, drop=True)
    )

    co["fecha"] = co["timestamp"].dt.date
    max_8h = (
        co.groupby(["fecha", "station_id"])["co_roll_8h"]
        .max()
        .reset_index()
        .rename(columns={"co_roll_8h": "co_max_8h"})
    )

    return max_8h


# =============================================================================
# AGREGACIÓN DIARIA DE METEOROLOGÍA
# =============================================================================

def agregar_diario_meteo(meteo: pd.DataFrame) -> pd.DataFrame:
    """Agrega meteorología horaria por estación a panel diario.

    Las variables se agregan con estadísticas relevantes para predecir
    contaminación atmosférica:
        - Temperatura: max, min, amplitud (proxy de estabilidad)
        - Humedad: avg, min (baja humedad asociada a O3)
        - Precipitación: total acumulado (lava PM)
        - Viento: avg total, avg en horas de pico O3 (10-18h), max gusts
        - Cobertura nubosa: avg
        - Radiación solar: total (crítico para O3 fotoquímico)
        - Presión: avg

    Args:
        meteo: DataFrame con columnas [timestamp, station_id, temp_2m,
               humidity_2m, ...] (granularidad por estación, no por zona)

    Returns:
        DataFrame con una fila por (fecha, station_id) y agregados diarios.
    """
    logger.info(f"Agregando {len(meteo):,} registros meteorológicos")

    df = meteo.copy()
    df["fecha"] = df["timestamp"].dt.date
    df["hora"] = df["timestamp"].dt.hour

    # Agregados estándar
    agg_general = df.groupby(["fecha", "station_id"]).agg(
        temp_max_day=("temp_2m", "max"),
        temp_min_day=("temp_2m", "min"),
        humidity_avg_day=("humidity_2m", "mean"),
        humidity_min_day=("humidity_2m", "min"),
        dewpoint_avg_day=("dewpoint_2m", "mean"),
        precipitation_total=("precipitation", "sum"),
        wind_speed_avg_day=("wind_speed_10m", "mean"),
        wind_gusts_max=("wind_gusts_10m", "max"),
        cloud_cover_avg_day=("cloud_cover", "mean"),
        radiation_total_day=("shortwave_radiation", "sum"),
        surface_pressure_avg=("surface_pressure", "mean"),
        n_horas_meteo=("temp_2m", "count"),
    ).reset_index()

    # Viento promedio en horas de pico O3 (10-18h)
    pico_o3 = df[df["hora"].isin(HORAS_PICO_O3)]
    agg_viento_pico = pico_o3.groupby(["fecha", "station_id"]).agg(
        wind_speed_avg_1018h=("wind_speed_10m", "mean"),
    ).reset_index()

    diario = agg_general.merge(agg_viento_pico, on=["fecha", "station_id"], how="left")

    # Feature derivada: amplitud térmica (proxy de estabilidad atmosférica)
    diario["temp_amplitude"] = diario["temp_max_day"] - diario["temp_min_day"]

    diario["fecha"] = pd.to_datetime(diario["fecha"])
    logger.info(f"Meteo diario: {len(diario):,} filas")

    return diario.sort_values(["fecha", "station_id"]).reset_index(drop=True)


# =============================================================================
# FEATURES TEMPORALES: LAGS Y ROLLING STATS
# =============================================================================

def construir_lags(
    panel: pd.DataFrame,
    cfg: ContaminantConfig,
) -> pd.DataFrame:
    """Agrega columnas de lag por cada contaminante predecible.

    Para cada (fecha, station_id), agrega el valor del contaminante de
    1, 3, 7 y 14 días atrás (configurable en cfg.lags_dias). Si no hay
    dato en el día -N, el lag es NULL.

    Args:
        panel: DataFrame ya con agregados diarios.
        cfg: ContaminantConfig con cfg.lags_dias.

    Returns:
        DataFrame con columnas adicionales {cont}_lag_{N}d.
    """
    logger.info(f"Construyendo lags: {cfg.lags_dias} días")
    df = panel.sort_values(["station_id", "fecha"]).copy()

    cols_target = {
        "O3": "o3_max_1h",
        "PM25": "pm25_avg_24h",
        "PM10": "pm10_avg_24h",
    }

    for cont, col in cols_target.items():
        if col not in df.columns:
            continue
        for lag in cfg.lags_dias:
            df[f"{cont.lower()}_lag_{lag}d"] = (
                df.groupby("station_id")[col].shift(lag)
            )

    return df


def construir_rolling(
    panel: pd.DataFrame,
    cfg: ContaminantConfig,
) -> pd.DataFrame:
    """Agrega features de medias y desviaciones móviles por contaminante.

    Calcula rolling mean y rolling std de ventanas configurables (default 7
    y 30 días) por cada contaminante predecible. Se aplica SHIFT(1) primero
    para evitar data leakage: el rolling de día t solo usa días <= t-1.

    Args:
        panel: DataFrame ya con agregados diarios.
        cfg: ContaminantConfig con cfg.rolls_dias.

    Returns:
        DataFrame con columnas adicionales {cont}_roll_{stat}_{N}d.
    """
    logger.info(f"Construyendo rolling stats: {cfg.rolls_dias} días")
    df = panel.sort_values(["station_id", "fecha"]).copy()

    cols_target = {
        "O3": "o3_max_1h",
        "PM25": "pm25_avg_24h",
        "PM10": "pm10_avg_24h",
    }

    for cont, col in cols_target.items():
        if col not in df.columns:
            continue
        for window in cfg.rolls_dias:
            min_periods = max(1, int(np.ceil(window * 0.7)))
            # SHIFT(1) primero para evitar leakage
            shifted = df.groupby("station_id")[col].shift(1)
            df[f"{cont.lower()}_roll_mean_{window}d"] = (
                shifted.groupby(df["station_id"])
                .rolling(window=window, min_periods=min_periods)
                .mean()
                .reset_index(level=0, drop=True)
            )
            df[f"{cont.lower()}_roll_std_{window}d"] = (
                shifted.groupby(df["station_id"])
                .rolling(window=window, min_periods=min_periods)
                .std()
                .reset_index(level=0, drop=True)
            )

    return df


# =============================================================================
# FEATURES DE CALENDARIO
# =============================================================================

def agregar_calendario(panel: pd.DataFrame) -> pd.DataFrame:
    """Agrega features derivadas del calendario.

    Variables generadas:
        - mes: 1-12
        - dia_semana: 0=lunes, 6=domingo
        - dia_anio: 1-366
        - es_fin_de_semana: bool (sábado y domingo)
        - es_temporada_seca: bool (nov-abr en CDMX)
        - es_temporada_o3: bool (feb-may, pico fotoquímico)
    """
    df = panel.copy()
    fecha_dt = pd.to_datetime(df["fecha"])

    df["mes"] = fecha_dt.dt.month.astype("int8")
    df["dia_semana"] = fecha_dt.dt.dayofweek.astype("int8")
    df["dia_anio"] = fecha_dt.dt.dayofyear.astype("int16")
    df["es_fin_de_semana"] = (df["dia_semana"] >= 5)
    df["es_temporada_seca"] = df["mes"].isin(MESES_TEMPORADA_SECA)
    df["es_temporada_o3"] = df["mes"].isin(MESES_TEMPORADA_O3)

    return df


# =============================================================================
# LABELS DE CONTINGENCIA
# =============================================================================

def agregar_labels(panel: pd.DataFrame) -> pd.DataFrame:
    """Deriva labels booleanas de contingencia desde los valores y umbrales.

    Para cada contaminante predecible, una contingencia se activa cuando el
    valor del día (en su ventana correspondiente) cruza el umbral oficial.

    Importante: si el valor es NULL (por baja cobertura), el label también
    es NULL — no asumimos "no contingencia" cuando no tenemos datos.

    Variables generadas:
        - contingencia_o3:   o3_max_1h >= 140
        - contingencia_pm25: pm25_avg_24h >= 79
        - contingencia_pm10: pm10_avg_24h >= 146
        - contingencia_any:  cualquiera de las anteriores
    """
    df = panel.copy()

    mapping = {
        "contingencia_o3":   ("o3_max_1h",    UMBRALES_PCAA["O3"]["valor"]),
        "contingencia_pm25": ("pm25_avg_24h", UMBRALES_PCAA["PM25"]["valor"]),
        "contingencia_pm10": ("pm10_avg_24h", UMBRALES_PCAA["PM10"]["valor"]),
    }

    for label_col, (val_col, umbral) in mapping.items():
        if val_col not in df.columns:
            df[label_col] = pd.NA
            continue
        # pd.NA propaga: si valor es NaN, el resultado es NaN (no False)
        df[label_col] = df[val_col].apply(
            lambda v: pd.NA if pd.isna(v) else (v >= umbral)
        ).astype("boolean")

    # contingencia_any: True si cualquiera es True; NA si todas NA
    label_cols = ["contingencia_o3", "contingencia_pm25", "contingencia_pm10"]
    existing = [c for c in label_cols if c in df.columns]
    if existing:
        df["contingencia_any"] = df[existing].any(axis=1, skipna=True).astype("boolean")
        # Si TODAS son NA, contingencia_any también es NA
        todas_na = df[existing].isna().all(axis=1)
        df.loc[todas_na, "contingencia_any"] = pd.NA

    return df


# =============================================================================
# FLAGS DE CALIDAD
# =============================================================================

def agregar_flags_calidad(panel: pd.DataFrame) -> pd.DataFrame:
    """Agrega indicadores de calidad de datos por estación.

    - dias_validos_30d: cuántos de los últimos 30 días tienen al menos un
      target no-nulo (proxy de "estación operando bien recientemente").
    - cobertura_30d: % de los últimos 30 días con al menos un target válido.

    Estos flags ayudan al modelo a aprender cuándo confiar en las predicciones
    y permiten filtrar estaciones con outages prolongados desde Streamlit.
    """
    df = panel.sort_values(["station_id", "fecha"]).copy()

    targets = ["o3_max_1h", "pm25_avg_24h", "pm10_avg_24h"]
    existing_targets = [c for c in targets if c in df.columns]
    if not existing_targets:
        df["dias_validos_30d"] = 0
        df["cobertura_30d"] = 0.0
        return df

    # Día válido = al menos un target no nulo
    df["dia_valido"] = df[existing_targets].notna().any(axis=1).astype(int)

    # Rolling sum de los últimos 30 días por estación (incluyendo el día actual)
    df["dias_validos_30d"] = (
        df.groupby("station_id")["dia_valido"]
        .rolling(window=30, min_periods=1)
        .sum()
        .reset_index(level=0, drop=True)
        .astype("int16")
    )
    df["cobertura_30d"] = (df["dias_validos_30d"] / 30.0).round(3)

    return df.drop(columns=["dia_valido"])


# =============================================================================
# PIPELINE PRINCIPAL
# =============================================================================

def construir_gold(
    obs: pd.DataFrame,
    meteo: pd.DataFrame,
    cfg: Optional[ContaminantConfig] = None,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
) -> pd.DataFrame:
    """Pipeline completo Silver → Gold.

    Args:
        obs: DataFrame de silver.observaciones_horarias.
        meteo: DataFrame de silver.meteo_horario (granularidad por estación).
        cfg: ContaminantConfig. Si None, usa defaults del módulo.
        fecha_inicio: filtro inicial (inclusivo), formato 'YYYY-MM-DD'.
        fecha_fin: filtro final (inclusivo), formato 'YYYY-MM-DD'.

    Returns:
        DataFrame Gold con una fila por (fecha, station_id) y ~50 columnas.
    """
    cfg = cfg or ContaminantConfig()

    # Filtrado opcional de fechas (antes de agregar para reducir carga)
    if fecha_inicio:
        obs = obs[obs["timestamp"] >= pd.Timestamp(fecha_inicio)]
        meteo = meteo[meteo["timestamp"] >= pd.Timestamp(fecha_inicio)]
    if fecha_fin:
        # Inclusivo del día completo: hasta 23:00 del fecha_fin
        ts_fin = pd.Timestamp(fecha_fin) + pd.Timedelta(hours=23)
        obs = obs[obs["timestamp"] <= ts_fin]
        meteo = meteo[meteo["timestamp"] <= ts_fin]

    logger.info(
        f"Pipeline Gold: obs={len(obs):,}, meteo={len(meteo):,}, "
        f"rango=[{fecha_inicio or 'todo'}, {fecha_fin or 'todo'}]"
    )

    # 1. Agregar a diario
    panel = agregar_diario_obs(obs)
    meteo_d = agregar_diario_meteo(meteo)

    # 2. Join con meteo por (fecha, station_id) — 1-a-1
    panel = panel.merge(meteo_d, on=["fecha", "station_id"], how="left")

    # 3. Lags
    panel = construir_lags(panel, cfg)

    # 4. Rolling stats
    panel = construir_rolling(panel, cfg)

    # 5. Calendario
    panel = agregar_calendario(panel)

    # 6. Labels de contingencia
    panel = agregar_labels(panel)

    # 7. Flags de calidad
    panel = agregar_flags_calidad(panel)

    # 8. Metadata
    panel["ingestion_timestamp"] = pd.Timestamp.now()
    panel["pipeline_version"] = "gold_v1.0"

    logger.info(
        f"Gold construido: {len(panel):,} filas, {len(panel.columns)} columnas, "
        f"{panel['station_id'].nunique()} estaciones, "
        f"rango {panel['fecha'].min().date()} a {panel['fecha'].max().date()}"
    )

    return panel


# =============================================================================
# CLI
# =============================================================================

def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _leer_silver(path: str) -> pd.DataFrame:
    """Lee Silver desde S3 o local. Detecta automáticamente el backend."""
    if path.startswith("s3://"):
        import awswrangler as wr
        logger.info(f"Leyendo Silver desde S3: {path}")
        return wr.s3.read_parquet(path)
    else:
        local_path = Path(path)
        logger.info(f"Leyendo Silver desde local: {local_path}")
        if local_path.is_dir():
            return pd.read_parquet(local_path)
        return pd.read_parquet(local_path)


def _escribir_gold(df: pd.DataFrame, path: str) -> None:
    """Escribe Gold a S3 o local con particionado por year/month."""
    df = df.copy()
    df["year"] = df["fecha"].dt.year
    df["month"] = df["fecha"].dt.month

    if path.startswith("s3://"):
        import awswrangler as wr
        logger.info(f"Escribiendo Gold a S3 (particionado): {path}")
        wr.s3.to_parquet(
            df=df,
            path=path,
            dataset=True,
            partition_cols=["year", "month"],
            compression="snappy",
            mode="overwrite",
        )
    else:
        local_path = Path(path)
        local_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Escribiendo Gold local (single file): {local_path}")
        df.drop(columns=["year", "month"]).to_parquet(
            local_path / "panel_diario.parquet",
            compression="snappy",
            index=False,
        )


def main() -> None:
    _setup_logging()

    parser = argparse.ArgumentParser(description="ETL Silver → Gold para AirSense MX")
    parser.add_argument(
        "--silver-obs", required=True,
        help="Path a silver.observaciones_horarias (S3 o local)",
    )
    parser.add_argument(
        "--silver-meteo", required=True,
        help="Path a silver.meteo_horario (S3 o local)",
    )
    parser.add_argument(
        "--output", required=True,
        help="Path de salida para gold.panel_diario (S3 o local)",
    )
    parser.add_argument(
        "--fecha-inicio", default="2021-01-01",
        help="Fecha de inicio (inclusiva), formato YYYY-MM-DD",
    )
    parser.add_argument(
        "--fecha-fin", default=None,
        help="Fecha final (inclusiva), formato YYYY-MM-DD",
    )
    args = parser.parse_args()

    obs = _leer_silver(args.silver_obs)
    meteo = _leer_silver(args.silver_meteo)

    gold = construir_gold(
        obs=obs,
        meteo=meteo,
        fecha_inicio=args.fecha_inicio,
        fecha_fin=args.fecha_fin,
    )

    _escribir_gold(gold, args.output)
    logger.info("✓ Gold construido y escrito correctamente")


if __name__ == "__main__":
    main()
