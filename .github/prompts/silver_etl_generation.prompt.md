# Silver ETL — Generación Automatizada

**Rol:** Principal Data Engineer especializado en pipelines Medallion, MLOps y productos de datos en Python.

**Objetivo:** Implementar ETL Bronze → Silver para convertir datos crudos (Excel RAMA/SIMAT, JSON Open-Meteo) en Parquet limpios, tipificados y listos para análisis.

## Documentos Normativos (Revisar primero)

1. `docs/data_contracts/airsense_data_contract.md`
2. `.github/prompts/data_contract_review.prompt.md`
3. `.github/copilot-instructions.md`

---

## Contexto del Proyecto

| Aspecto | Detalle |
|--------|---------|
| **Proyecto** | AirSense MX (Maestría DS ITAM, mayo 2026) |
| **Producto** | Predicción calidad del aire ZMVM |
| **Arquitectura** | Medallion: Bronze → Silver → Gold |
| **Timezone** | UTC-6 CDMX (naive, sin DST) |

**Fuentes Bronze:**
- RAMA/SIMAT: Excel `.xls` raw
- Open-Meteo: JSON raw
- Dimensión: `data/dim_estaciones.csv`

**Salidas Silver:**
- `silver.observaciones_horarias` (RAMA/SIMAT limpio)
- `silver.meteo_horario` (Open-Meteo normalizado)

---

## Alcance

| ✅ Hacer | ❌ Fuera de Scope |
|--------|---------|
| Bronze → Silver RAMA/SIMAT | Gold layer |
| Bronze → Silver Open-Meteo | Feature engineering (Gustavo) |
| Validación contra dim_estaciones.csv | Model training |
| Parquet particionado year/month | Predictions/contingencias |
| Tests de contrato de datos | Modificar contrato sin avisar |

---

## Principios de Diseño (Orden de Prioridad)

1. **Correctitud de datos** — Nunca sacrificar integridad
2. **Reproducibilidad** — Ejecuciones determinísticas
3. **Compatibilidad analítica** — Athena, Glue, Polars, pandas
4. **Simplicidad operacional** — Legible en <30 min
5. **Escalabilidad** — Soportar años futuros sin refactor

**Reglas:**
- Código explícito y mantenible, NO abstracciones innecesarias
- Funciones pequeñas (<40 líneas), puras, responsabilidad única
- Sin lógica en notebooks, TODO en módulos importables

---

## Arquitectura de la Solución

```
etl/silver/
├── __init__.py
├── rama_silver.py          # Bronze RAMA → Silver observaciones_horarias
├── openmeteo_silver.py     # Bronze Open-Meteo → Silver meteo_horario
├── schemas.py              # Definiciones explícitas de schemas
├── validations.py          # Validaciones de contrato y calidad
└── shared.py               # Utilities compartidas (timezones, nulls, etc)

tests/
├── test_rama_silver.py
├── test_openmeteo_silver.py
└── test_contracts.py
```

**Flujo de cada ETL:**
1. Lectura de Bronze (Excel/JSON)
2. Desnormalización (long format, expand nested)
3. Limpieza de nulls (`-99` → NULL)
4. Normalización temporal (UTC-6 naive, hour=0-23)
5. Casteo de tipos (schema explícito)
6. Validación de contrato
7. Particionamiento y escritura Parquet

---

## Especificaciones Técnicas

### Normalización Temporal Obligatoria

**Columna canónica:** `datetime_local`
- Timezone: naive (sin tzinfo)
- Zona: CDMX UTC-6
- Sin DST
- Granularidad: horaria exacta
- Rango hora: 0-23 (NO 1-24)

**Columnas derivadas** (generadas desde `datetime_local`):
```python
df = df.assign(
    year=df.datetime_local.dt.year.astype("int16"),
    month=df.datetime_local.dt.month.astype("int8"),
    day=df.datetime_local.dt.day.astype("int8"),
    hour=df.datetime_local.dt.hour.astype("int8"),
)
```

### Manejo de Valores Faltantes

**En RAMA/SIMAT:** `-99` = missing value (NO es dato válido)

**Reglas obligatorias:**
- ✅ Convertir TODOS los `-99` a `pd.NA` ANTES de cualquier validación
- ✅ Usar NULL nativo de Parquet
- ❌ Nunca conservar `-99` en Silver
- ❌ Nunca guardar strings `"NULL"`, `"NaN"`, `""`

```python
df = df.replace(-99, pd.NA)
```

### Tipos de Datos Explícitos

**Definir en `schemas.py` (NO inferir):**

| Columna | Tipo | Rango Válido |
|--------|------|-------------|
| `station_id` | string | any |
| `pollutant` | string | O3, PM2.5, PM10, NO2, SO2 |
| `datetime_local` | datetime64[ns] | valid timestamps |
| `value` | Float64 | [0, 500] (contaminantes) |
| `latitude` | float64 | [-19, -14] |
| `longitude` | float64 | [-102, -98] |
| `year` | int16 | [2015, 2030] |
| `month` | int8 | [1, 12] |
| `day` | int8 | [1, 31] |
| `hour` | int8 | [0, 23] |
| `temperature_2m` | Float64 | [-20, 50] |
| `relative_humidity` | Float64 | [0, 100] |

**Nunca usar dtype `object` para columnas numéricas.**

---

## Reglas Específicas por Fuente

### RAMA/SIMAT (Excel)

**Formato entrada:** Wide (estación × hora × contaminante)
**Formato salida:** Long (tidy)

**Transformación:**
1. Leer Excel con `pd.read_excel()`
2. Pivotar a formato long: 1 fila = station_id + pollutant + datetime_local + value
3. Convertir `-99` a NULL
4. Validar station_id contra dim_estaciones.csv
5. Normalizar timestamps a UTC-6 hora 0-23

**Columnas esperadas en salida:**
```
station_id, pollutant, datetime_local, value, latitude, longitude, year, month, day, hour
```

### Open-Meteo (JSON)

**Formato entrada:** Nested JSON con estructura:
```json
{
  "latitude": -19.4,
  "longitude": -99.2,
  "hourly": {
    "time": ["2024-01-01T00:00", "2024-01-01T01:00", ...],
    "temperature_2m": [15.2, 14.8, ...],
    "relative_humidity_2m": [65, 70, ...],
    ...
  }
}
```

**Transformación:**
1. Extraer metadata: latitude, longitude, zona_id
2. Expandir `hourly.*` a columnas
3. Pivotar time a datetime_local (UTC-6 naive)
4. Generar year/month/day/hour
5. Castear tipos

**Columnas esperadas en salida:**
```
station_id, datetime_local, temperature_2m, relative_humidity_2m, [otros], 
year, month, day, hour
```

---

## Particionamiento

**Obligatorio:**
```python
partition_cols=["year", "month"]
```

**Por qué NO particionar por:**
- ❌ `pollutant` → Genera demasiados archivos pequeños
- ❌ `station_id` → Fragmentación extrema
- ❌ `day`, `hour` → Inviable

**Objetivo:**
- 50-250 MB por archivo Parquet
- Dataset consolidado por año/mes
- Optimizado para lecturas en Athena

---

## Validaciones y Calidad

**Validaciones obligatorias ANTES de escribir:**

| Validación | Qué revisar | Acción |
|-----------|-----------|--------|
| Duplicados | group by (station_id, pollutant, datetime_local) | Falla si > 0 |
| Timestamps inválidos | NULL en datetime_local | Falla si > 0 |
| Rangos contaminantes | value ∈ [0, 500] | Log y filtra si inválidos |
| Estaciones desconocidas | station_id ∉ dim_estaciones.csv | Log y filtra |
| Year/Month NULL | datetime_local NULL | Falla si > 0 |
| Timezone naive | datetime_local.dt.tz is None | Falla si False |

**Métricas a registrar:**
```python
{
    "rows_input": int,
    "rows_output": int,
    "null_replacements": int,
    "invalid_ranges": int,
    "invalid_stations": int,
    "duplicates_removed": int,
    "partitions_created": list[str],
    "bytes_written": int,
}
```

---

## Reglas de Implementación

### Pandas — Preferencias

```python
# ✅ Preferir
df = (
    df
    .assign(new_col=...)
    .query("value > 0")
    .pipe(cast_types)
)

# ❌ Evitar
for idx, row in df.iterrows():
    df.loc[idx, 'col'] = ...
df = df.apply(lambda x: ..., axis=1)
```

**Operaciones vectorizadas siempre.**

### Polars vs Pandas

Usar Polars si proporciona:
- +50% de speedup en lectura/escritura Parquet
- -30% memoria
- Operaciones columnar más eficientes

Mantener compatibilidad con pandas si hay > 1 consumidor.

---

## Compatibilidad AWS Obligatoria

Los Parquet Silver deben ser legibles por:
- ✅ AWS Athena (SQL)
- ✅ AWS Glue (transformaciones)
- ✅ PyArrow (lectura en Python)
- ✅ DuckDB (análisis local)

**Reglas de escritura:**
```python
table.to_parquet(
    path,
    engine="pyarrow",
    compression="snappy",
    index=False,
    partition_cols=["year", "month"],
)
```

**Nunca:**
- ❌ Índices pandas
- ❌ Columnas unnamed
- ❌ dtypes `object` ambiguos

---

## Logging y Observabilidad

**Importar desde `utils.logging`:**
```python
from utils.logging import get_logger

logger = get_logger(__name__)
```

**Loggear en cada ETL:**
```python
logger.info("Inicio Bronze → Silver RAMA",
    extra={
        "source_path": str(bronze_dir),
        "output_path": str(silver_dir),
    }
)

logger.info("Archivos leídos",
    extra={"count": len(files), "total_bytes": total_size}
)

logger.warning("Valores inválidos encontrados",
    extra={"invalid_count": n_invalid, "action": "filtered"}
)

logger.info("Silver escribido",
    extra={
        "rows_input": n_input,
        "rows_output": n_output,
        "partitions": partitions,
        "bytes_written": file_size,
        "duration_seconds": elapsed,
    }
)
```

---

## Testing Obligatorio

**Test suite:**

| Test | Cobertura | Ejemplo |
|------|-----------|---------|
| `test_rama_parsing` | Lectura Excel | ✓ Abre archivo, valida columnas |
| `test_openmeteo_flatten` | Desnormalización JSON | ✓ Expande hourly.*, verifica shape |
| `test_null_replacement` | `-99` → NULL | ✓ Todos los `-99` convertidos |
| `test_schema_validation` | Tipos correctos | ✓ dtypes matchean schema |
| `test_datetime_normalization` | Timezone UTC-6 | ✓ Naive, hora ∈ [0-23] |
| `test_no_duplicates` | Duplicados | ✓ Count by PK = count total |
| `test_partition_structure` | year/month partition | ✓ Directorio s3://.../{year}/{month} |
| `test_idempotence` | Rerun seguro | ✓ 2da ejecución = 0 cambios |
| `test_station_validation` | station_id ∈ dim | ✓ Todos válidos o filtrados |
| `test_pyarrow_compat` | Lectura PyArrow | ✓ `pa.parquet.read_table()` OK |

**Cobertura mínima:** 80% (críticos 90%)

---

## Regla Medallion

**Bronze es inmutable:**
- ✅ Limpiar en Silver
- ✅ Tipar en Silver
- ✅ Normalizar en Silver
- ✅ Convertir formatos en Silver

**Pero:**
- ❌ NUNCA modificar archivos Bronze
- ❌ NUNCA sobrescribir raw data
- ❌ Siempre leer desde Bronze como fuente of truth

---

## Diseño Incremental

Silver debe soportar reprocesamiento de particiones específicas.

**Parámetros CLI obligatorios:**
```bash
python -m etl.silver rama --start-date 2024-01-01 --end-date 2024-01-31 --overwrite
python -m etl.silver openmeteo --year 2024 --month 01 --overwrite
```

**Lógica:**
- `--start-date`/`--end-date`: Filtrar particiones a procesar
- `--year`/`--month`: Alternativa para seleccionar fecha
- `--overwrite`: DELETE + INSERT para período, NO full refresh

**Ventajas:**
- Recuperación de errores parciales
- Reexecución rápida para debugging
- Escalabilidad: puede procesarse año por año

---

## Cadencia de Ejecución

**Propuesto (futuro):**
- Bronze: Daily (RAMA actualiza diario)
- Silver: Daily (post-Bronze)
- Gold: Weekly (post-Silver)

**Actualmente (desarrollo):**
- Ejecución manual para testing
- Inicializar con 2015-2024

---

## Checklist de Aceptación

- [ ] Bronze → Silver RAMA ejecuta sin errores
- [ ] Bronze → Silver Open-Meteo ejecuta sin errores
- [ ] Todos los `-99` convertidos a NULL
- [ ] Timestamps normalizados UTC-6, hora ∈ [0-23]
- [ ] Schemas explícitos validados (sin dtype object)
- [ ] Particiones generadas `year/month`
- [ ] Tests pasan (80%+ cobertura)
- [ ] Parquet compatible PyArrow + Athena
- [ ] Logging estructurado en todos los ETLs
- [ ] Documentación de data contracts actualizada
- [ ] Git commit con mensaje descriptivo

---

## Referencias

**Estándares obligatorios:**
- `copilot-instructions.md`: Python 3.11, Ruff, Google docstrings español
- `data_contract_review.prompt.md`: Data quality checks
- `airsense_data_contract.md`: Schema definitivo
