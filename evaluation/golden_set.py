"""Golden set de contingencias históricas del PCAA-SEDEMA.

Parsea el PDF oficial publicado por SEDEMA con el histórico de Contingencias
Ambientales Atmosféricas activadas en la ZMVM (1988-2026), y produce una
tabla estructurada utilizable como benchmark de evaluación del modelo.

PROPÓSITO
=========
El modelo se entrena con datos crudos del SIMAT y deriva sus labels cruzando
los umbrales del PCAA sobre los agregados diarios. Sin embargo, la activación
REAL de una contingencia depende de criterios operativos de SEDEMA (no solo
del umbral matemático). Este archivo captura las decisiones reales para usarse
como evaluación complementaria del modelo.

Métrica principal derivada:
    recall_pcaa = (contingencias reales que el modelo predijo correctamente
                   con N días de anticipación) / (contingencias reales totales)

ESTRUCTURA DEL PDF (entendida tras inspección)
==============================================
- 4 páginas. Una tabla por página con 15 columnas.
- Bloques separados por año: "2026", "2025", ..., "1988"
- Antes de 2020: valores en "INDICE IMECA" (entero). NO COMPARABLES con umbrales.
- A partir de 2020: valores en concentración (µg/m³ o ppb). SÍ COMPARABLES.
- Formato de año en páginas 3-4: con espacios "2 0 1 6" (los más viejos).

DECISIÓN: este parser solo carga registros 2020-2026 (cuando hay concentraciones).
Antes de 2020 se ignora porque el cambio de unidades los hace incomparables y
ya no tenemos datos SIMAT estables para esos años.

USO
===
    from evaluation.golden_set import cargar_golden_set
    golden = cargar_golden_set("data/raw/pcaa/pcaa-historico-contingencias.pdf")

    # filtrar por periodo de test del modelo
    golden_test = golden[
        (golden["fecha_activacion"] >= "2025-10-01") &
        (golden["fecha_activacion"] <= "2026-02-28")
    ]
"""

from __future__ import annotations

import argparse
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd


logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTES
# =============================================================================

# Encabezado esperado en formato moderno (2020+, valores en concentración)
HEADER_MODERN = "Valor de"
HEADER_MODERN_FULL = "Valor de\nactivación"

# Encabezado esperado en formato viejo (pre-2020, valores en INDICE IMECA)
HEADER_OLD = "Valor del"
HEADER_OLD_FULL = "Valor del\nINDICE"

# Año mínimo a parsear: 2020 (cuando cambió a concentración).
YEAR_MIN = 2020

# Normalización de nombres de contaminantes (variantes encontradas en el PDF)
NORMALIZACION_CONTAMINANTES = {
    "Ozono": "O3",
    "PM2.5": "PM25",
    "PM₂.₅": "PM25",
    "PM2.₅": "PM25",
    "PM10": "PM10",
    "PM₁₀": "PM10",
}

# Normalización de zonas (mantenemos los códigos oficiales NO/NE/SE/SO/CE)
ZONAS_VALIDAS = {"NO", "NE", "SE", "SO", "CE"}


# =============================================================================
# MAPEO DE NOMBRES PDF → station_id SIMAT
# =============================================================================
#
# Los reportes oficiales del PCAA reportan estaciones por nombre textual, pero
# los archivos de datos del SIMAT las identifican por clave de 3 letras.
# Este diccionario hace el puente entre ambos universos.
#
# HALLAZGO METODOLÓGICO IMPORTANTE
# --------------------------------
# Durante la auditoría descubrimos una inconsistencia terminológica entre las
# dos publicaciones oficiales de SEDEMA:
#
#     - Catálogo oficial SIMAT (cat_estacion.csv y portal aire.cdmx.gob.mx):
#         AJU = "Ajusco"
#         AJM = "Ajusco Medio"
#
#     - Reportes PCAA (PDF de contingencias):
#         "Ajusco Medio" se asocia a valores que en los datos del SIMAT
#         aparecen registrados en la columna AJU, NO en AJM.
#
# EVIDENCIA: el 22/02/2024 15:00, el PDF reporta "Ajusco Medio — 167 ppb",
# pero el valor 167 está en columna AJU del archivo 2024O3.xls (AJM registró
# 143 ppb esa hora). Validación cruzada confirmada con FAR el 23/02/2024
# (pico 187 ppb del PDF coincide con FAR en el archivo, descartando un
# desorden sistémico).
#
# DECISIÓN: confiamos en los DATOS del SIMAT (fuente primaria, archivos de
# medición directa) sobre los REPORTES del PCAA (fuente secundaria, texto
# preparado por la SEDEMA). Por eso "Ajusco Medio" del PDF se mapea a AJU.
#
# Cada mapeo lleva una bandera de calidad:
#     - "confirmed": validado contra catálogo + dato real, sin conflicto
#     - "inconsistent_pcaa_simat": PDF usa nombre que en SIMAT corresponde
#       a otro station_id (resuelto a favor del dato real)
#     - "needs_validation": no se ha podido validar contra dato real

ESTACION_PDF_A_SIMAT: dict[str, tuple[str, str]] = {
    # Formato: "Nombre como aparece en PDF": (station_id, calidad_mapeo)

    # ---- Confirmados (sin conflicto) ----
    "FES-Acatlán":           ("FAC", "confirmed"),
    "FES Acatlán":           ("FAC", "confirmed"),
    "FES- Acatlán":          ("FAC", "confirmed"),
    "FES-Aragón":            ("FAR", "confirmed"),
    "FES Aragón":            ("FAR", "confirmed"),
    "Santiago Acahualtepec": ("SAC", "confirmed"),
    "Cuajimalpa":            ("CUA", "confirmed"),
    "Pedregal":              ("PED", "confirmed"),
    "Tlalnepantla":          ("TLA", "confirmed"),
    "Atizapán":              ("ATI", "confirmed"),
    "Atizapan":              ("ATI", "confirmed"),
    "Cuautitlán":            ("CUT", "confirmed"),
    "Tultitlán":             ("TLI", "confirmed"),
    "Gustavo A. Madero":     ("GAM", "confirmed"),
    "Benito Juárez":         ("BJU", "confirmed"),
    "Benito Juarez":         ("BJU", "confirmed"),
    "UAM-Iztapalapa":        ("UIZ", "confirmed"),
    "UAM Iztapalapa":        ("UIZ", "confirmed"),
    "UAM-Xochimilco":        ("UAX", "confirmed"),
    "UAM Xochimilco":        ("UAX", "confirmed"),
    "Nezahualcóyotl":        ("NEZ", "confirmed"),
    "Camarones":             ("CAM", "confirmed"),
    "Tláhuac":               ("TAH", "confirmed"),
    "Merced":                ("MER", "confirmed"),
    "Santa Fe":              ("SFE", "confirmed"),
    "Villa de las Flores":   ("VIF", "confirmed"),
    "Xalostoc":              ("XAL", "confirmed"),
    "Centro de Ciencias de la Atmósfera": ("CCA", "confirmed"),
    "Centro de Ciencias de la Atmosfera": ("CCA", "confirmed"),  # sin acento

    # ---- Inconsistencia documentada PCAA vs SIMAT ----
    # "Ajusco Medio" en el PDF → AJU en SIMAT (NO a AJM como sugeriría el catálogo).
    # Validado con dato real del 22/02/2024 (167 ppb en AJU, 143 en AJM).
    "Ajusco Medio": ("AJU", "inconsistent_pcaa_simat"),

    # ---- Por simetría asumimos inversión, pero sin caso de uso confirmado ----
    # No tenemos un evento PCAA reportado como "Ajusco" (a secas) en 2020+, así
    # que mantenemos el mapeo simétrico como hipótesis a validar.
    "Ajusco": ("AJM", "needs_validation"),

    # ---- Estaciones desincorporadas pero aparecen en histórico antiguo ----
    "ENEP Acatlán":          ("EAC", "confirmed"),
    "ENEP-Acatlán":          ("EAC", "confirmed"),
    "Plateros":              ("PLA", "confirmed"),
    "Azcapotzalco":          ("AZC", "confirmed"),
    "Tacuba":                ("TAC", "confirmed"),

    # ---- Zonas múltiples / referencias regionales sin estación específica ----
    # Estos vienen como "estacion_activacion" cuando la contingencia se activa
    # por valor regional (promedio zonal) y no por una estación puntual.
    "Regional":              (None, "regional_aggregate"),
    "ZMVM":                  (None, "regional_aggregate"),
}


def mapear_estacion_a_station_id(nombre_pdf: Optional[str]) -> tuple[Optional[str], str]:
    """Mapea un nombre de estación del PDF al station_id del SIMAT.

    Args:
        nombre_pdf: nombre textual de la estación como aparece en el PDF
                    (puede tener \\n o espacios extra del parser).

    Returns:
        Tupla (station_id, calidad_mapeo).
        - station_id puede ser None si la entrada es regional o desconocida.
        - calidad_mapeo es uno de: "confirmed", "inconsistent_pcaa_simat",
          "needs_validation", "regional_aggregate", "unknown".

    Maneja casos compuestos como "FES-Acatlán, Tlalnepantla y Camarones" donde
    se toma la primera estación listada (que es la que reporta el valor de
    activación según convención SEDEMA).
    """
    if not nombre_pdf:
        return (None, "unknown")

    # Limpieza: quita saltos de línea y espacios extra
    nombre = nombre_pdf.replace("\n", " ").strip()
    # Colapsa espacios múltiples a uno solo
    nombre = re.sub(r"\s+", " ", nombre)

    # Caso compuesto: "Estación A, Estación B y Estación C"
    # Tomamos la primera (la que dispara la activación)
    for sep in (", ", " y ", " / "):
        if sep in nombre:
            nombre = nombre.split(sep)[0].strip()
            break

    # Búsqueda directa
    if nombre in ESTACION_PDF_A_SIMAT:
        return ESTACION_PDF_A_SIMAT[nombre]

    # Búsqueda case-insensitive como fallback
    for k, v in ESTACION_PDF_A_SIMAT.items():
        if k.lower() == nombre.lower():
            return v

    return (None, "unknown")


# =============================================================================
# DETECCIÓN DE MARCADORES DE AÑO
# =============================================================================

def _es_marcador_anio(row: list) -> Optional[int]:
    """Detecta si una fila del PDF es marcador de año.

    Args:
        row: lista de strings/None (una fila extraída).

    Returns:
        El año como int si la fila es marcador, None en otro caso.

    Detecta dos formatos:
      - Moderno: ["2026", None, None, ...]
      - Viejo:   ["2 0 1 6", None, None, ...] (con espacios entre dígitos)
    """
    no_nulos = [c for c in row if c is not None]
    if len(no_nulos) != 1:
        return None

    candidato = no_nulos[0].strip()

    # Formato moderno: "2026"
    if candidato.isdigit() and len(candidato) == 4:
        return int(candidato)

    # Formato viejo: "2 0 1 6"
    sin_espacios = candidato.replace(" ", "")
    if sin_espacios.isdigit() and len(sin_espacios) == 4:
        return int(sin_espacios)

    return None


def _es_fila_encabezado(row: list) -> bool:
    """Identifica si una fila es encabezado de columnas (no dato)."""
    primera = (row[0] or "").strip() if row else ""
    return primera in ("Contaminante", "INICIO", "")


# =============================================================================
# NORMALIZACIÓN DE CAMPOS
# =============================================================================

def _normalizar_contaminante(raw: Optional[str]) -> Optional[str]:
    """Normaliza el nombre del contaminante a códigos canónicos (O3, PM25, etc.)."""
    if not raw:
        return None
    raw = raw.strip()
    return NORMALIZACION_CONTAMINANTES.get(raw, raw)


def _normalizar_zona(raw: Optional[str]) -> Optional[str]:
    """Normaliza zona a códigos NO/NE/SE/SO/CE. Maneja zonas compuestas (CE / SO)."""
    if not raw:
        return None
    raw = raw.strip().upper()
    # Casos compuestos: "CE / SO", "NE y SE"
    for sep in (" / ", " Y ", "/"):
        if sep in raw:
            zonas = [z.strip() for z in raw.split(sep)]
            zonas_validas = [z for z in zonas if z in ZONAS_VALIDAS]
            if zonas_validas:
                return ",".join(zonas_validas)
    return raw if raw in ZONAS_VALIDAS else raw  # devolvemos tal cual si no matchea


def _parsear_fecha(raw: Optional[str]) -> Optional[pd.Timestamp]:
    """Parsea fechas en formato DD/MM/YYYY del PDF."""
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return pd.to_datetime(raw, format=fmt)
        except (ValueError, TypeError):
            continue
    return None


def _parsear_hora(raw: Optional[str]) -> Optional[str]:
    """Normaliza hora a formato HH:MM."""
    if not raw:
        return None
    raw = raw.strip()
    # Formatos comunes: "14:00", "14"
    if ":" in raw:
        return raw
    if raw.isdigit():
        return f"{int(raw):02d}:00"
    return None


def _parsear_valor(raw: Optional[str]) -> Optional[float]:
    """Parsea un valor numérico, manejando casos como '107.3' o '106.9 y 100.2'."""
    if not raw:
        return None
    raw = raw.strip()
    # Si trae múltiples valores separados (zona compuesta), tomar el primero
    for sep in (" y ", ","):
        if sep in raw:
            raw = raw.split(sep)[0].strip()
            break
    # Quitar caracteres no numéricos al final (ej. asteriscos de notas)
    match = re.match(r"[\d.]+", raw)
    if match:
        try:
            return float(match.group())
        except ValueError:
            return None
    return None


def _parsear_fase(raw: Optional[str]) -> Optional[str]:
    """Normaliza fase: 'I', 'II', 'I Regional', 'I - ZMVM', etc."""
    if not raw:
        return None
    raw = raw.strip()
    return raw if raw else None


# =============================================================================
# PARSER PRINCIPAL
# =============================================================================

def _parsear_fila_evento(
    row: list,
    anio_actual: int,
) -> Optional[dict]:
    """Convierte una fila del PDF en un dict estructurado de contingencia.

    Mapeo de columnas (formato moderno 2020+):
        0:  Contaminante
        1:  Zona
        2:  Valor de activación (µg/m³ o ppb)
        3:  Estación
        4:  Día de la semana
        5:  Fecha de activación
        6:  Hora
        7:  Fase
        8:  Valor máximo
        9:  Estación (del máximo)
        10: Fecha (del máximo)
        11: Hora (del máximo)
        12: Fecha de desactivación
        13: Hora de desactivación
        14: Valor de desactivación

    Args:
        row: fila cruda del PDF.
        anio_actual: año del bloque al que pertenece (de _es_marcador_anio).

    Returns:
        Dict con campos normalizados, o None si la fila no es válida.
    """
    if not row or len(row) < 8:
        return None

    contaminante = _normalizar_contaminante(row[0])
    if not contaminante:
        return None

    # Filtrar filas que no son contingencias (fragmentos, headers)
    if contaminante in ("Contaminante", "INICIO", "DURANTE", "LEVANTAMIENTO"):
        return None

    fecha_act = _parsear_fecha(row[5])
    if fecha_act is None:
        return None

    # Sanity check: la fecha debe coincidir con el año del bloque
    if fecha_act.year != anio_actual:
        logger.warning(
            f"Fecha {fecha_act.date()} no coincide con bloque año {anio_actual}, "
            f"se mantiene la fecha real"
        )

    evento = {
        "contaminante": contaminante,
        "zona": _normalizar_zona(row[1]),
        "valor_activacion": _parsear_valor(row[2]),
        "estacion_activacion": (row[3] or "").strip() or None,
        "dia_semana": (row[4] or "").strip() or None,
        "fecha_activacion": fecha_act,
        "hora_activacion": _parsear_hora(row[6]),
        "fase": _parsear_fase(row[7]) if len(row) > 7 else None,
        "valor_maximo": _parsear_valor(row[8]) if len(row) > 8 else None,
        "estacion_maximo": ((row[9] or "").strip() or None) if len(row) > 9 else None,
        "fecha_maximo": _parsear_fecha(row[10]) if len(row) > 10 else None,
        "hora_maximo": _parsear_hora(row[11]) if len(row) > 11 else None,
        "fecha_desactivacion": _parsear_fecha(row[12]) if len(row) > 12 else None,
        "hora_desactivacion": _parsear_hora(row[13]) if len(row) > 13 else None,
        "valor_desactivacion": _parsear_valor(row[14]) if len(row) > 14 else None,
        "anio_bloque": anio_actual,
    }

    # Mapeo de nombres de estación a station_id SIMAT (con bandera de calidad)
    sid_act, calidad_act = mapear_estacion_a_station_id(evento["estacion_activacion"])
    sid_max, calidad_max = mapear_estacion_a_station_id(evento["estacion_maximo"])
    evento["station_id_activacion"] = sid_act
    evento["mapeo_calidad_activacion"] = calidad_act
    evento["station_id_maximo"] = sid_max
    evento["mapeo_calidad_maximo"] = calidad_max

    return evento


def parsear_pdf_pcaa(pdf_path: str | Path) -> pd.DataFrame:
    """Parsea el PDF completo del PCAA a un DataFrame estructurado.

    Solo extrae registros del año YEAR_MIN (2020) en adelante, donde los
    valores están en concentración (µg/m³ o ppb) y son comparables con los
    umbrales que usa el modelo.

    Args:
        pdf_path: ruta al PDF oficial del PCAA-SEDEMA.

    Returns:
        DataFrame con una fila por evento de contingencia.
    """
    import pdfplumber  # import lazy: no requerirlo para tests unitarios

    pdf_path = Path(pdf_path)
    logger.info(f"Parseando PDF PCAA desde {pdf_path}")

    eventos = []

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            tables = page.extract_tables()
            if not tables:
                logger.warning(f"Página {i+1} sin tablas extraídas")
                continue

            tabla = tables[0]
            anio_actual: Optional[int] = None

            for row in tabla:
                # Marcador de año
                anio_detectado = _es_marcador_anio(row)
                if anio_detectado is not None:
                    anio_actual = anio_detectado
                    continue

                # Sin año asignado todavía, ignorar
                if anio_actual is None:
                    continue

                # Solo procesar a partir de YEAR_MIN
                if anio_actual < YEAR_MIN:
                    continue

                # Filas de encabezado
                if _es_fila_encabezado(row):
                    continue

                # Intentar parsear como evento
                evento = _parsear_fila_evento(row, anio_actual)
                if evento is not None:
                    eventos.append(evento)

    df = pd.DataFrame(eventos)
    if df.empty:
        logger.warning("No se extrajo ningún evento del PDF")
        return df

    df = df.sort_values("fecha_activacion").reset_index(drop=True)
    logger.info(
        f"Extraídos {len(df)} eventos de contingencia de {df['anio_bloque'].min()} "
        f"a {df['anio_bloque'].max()}"
    )

    # Reporte de calidad del mapeo: cuántas estaciones se mapearon a qué calidad
    if "mapeo_calidad_activacion" in df.columns:
        resumen_calidad = df["mapeo_calidad_activacion"].value_counts()
        logger.info(f"Calidad del mapeo estación→SIMAT: {dict(resumen_calidad)}")
        unknowns = df[df["mapeo_calidad_activacion"] == "unknown"]
        if len(unknowns) > 0:
            estaciones_no_mapeadas = unknowns["estacion_activacion"].dropna().unique()
            logger.warning(
                f"{len(unknowns)} eventos con estación no mapeada. "
                f"Estaciones faltantes en ESTACION_PDF_A_SIMAT: "
                f"{list(estaciones_no_mapeadas)}"
            )

    return df


# =============================================================================
# API PÚBLICA
# =============================================================================

def cargar_golden_set(
    pdf_path: str | Path,
    fecha_inicio: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    solo_fase_1: bool = True,
) -> pd.DataFrame:
    """Carga y filtra el golden set de contingencias.

    Args:
        pdf_path: ruta al PDF del PCAA.
        fecha_inicio: filtro inclusivo (YYYY-MM-DD). Si None, sin filtro.
        fecha_fin: filtro inclusivo (YYYY-MM-DD). Si None, sin filtro.
        solo_fase_1: si True, excluye Fase II y eventos extraordinarios.

    Returns:
        DataFrame de contingencias filtrado, ordenado por fecha.
    """
    df = parsear_pdf_pcaa(pdf_path)
    if df.empty:
        return df

    if fecha_inicio:
        df = df[df["fecha_activacion"] >= pd.Timestamp(fecha_inicio)]
    if fecha_fin:
        df = df[df["fecha_activacion"] <= pd.Timestamp(fecha_fin)]

    if solo_fase_1 and "fase" in df.columns:
        # Fase I, "I Regional", "I - ZMVM", "I"; excluye "II", "Extraordinaria"
        df = df[df["fase"].fillna("").str.startswith("I")]
        df = df[~df["fase"].fillna("").str.contains("II", regex=False)]
        df = df[~df["fase"].fillna("").str.contains("Extraordinaria")]

    return df.reset_index(drop=True)


# =============================================================================
# CLI
# =============================================================================

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Parser del PDF de contingencias PCAA → CSV/Parquet"
    )
    parser.add_argument(
        "--pdf", required=True,
        help="Ruta al PDF oficial del PCAA-SEDEMA",
    )
    parser.add_argument(
        "--output", required=True,
        help="Ruta de salida (extensión .csv o .parquet)",
    )
    parser.add_argument(
        "--fecha-inicio", default=None,
        help="Filtro fecha inicio (inclusiva), formato YYYY-MM-DD",
    )
    parser.add_argument(
        "--fecha-fin", default=None,
        help="Filtro fecha fin (inclusiva), formato YYYY-MM-DD",
    )
    args = parser.parse_args()

    df = cargar_golden_set(args.pdf, args.fecha_inicio, args.fecha_fin)

    out = Path(args.output)
    if out.suffix == ".parquet":
        df.to_parquet(out, compression="snappy", index=False)
    elif out.suffix == ".csv":
        df.to_csv(out, index=False)
    else:
        raise ValueError(f"Extensión no soportada: {out.suffix}")

    logger.info(f"✓ Golden set escrito en {out} ({len(df)} eventos)")
    logger.info(f"  Contaminantes: {sorted(df['contaminante'].unique())}")
    logger.info(f"  Zonas: {sorted(df['zona'].dropna().unique())}")
    logger.info(f"  Rango: {df['fecha_activacion'].min()} a {df['fecha_activacion'].max()}")


if __name__ == "__main__":
    main()
