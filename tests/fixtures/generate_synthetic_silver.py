"""
Generador de fixture sintética para silver.observaciones_horarias y silver.meteo_horario.

PROPÓSITO
=========
Permite desarrollar Gold (feature engineering) y el modelo (training) sin
depender de que Antonio termine el ETL Bronze→Silver. Genera datos que cumplen
EXACTAMENTE el contrato de datos v1.0, con distribuciones plausibles y eventos
de contingencia plantados para que los labels no salgan todos en 0.

USO
===
    from tests.fixtures.generate_synthetic_silver import generate_silver_fixtures
    obs, meteo = generate_silver_fixtures(seed=42)
    obs.to_parquet("tests/fixtures/silver_obs_synthetic.parquet")
    meteo.to_parquet("tests/fixtures/silver_meteo_synthetic.parquet")

DECISIONES DE DISEÑO
====================
- Periodo: 2024-01-01 a 2024-03-31 (90 días). Cubre temporada seca/fría con
  inversiones térmicas (picos PM) y transición a temporada de ozono (febrero-marzo).
- Estaciones: 10 representativas, 2 por zona. No son las 44 reales — es fixture.
- Distribuciones: O3 con patrón diurno fotoquímico, PM con persistencia,
  meteo coherente con contaminación (alta T + bajo viento → picos O3).
- 3 eventos de contingencia plantados:
    * 2024-02-22 SO  O3 ≈ 167 ppb (replica el evento real)
    * 2024-03-15 NO  O3 ≈ 155 ppb (genérico)
    * 2024-01-01 SE  PM25 ≈ 99 µg/m³ (replica patrón de quema pirotécnica año nuevo)
- 5% de NULLs aleatorios para simular outages reales del SIMAT.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime
from typing import Tuple


# =============================================================================
# CATÁLOGO DE ESTACIONES SINTÉTICAS (subset representativo de la dim real)
# =============================================================================

STATIONS_FIXTURE = [
    # station_id, zone, latitude, longitude, municipality
    ("AJU", "SO", 19.1543, -99.1626, "Tlalpan"),
    ("PED", "SO", 19.3251, -99.2041, "Álvaro Obregón"),
    ("FAC", "NO", 19.4823, -99.2433, "Naucalpan de Juárez"),
    ("TLA", "NO", 19.5291, -99.2046, "Tlalnepantla de Baz"),
    ("GAM", "NE", 19.4827, -99.0946, "Gustavo A. Madero"),
    ("XAL", "NE", 19.5260, -99.0824, "Ecatepec de Morelos"),
    ("SAC", "SE", 19.3450, -99.0090, "Iztapalapa"),
    ("UIZ", "SE", 19.3608, -99.0739, "Iztapalapa"),
    ("MER", "CE", 19.4246, -99.1196, "Venustiano Carranza"),
    ("HGM", "CE", 19.4114, -99.1514, "Cuauhtémoc"),
]

CONTAMINANTES = ["O3", "NO2", "SO2", "PM10", "PM25", "CO"]

# Eventos de contingencia plantados: (fecha, hora_pico, zone, contaminante, pico)
# Estos los plantamos para que cuando Gustavo construya Gold, los labels no
# salgan todos en 0. Replican patrones del histórico real del PCAA.
CONTINGENCIAS_PLANTADAS = [
    # Patrón ozono primaveral en zona SO (replica 22/02/2024 real)
    {"fecha": "2024-02-22", "hora_pico": 15, "zone": "SO", "cont": "O3", "pico": 167.0},
    # Patrón ozono en zona NO (similar a contingencias documentadas)
    {"fecha": "2024-03-15", "hora_pico": 16, "zone": "NO", "cont": "O3", "pico": 155.0},
    # Patrón PM2.5 año nuevo (quema pirotécnica)
    {"fecha": "2024-01-01", "hora_pico": 23, "zone": "SE", "cont": "PM25", "pico": 99.0},
]


# =============================================================================
# GENERADORES DE PATRONES BASE
# =============================================================================

def _diurnal_o3_pattern(hour: int) -> float:
    """
    Patrón fotoquímico típico de O3: bajo en la madrugada, sube con la radiación
    solar, pico entre 14-16h, baja al anochecer.
    Devuelve un multiplicador entre 0.1 y 1.0.
    """
    # Aproximación con función gaussiana centrada en hora 15
    peak_hour = 15
    sigma = 4
    base = 0.1
    peak = 1.0
    return base + (peak - base) * np.exp(-((hour - peak_hour) ** 2) / (2 * sigma ** 2))


def _diurnal_pm_pattern(hour: int) -> float:
    """
    PM tiene doble pico: mañana (tráfico 7-9h) y noche (estabilidad atmosférica 20-23h).
    """
    # Suma de dos gaussianas
    morning = np.exp(-((hour - 8) ** 2) / (2 * 2 ** 2))
    evening = np.exp(-((hour - 22) ** 2) / (2 * 3 ** 2))
    return 0.3 + 0.7 * max(morning, evening)


def _seasonal_factor(date: pd.Timestamp, contaminant: str) -> float:
    """
    Factor estacional: O3 sube en primavera, PM sube en invierno.
    """
    month = date.month
    if contaminant == "O3":
        # Pico marzo-mayo
        return 0.6 + 0.4 * np.exp(-((month - 4) ** 2) / 8)
    elif contaminant in ("PM25", "PM10"):
        # Pico diciembre-febrero
        winter_distance = min(abs(month - 1), abs(month - 13))
        return 0.5 + 0.5 * np.exp(-(winter_distance ** 2) / 4)
    else:
        return 1.0


# =============================================================================
# GENERADOR PRINCIPAL DE OBSERVACIONES
# =============================================================================

def _generate_observations(
    start_date: str,
    end_date: str,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """
    Genera el dataset de observaciones horarias con distribuciones plausibles
    y eventos de contingencia plantados.
    """
    timestamps = pd.date_range(start=start_date, end=end_date, freq="h", inclusive="left")
    records = []

    # Niveles base por contaminante (medianas plausibles en CDMX)
    base_levels = {
        "O3":   35,   # ppb, sube con radiación
        "NO2":  30,   # ppb
        "SO2":   8,   # ppb
        "PM10": 50,   # µg/m³
        "PM25": 22,   # µg/m³
        "CO":   0.8,  # ppm
    }

    # Volatilidades (cuánto varía día a día)
    volatilities = {
        "O3":   15,
        "NO2":  12,
        "SO2":   4,
        "PM10": 20,
        "PM25": 10,
        "CO":   0.3,
    }

    for station_id, zone, lat, lon, muni in STATIONS_FIXTURE:
        for cont in CONTAMINANTES:
            base = base_levels[cont]
            vol = volatilities[cont]

            # Generamos serie diaria base con persistencia (AR(1))
            n_days = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days
            daily_innovations = rng.normal(0, vol * 0.3, n_days)
            daily_levels = np.zeros(n_days)
            daily_levels[0] = base
            phi = 0.7  # autocorrelación día a día
            for i in range(1, n_days):
                daily_levels[i] = phi * daily_levels[i-1] + (1 - phi) * base + daily_innovations[i]

            for ts in timestamps:
                day_idx = (ts.date() - pd.Timestamp(start_date).date()).days
                if day_idx >= n_days:
                    continue
                daily_level = daily_levels[day_idx]

                # Aplicar patrón diurno según contaminante
                if cont == "O3":
                    hourly_factor = _diurnal_o3_pattern(ts.hour)
                elif cont in ("PM10", "PM25"):
                    hourly_factor = _diurnal_pm_pattern(ts.hour)
                elif cont == "NO2":
                    # NO2 tiene pico matutino y vespertino (tráfico)
                    hourly_factor = _diurnal_pm_pattern(ts.hour) * 0.9
                else:
                    hourly_factor = 0.6 + 0.4 * rng.random()

                # Factor estacional
                seasonal = _seasonal_factor(ts, cont)

                # Ruido horario
                noise = rng.normal(0, vol * 0.15)

                value = daily_level * hourly_factor * seasonal + noise
                value = max(0.0, value)  # no hay concentraciones negativas

                records.append({
                    "timestamp": ts,
                    "station_id": station_id,
                    "zone": zone,
                    "contaminante": cont,
                    "valor": round(value, 2),
                    "latitude": lat,
                    "longitude": lon,
                    "municipality": muni,
                })

    df = pd.DataFrame.from_records(records)

    # =========================================================================
    # PLANTAR EVENTOS DE CONTINGENCIA
    # =========================================================================
    # Para cada evento plantado, ELEVAR las observaciones de la zona afectada
    # durante una ventana de horas alrededor del pico.

    for evt in CONTINGENCIAS_PLANTADAS:
        evt_date = pd.Timestamp(evt["fecha"])
        evt_zone = evt["zone"]
        evt_cont = evt["cont"]
        evt_pico = evt["pico"]
        evt_hora = evt["hora_pico"]

        # Ventana: 6 horas antes y después del pico
        for offset in range(-6, 7):
            target_ts = evt_date + pd.Timedelta(hours=evt_hora + offset)
            # Forma de campana alrededor del pico
            decay = np.exp(-(offset ** 2) / 8)
            elevated = evt_pico * decay + base_levels[evt_cont] * (1 - decay)

            mask = (
                (df["timestamp"] == target_ts)
                & (df["zone"] == evt_zone)
                & (df["contaminante"] == evt_cont)
            )
            # Variación entre estaciones de la zona (no todas igual)
            station_noise = rng.normal(1.0, 0.05, size=mask.sum())
            df.loc[mask, "valor"] = np.round(elevated * station_noise, 2)

    # =========================================================================
    # SIMULAR DATOS FALTANTES (~5% NULLs)
    # =========================================================================
    null_mask = rng.random(len(df)) < 0.05
    df.loc[null_mask, "valor"] = np.nan

    # =========================================================================
    # COLUMNA DE AUDITORÍA
    # =========================================================================
    df["ingestion_timestamp"] = pd.Timestamp.now()

    # Orden de columnas según contrato
    return df[[
        "timestamp", "station_id", "zone", "contaminante", "valor",
        "latitude", "longitude", "municipality", "ingestion_timestamp"
    ]].sort_values(["timestamp", "station_id", "contaminante"]).reset_index(drop=True)


# =============================================================================
# GENERADOR DE METEOROLOGÍA
# =============================================================================

def _generate_meteo(
    start_date: str,
    end_date: str,
    rng: np.random.Generator,
    granularidad: str = "zone",  # "zone" o "station"
) -> pd.DataFrame:
    """
    Genera meteorología horaria coherente con la contaminación.

    Decisión: por defecto granularidad por ZONA (5 puntos), siguiendo la
    recomendación del equipo de hacer una llamada Open-Meteo por centroide
    zonal. Si Antonio decide otra cosa, se ajusta.
    """
    timestamps = pd.date_range(start=start_date, end=end_date, freq="h", inclusive="left")

    if granularidad == "zone":
        # Centroides aproximados por zona (de la dim_estaciones real)
        puntos = [
            ("SO", 19.24, -99.18),
            ("NO", 19.50, -99.22),
            ("NE", 19.50, -99.09),
            ("SE", 19.35, -99.04),
            ("CE", 19.42, -99.14),
        ]
        id_col = "zone"
    else:
        puntos = [(sid, lat, lon) for sid, _, lat, lon, _ in STATIONS_FIXTURE]
        id_col = "station_id"

    records = []
    for punto_id, lat, lon in puntos:
        for ts in timestamps:
            hour = ts.hour
            doy = ts.dayofyear

            # Temperatura: patrón diurno + estacional
            temp_base = 16 + 4 * np.sin(2 * np.pi * (doy - 80) / 365)  # estacional
            temp_diurnal = 6 * np.sin(2 * np.pi * (hour - 8) / 24)     # diurno
            temp = temp_base + temp_diurnal + rng.normal(0, 1.5)

            # Humedad: inversa de temperatura
            humidity = max(15, min(95, 75 - 1.5 * (temp - 16) + rng.normal(0, 5)))

            # Punto de rocío (derivado simple)
            dewpoint = temp - (100 - humidity) / 5

            # Presión superficial: poca variación
            surface_pressure = 1013 + rng.normal(0, 2)

            # Precipitación: poco común en temporada seca (ene-mar)
            precipitation = 0.0
            if ts.month >= 5 and rng.random() < 0.05:
                precipitation = rng.exponential(2.0)

            # Cobertura nubosa
            cloud_cover = max(0, min(100, 30 + rng.normal(0, 25)))

            # Radiación solar: cero de noche, máx al mediodía
            if 6 <= hour <= 18:
                radiation = 800 * np.sin(np.pi * (hour - 6) / 12) * (1 - cloud_cover / 200)
                radiation = max(0, radiation + rng.normal(0, 50))
            else:
                radiation = 0.0

            # Viento: bajo en madrugada, sube en tarde
            wind_speed = max(0, 8 + 4 * np.sin(2 * np.pi * (hour - 6) / 24) + rng.normal(0, 2))
            wind_direction = rng.uniform(0, 360)
            wind_gusts = wind_speed * (1.3 + rng.random() * 0.4)

            records.append({
                "timestamp": ts,
                id_col: punto_id,
                "latitude_centroide": lat,
                "longitude_centroide": lon,
                "temp_2m": round(temp, 2),
                "humidity_2m": round(humidity, 2),
                "dewpoint_2m": round(dewpoint, 2),
                "surface_pressure": round(surface_pressure, 2),
                "precipitation": round(precipitation, 2),
                "cloud_cover": round(cloud_cover, 2),
                "shortwave_radiation": round(radiation, 2),
                "wind_speed_10m": round(wind_speed, 2),
                "wind_direction_10m": round(wind_direction, 2),
                "wind_gusts_10m": round(wind_gusts, 2),
            })

    df = pd.DataFrame.from_records(records)
    df["ingestion_timestamp"] = pd.Timestamp.now()

    # ~2% NULLs en meteo (más confiable que SIMAT)
    null_mask = rng.random(len(df)) < 0.02
    meteo_vars = [
        "temp_2m", "humidity_2m", "dewpoint_2m", "surface_pressure",
        "precipitation", "cloud_cover", "shortwave_radiation",
        "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
    ]
    for var in meteo_vars:
        var_nulls = rng.random(len(df)) < 0.02
        df.loc[var_nulls, var] = np.nan

    return df.sort_values(["timestamp", id_col]).reset_index(drop=True)


# =============================================================================
# API PÚBLICA
# =============================================================================

def generate_silver_fixtures(
    start_date: str = "2024-01-01",
    end_date: str = "2024-04-01",
    seed: int = 42,
    granularidad_meteo: str = "zone",
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Genera los DataFrames sintéticos de Silver para desarrollo de Gold.

    Args:
        start_date: fecha inicial inclusiva (YYYY-MM-DD)
        end_date: fecha final exclusiva (YYYY-MM-DD)
        seed: semilla del RNG para reproducibilidad
        granularidad_meteo: "zone" (5 puntos) o "station" (10 puntos)

    Returns:
        (df_observaciones, df_meteo) — ambos cumpliendo el contrato v1.0
    """
    rng = np.random.default_rng(seed)
    print(f"[fixture] Generando observaciones de {start_date} a {end_date}...")
    obs = _generate_observations(start_date, end_date, rng)
    print(f"[fixture] {len(obs):,} filas de observaciones generadas")
    print(f"[fixture] Generando meteo (granularidad={granularidad_meteo})...")
    meteo = _generate_meteo(start_date, end_date, rng, granularidad_meteo)
    print(f"[fixture] {len(meteo):,} filas de meteo generadas")
    return obs, meteo


if __name__ == "__main__":
    # CLI: genera y guarda los fixtures
    import sys
    from pathlib import Path

    output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    obs, meteo = generate_silver_fixtures()

    obs_path = output_dir / "silver_obs_synthetic.parquet"
    meteo_path = output_dir / "silver_meteo_synthetic.parquet"

    obs.to_parquet(obs_path, compression="snappy", index=False)
    meteo.to_parquet(meteo_path, compression="snappy", index=False)

    print(f"\n✓ Observaciones: {obs_path} ({obs_path.stat().st_size / 1e6:.2f} MB)")
    print(f"✓ Meteo:         {meteo_path} ({meteo_path.stat().st_size / 1e6:.2f} MB)")

    # Validaciones rápidas
    print("\n=== VALIDACIÓN DE CONTRATO ===")
    print(f"Stations únicos en obs:   {obs['station_id'].nunique()}")
    print(f"Zonas únicas en obs:      {sorted(obs['zone'].unique())}")
    print(f"Contaminantes:            {sorted(obs['contaminante'].unique())}")
    print(f"% nulls en valor:         {obs['valor'].isna().mean()*100:.2f}%")
    print(f"Rango de timestamp:       {obs['timestamp'].min()} a {obs['timestamp'].max()}")
    print(f"Stations únicos en meteo: {meteo.iloc[:, 1].nunique()} (col '{meteo.columns[1]}')")

    # Validación: los eventos plantados están elevados
    print("\n=== EVENTOS DE CONTINGENCIA PLANTADOS ===")
    for evt in CONTINGENCIAS_PLANTADAS:
        target_ts = pd.Timestamp(evt["fecha"]) + pd.Timedelta(hours=evt["hora_pico"])
        mask = (
            (obs["timestamp"] == target_ts)
            & (obs["zone"] == evt["zone"])
            & (obs["contaminante"] == evt["cont"])
        )
        valores = obs.loc[mask, "valor"].dropna()
        print(f"  {evt['fecha']} {evt['hora_pico']:02d}:00 zona={evt['zone']} "
              f"{evt['cont']} → esperado≈{evt['pico']}, valores={valores.tolist()}")
