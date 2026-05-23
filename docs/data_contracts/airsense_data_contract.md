# Contrato de Datos — AirSense MX

**Versión:** 1.0  
**Última actualización:** [fecha]  
**Owners:** Gustavo (modelo), Antonio (pipeline)  
**Estado:** ✅ Acordado

---

## 1. Propósito

Este documento define las **interfaces de datos** entre las dos rutas de trabajo del proyecto:

- **Antonio** entrega: `silver.observaciones_horarias` y `silver.meteo_horario`
- **Gustavo** entrega: `gold.predicciones_diarias`

Ambos consumen: `dim_estaciones` (tabla dimensional compartida)

**Regla de oro:** ningún cambio a estos schemas sin un PR a este documento aprobado por ambos owners. Si rompemos esto, perdemos medio día de debugging.

---

## 2. Convenciones generales

| Aspecto | Convención |
|---|---|
| **Formato de archivo** | Parquet con compresión Snappy |
| **Encoding de strings** | UTF-8 |
| **Timezone de timestamps** | Hora local CDMX (UTC-6, sin DST). NO convertir a UTC. La columna canónica es `datetime_local` (timezone-naive). Ver §7.5 para reglas completas. |
| **Representación de NULL** | NULL nativo de Parquet. NUNCA usar -99, NaN, "NULL", "", -1. |
| **Particionado** | Hive-style: `year=YYYY/month=MM/` |
| **Catálogo** | AWS Glue Data Catalog, bases `airsense_silver` y `airsense_gold` |
| **Naming columnas** | `snake_case`, todo en minúsculas, sin acentos |
| **Tipos numéricos** | DOUBLE para valores físicos; INT para conteos/horizontes; STRING para categóricos |

### Bucket S3

```
s3://airsense-mx/
├── bronze/         (Antonio)
│   ├── rama/{contaminante}/{anio}.xls
│   ├── openmeteo/{station_id}/{anio}.json
│   └── pcaa/contingencias_historicas.pdf
├── silver/         (Antonio publica)
│   ├── observaciones_horarias/year=YYYY/month=MM/
│   └── meteo_horario/year=YYYY/month=MM/
├── gold/           (Gustavo publica)
│   └── predicciones_diarias/year=YYYY/month=MM/
├── dim/            (compartido, version-controlado en repo)
│   └── dim_estaciones.csv
└── models/         (Gustavo)
    └── {modelo}/{version}/model.tar.gz
```

---

## 3. Tabla compartida: `dim_estaciones`

**Owner:** Antonio (con validación cruzada de Gustavo)  
**Path:** `s3://airsense-mx/dim/dim_estaciones.csv`  
**Versionado:** en Git (`data/dim_estaciones.csv`), cualquier cambio = PR

### Schema

| Columna | Tipo | Nullable | Descripción |
|---|---|---|---|
| `station_id` | STRING(3) | NO | Clave oficial SIMAT (PK). Ej: "AJU", "FAC" |
| `station_name` | STRING | NO | Nombre oficial corto. Ej: "Ajusco" |
| `station_name_full` | STRING | SÍ | Nombre largo descriptivo |
| `zone` | STRING(2) | NO | Una de: `NO`, `NE`, `SE`, `SO`, `CE` |
| `zone_full` | STRING | NO | Nombre completo de la zona |
| `municipality` | STRING | NO | Alcaldía o municipio |
| `state` | STRING | NO | "Ciudad de México" o "Estado de México" |
| `latitude` | DOUBLE | SÍ | Grados decimales WGS84, 4+ decimales |
| `longitude` | DOUBLE | SÍ | Grados decimales WGS84, 4+ decimales |
| `altitude_masl` | INT | SÍ | Metros sobre el nivel del mar |
| `pollutants_measured` | STRING | NO | Lista separada por `;`. Ej: "O3;NO2;PM10;PM25" |
| `is_active` | BOOLEAN | NO | TRUE si opera actualmente |
| `notes` | STRING | SÍ | Notas, conflictos documentados, fuentes |

### Reglas de calidad
1. `station_id` único (PK).
2. Si `is_active = TRUE`, entonces `latitude` y `longitude` NO pueden ser NULL.
3. `zone` debe estar en el set `{NO, NE, SE, SO, CE}`.
4. Cualquier conflicto entre fuentes debe documentarse en `notes`.

---

## 4. Tabla: `silver.observaciones_horarias`

**Owner:** Antonio  
**Path:** `s3://airsense-mx/silver/observaciones_horarias/year=YYYY/month=MM/`  
**Granularidad:** una fila por `(timestamp, station_id, contaminante)`

### Schema

| Columna | Tipo | Nullable | Descripción |
|---|---|---|---|
| `timestamp` | TIMESTAMP | NO | Hora local CDMX. Construido como `FECHA + (HORA - 1) horas`. Ver §7.1. |
| `station_id` | STRING | NO | FK soft a `dim_estaciones.station_id` |
| `zone` | STRING | NO | Denormalizado desde dim para evitar joins en Athena |
| `contaminante` | STRING | NO | Una de: `O3`, `PM25`, `PM10`, `NO2`, `SO2`, `CO`. Mayúsculas, sin punto. |
| `valor` | DOUBLE | SÍ | Medición. NULL si raw era -99. Ver §7.2 para unidades. |
| `latitude` | DOUBLE | SÍ | Denormalizado desde dim |
| `longitude` | DOUBLE | SÍ | Denormalizado desde dim |
| `municipality` | STRING | SÍ | Denormalizado desde dim |
| `ingestion_timestamp` | TIMESTAMP | NO | Cuándo se generó esta fila (auditoría) |

### Particiones

```
year=YYYY/month=MM/
```

Donde `year` y `month` coinciden con el `timestamp` de la fila.

### Reglas de calidad (Antonio valida antes de publicar)

1. **No -99 en `valor`** — debe ser NULL.
2. **station_id válido** — debe existir en `dim_estaciones`. Si aparece un station_id no listado en dim, escribir log y agregar a dim antes de publicar.
3. **Sin duplicados** — clave única: `(timestamp, station_id, contaminante)`.
4. **Rango de timestamp plausible** — entre 2015-01-01 y la fecha actual.
5. **Particiones consistentes** — `year` y `month` de la partición deben coincidir con el `timestamp` de la fila.
6. **Cobertura mínima** — para cada combinación `(año, contaminante)`, al menos 80% de las estaciones activas tienen al menos 50% de horas no-nulas. Si no, marcar el año como "calidad degradada" en metadata.

### Ejemplo de fila

```
timestamp           | station_id | zone | contaminante | valor | latitude | longitude | municipality | ingestion_timestamp
2024-02-22 15:00:00 | AJU        | SO   | O3           | 167.0 | 19.1543  | -99.1626  | Tlalpan      | 2026-05-22 18:30:00
2024-02-22 15:00:00 | LLA        | NE   | O3           | NULL  | 19.5788  | -99.0397  | Ecatepec...  | 2026-05-22 18:30:00
```

---

## 5. Tabla: `silver.meteo_horario`

**Owner:** Antonio  
**Path:** `s3://airsense-mx/silver/meteo_horario/year=YYYY/month=MM/`  
**Granularidad:** una fila por `(timestamp, station_id)`

### Schema

| Columna | Tipo | Nullable | Descripción | Unidad |
|---|---|---|---|---|
| `timestamp` | TIMESTAMP | NO | Hora local CDMX, alineado con RAMA | — |
| `station_id` | STRING | NO | FK soft a `dim_estaciones.station_id` | — |
| `latitude` | DOUBLE | NO | Coordenada usada para llamar Open-Meteo | grados |
| `longitude` | DOUBLE | NO | Coordenada usada para llamar Open-Meteo | grados |
| `temp_2m` | DOUBLE | SÍ | Temperatura a 2m | °C |
| `humidity_2m` | DOUBLE | SÍ | Humedad relativa a 2m | % |
| `dewpoint_2m` | DOUBLE | SÍ | Punto de rocío a 2m | °C |
| `surface_pressure` | DOUBLE | SÍ | Presión a nivel de superficie | hPa |
| `precipitation` | DOUBLE | SÍ | Precipitación total esa hora | mm |
| `cloud_cover` | DOUBLE | SÍ | Cobertura nubosa total | % |
| `shortwave_radiation` | DOUBLE | SÍ | Radiación solar de onda corta | W/m² |
| `wind_speed_10m` | DOUBLE | SÍ | Velocidad del viento a 10m | km/h |
| `wind_direction_10m` | DOUBLE | SÍ | Dirección del viento a 10m (0=N, 90=E) | grados |
| `wind_gusts_10m` | DOUBLE | SÍ | Ráfagas de viento a 10m | km/h |
| `ingestion_timestamp` | TIMESTAMP | NO | Auditoría | — |

### Particiones

```
year=YYYY/month=MM/
```

### Reglas de calidad

1. **Misma cardinalidad temporal que RAMA** — para cada `(year, month)`, debe haber registros para todas las horas del mes.
2. **station_id válido** — debe existir en dim.
3. **Sin duplicados** — clave: `(timestamp, station_id)`.
4. **Rangos plausibles** — alertar (no rechazar) si `temp_2m > 45` o `< -10`, `wind_speed_10m > 150`, `humidity_2m > 100`.

### 7.5. Regla crítica de timezone y timestamps

**Toda la capa Silver preserva la temporalidad original en hora local CDMX.** Esta regla no es negociable.

#### Columna canónica

```python
datetime_local  # datetime64[ns], timezone-naive, hora CDMX UTC-6
```

#### Reglas de implementación

| Regla | ✅ Correcto | ❌ Prohibido |
|-------|-----------|-------------|
| Timezone | Naive (sin tzinfo) | `tz_localize()`, `tz_convert()` |
| Offset | UTC-6 fijo | Offsets dinámicos verano/invierno |
| DST | No aplicar | Nunca ajustar por horario de verano |
| Sistema | Ignorar tz del OS | `datetime.now()` sin control de tz |
| UTC | No usar | `tz_localize("UTC")` o conversiones a UTC |

#### Razón de negocio

Cambiar a UTC rompería:
- Alineación temporal entre RAMA/SIMAT y Open-Meteo
- Interpretación regulatoria (umbrales PCAA operan en hora local)
- Joins horarios entre `observaciones_horarias` y `meteo_horario`
- Comparabilidad con reportes oficiales SIMAT
- Agregaciones temporales (picos diurnos, patrones de tráfico)

#### Validación obligatoria antes de escribir Parquet

```python
assert df["datetime_local"].dt.tz is None, "datetime_local debe ser timezone-naive"
assert df["hour"].between(0, 23).all(), "hora debe estar en rango [0, 23]"
```

---

### 7.6. Variables que NO se ingieren de Open-Meteo
- `snow*`, `weather_code`, `apparent_temperature`
- `cloud_cover_low/mid/high` (basta con `cloud_cover` total)
- `soil_temperature_*` y `soil_moisture_*` a profundidades
- `wind_speed_100m` y `wind_direction_100m` (suficiente con 10m para PM y O3 a nivel respiratorio)
- `reference_evapotranspiration`, `vapour_pressure_deficit`

Si en alguna iteración futura se necesita alguna, se actualiza este contrato.

---

## 6. Tabla: `gold.predicciones_diarias`

**Owner:** Gustavo  
**Path:** `s3://airsense-mx/gold/predicciones_diarias/year=YYYY/month=MM/`  
**Granularidad:** una fila por `(fecha_prediccion, fecha_objetivo, station_id, contaminante)`  
**Frecuencia de actualización:** diaria (batch transform)

### Schema

| Columna | Tipo | Nullable | Descripción |
|---|---|---|---|
| `fecha_prediccion` | DATE | NO | Día en que se ejecutó el modelo (run date) |
| `fecha_objetivo` | DATE | NO | Día que se está prediciendo |
| `horizonte_dias` | INT | NO | `fecha_objetivo - fecha_prediccion`. Valores: 1, 2, 3, 4, 5, 6, 7 |
| `station_id` | STRING | NO | Estación a la que aplica la predicción |
| `zone` | STRING | NO | Denormalizado |
| `contaminante` | STRING | NO | `O3`, `PM25`, `PM10` (no predecimos NO2/SO2/CO en v1.0) |
| `valor_predicho` | DOUBLE | NO | Predicción puntual (ej. máx 1h para O3, prom 24h para PM) |
| `valor_p10` | DOUBLE | SÍ | Percentil 10 del intervalo de predicción |
| `valor_p90` | DOUBLE | SÍ | Percentil 90 del intervalo de predicción |
| `umbral_contingencia` | DOUBLE | NO | Umbral aplicable a ese contaminante (ej. 140 ppb para O3) |
| `probabilidad_contingencia` | DOUBLE | NO | P(valor > umbral) ∈ [0, 1] |
| `semaforo` | STRING | NO | `verde`, `amarillo`, `naranja`, `rojo` (ver §7.3) |
| `modelo_version` | STRING | NO | Ej: `lgbm_v1.0`, `lgbm_v1.1` |
| `ingestion_timestamp` | TIMESTAMP | NO | Cuándo se escribió la fila |

### Particiones

```
year=YYYY/month=MM/
```

Particionado por `fecha_objetivo`, NO por `fecha_prediccion`. Razón: Streamlit consulta "qué se predice para mañana", no "qué se predijo el martes pasado".

### Reglas de calidad

1. `horizonte_dias` = `fecha_objetivo - fecha_prediccion` (consistencia).
2. `probabilidad_contingencia` ∈ [0, 1].
3. `semaforo` derivado por la función documentada en §7.3 (Streamlit no recalcula, solo lee).
4. Para cada `fecha_prediccion`, se generan filas para `horizonte_dias ∈ {1..7}`, todas las estaciones activas, los 3 contaminantes principales = ~30 estaciones × 7 días × 3 contaminantes = ~630 filas por run.
5. Sin duplicados: clave única `(fecha_prediccion, fecha_objetivo, station_id, contaminante)`.

### Ejemplo de fila

```
fecha_prediccion | fecha_objetivo | horizonte_dias | station_id | zone | contaminante | valor_predicho | valor_p10 | valor_p90 | umbral_contingencia | probabilidad_contingencia | semaforo | modelo_version | ingestion_timestamp
2026-05-22       | 2026-05-23     | 1              | AJU        | SO   | O3           | 145.3          | 128.5     | 162.1     | 140.0               | 0.62                      | naranja  | lgbm_v1.0      | 2026-05-22 06:00:00
2026-05-22       | 2026-05-23     | 1              | PED        | SO   | PM25         | 28.4           | 22.1      | 35.2      | 79.0                | 0.02                      | verde    | lgbm_v1.0      | 2026-05-22 06:00:00
```

---

## 7. Definiciones operacionales (referencia compartida)

### 7.1. Construcción del timestamp desde archivos SIMAT

Los archivos crudos del SIMAT vienen con dos columnas: `FECHA` (date) y `HORA` (1-24, no 0-23).

```python
# Conversión correcta
timestamp = pd.to_datetime(fecha) + pd.to_timedelta(hora - 1, unit="h")

# HORA=1 representa la hora 00:00-01:00 → timestamp = 00:00
# HORA=24 representa la hora 23:00-00:00 → timestamp = 23:00
```

**Trampa:** si no restas 1, todos tus timestamps están corridos una hora, los joins con meteorología fallan silenciosamente, y los picos del modelo apuntan a horas equivocadas.

### 7.2. Unidades de contaminantes

Según el portal SIMAT y la tabla de umbrales oficial:

| Contaminante | Unidad |
|---|---|
| O3, NO2, SO2 | ppb |
| CO | ppm |
| PM10, PM25 | µg/m³ |

Estas son las unidades **nativas** de los archivos. NO se convierten en Silver. Las conversiones (si alguna fuera necesaria en Gold) se hacen explícitas.

### 7.3. Umbrales y semáforo

Constantes en `src/config/umbrales.py` (compartido entre Gustavo y Antonio):

```python
UMBRALES_CONTINGENCIA = {
    "O3":   {"valor": 140, "unidad": "ppb",   "ventana": "max_1h"},
    "NO2":  {"valor": 188, "unidad": "ppb",   "ventana": "max_1h"},
    "SO2":  {"valor": 185, "unidad": "ppb",   "ventana": "max_1h"},
    "PM25": {"valor":  79, "unidad": "ug/m3", "ventana": "avg_24h"},
    "PM10": {"valor": 146, "unidad": "ug/m3", "ventana": "avg_24h"},
}

def calcular_semaforo(valor_predicho: float, umbral: float) -> str:
    """Función oficial, idéntica en producción de Gustavo y consumo de Antonio."""
    if valor_predicho < 0.50 * umbral:
        return "verde"
    elif valor_predicho < 0.75 * umbral:
        return "amarillo"
    elif valor_predicho < 1.00 * umbral:
        return "naranja"
    else:
        return "rojo"
```

**Importante:** este archivo vive en el repo, lo importan ambos. Si alguien lo cambia, es un PR explícito a este contrato.

### 7.4. Catálogo de zonas

```
NO = Noroeste
NE = Noreste
SE = Sureste
SO = Suroeste
CE = Centro
```

Asignación oficial: Gaceta CDMX 28/05/2019 + tabla `simat-entornos.pdf` Tabla 2. Conflictos documentados en `dim_estaciones.notes`.

---

## 8. Flujo de validación en CI (mínimo)

Antes de que Antonio publique a Silver, o Gustavo a Gold, debe correr:

```bash
pytest tests/contracts/ -v
```

Tests mínimos esperados:

- `test_silver_observaciones_schema` — verifica columnas, tipos, nulls esperados.
- `test_silver_observaciones_no_minus99` — verifica que ninguna fila tenga `valor = -99`.
- `test_silver_observaciones_unique_key` — verifica unicidad de `(timestamp, station_id, contaminante)`.
- `test_silver_meteo_aligned_with_obs` — verifica que para cada hora con observaciones existe meteo.
- `test_dim_referential_integrity` — todos los `station_id` en Silver están en dim.
- `test_gold_predicciones_horizon` — `horizonte_dias` = `fecha_objetivo - fecha_prediccion`.
- `test_gold_predicciones_probability_range` — probabilidades ∈ [0,1].
- `test_gold_predicciones_semaforo_consistent` — semáforo derivado correctamente del umbral.

---

## 9. Mocking para desarrollo paralelo

Mientras Antonio termina Silver y Gustavo termina Gold, ambos generan **fixtures sintéticas** que cumplen el contrato:

- Antonio puede consumir `tests/fixtures/gold_predicciones_synthetic.parquet` desde Streamlit.
- Gustavo puede entrenar contra `tests/fixtures/silver_observaciones_synthetic.parquet`.

Generadores en `tests/fixtures/generate_*.py`. Reglas:
- ~10,000 filas mínimo
- Cubren todas las estaciones activas
- Incluyen al menos un evento de contingencia simulado
- Mantienen distribuciones plausibles (no random uniforme)

Cuando el dato real está listo, los fixtures se vuelven solo material de tests unitarios.

---

## 10. Changelog

| Versión | Fecha | Cambios | Aprobado por |
|---|---|---|---|
| 1.0 | [hoy] | Versión inicial | Gustavo, Antonio |

### Política de cambios

1. Cualquier cambio al schema requiere un PR a este documento.
2. El PR debe ser aprobado por ambos owners antes de merge.
3. Cambios breaking (eliminar columna, cambiar tipo) requieren bump de versión major (2.0).
4. Cambios non-breaking (agregar columna nullable) requieren bump minor (1.1).
5. Cualquier cambio se notifica en Slack del equipo el mismo día.

---

## 11. Q&A esperadas

**P: ¿Por qué hora local CDMX y no UTC?**  
R: Los umbrales del PCAA y las decisiones del usuario operan en hora local. Convertir a UTC y reconvertir en Streamlit duplica complejidad sin beneficio. Toda la cadena vive en hora CDMX.

**P: ¿Por qué denormalizar `zone`, `latitude`, `longitude` en Silver?**  
R: Athena cobra por escaneo. Hacer un join con la dim en cada query suma costo. Denormalizar 3 columnas pequeñas reduce queries a una sola tabla. Vale la pena.

**P: ¿Por qué no escribimos NO2/SO2/CO en `gold.predicciones_diarias`?**  
R: En v1.0 nos enfocamos en O3, PM2.5 y PM10 porque concentran el 100% de las contingencias históricas. Los demás se ingieren para usar como features (Silver), no como targets (Gold). Si en una v2.0 ampliamos, agregamos sin cambiar schema (nuevo valor en `contaminante`).

**P: ¿Qué pasa si Open-Meteo da error en algunas horas?**  
R: Antonio escribe NULL en las variables meteorológicas para esa hora. Gustavo maneja NULL en su feature engineering (imputación o exclusión documentada).

**P: ¿Y si el modelo de Gustavo no está listo y Antonio necesita predicciones para demo?**  
R: Gustavo publica fixture sintético en `gold.predicciones_diarias` con `modelo_version = "mock_v0"`. Antonio puede leer y mostrar. Cuando Gustavo libera v1.0, Antonio no cambia código.
