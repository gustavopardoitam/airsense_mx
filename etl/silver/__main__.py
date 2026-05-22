"""Entry point para ejecutar la capa Silver desde CLI.

Uso:
    # Procesar RAMA todos los años disponibles
    python -m etl.silver rama --start-year 2021 --end-year 2024

    # Procesar Open-Meteo solo 2023
    python -m etl.silver openmeteo --start-year 2023 --end-year 2023

    # Reprocesar partición específica de RAMA con overwrite
    python -m etl.silver rama --start-year 2024 --end-year 2024 --overwrite

    # Procesar solo una estación de Open-Meteo
    python -m etl.silver openmeteo --start-year 2023 --end-year 2023 --station-id BJU
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from config import PathsConfig, find_repo_root
from etl.silver.openmeteo_silver import run_openmeteo_silver
from etl.silver.rama_silver import run_rama_silver
from utils.logging import get_logger, setup_logging

logger = get_logger(__name__)

_CURRENT_YEAR = datetime.now().year


def _build_parser() -> argparse.ArgumentParser:
    """Construye el parser CLI con subcomandos rama y openmeteo."""
    parser = argparse.ArgumentParser(
        description="Silver ETL: Bronze → Parquet limpio y tipificado",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    sub = parser.add_subparsers(dest="source", required=True)

    # ── Subcomando RAMA ──────────────────────────────────────────────────────
    rama = sub.add_parser("rama", help="Procesar datos RAMA/SIMAT (Excel)")
    rama.add_argument(
        "--start-year",
        type=int,
        default=2021,
        help="Primer año a procesar (default: 2021)",
    )
    rama.add_argument(
        "--end-year",
        type=int,
        default=_CURRENT_YEAR,
        help=f"Último año a procesar (default: {_CURRENT_YEAR})",
    )
    rama.add_argument(
        "--bronze-dir",
        type=Path,
        default=None,
        help="Directorio Bronze RAMA (default: data/raw/rama/)",
    )
    rama.add_argument(
        "--silver-dir",
        type=Path,
        default=None,
        help=(
            "Directorio Silver salida"
            " (default: data/prep/silver/observaciones_horarias/)"
        ),
    )
    rama.add_argument(
        "--dim-path",
        type=Path,
        default=None,
        help="Ruta a dim_estaciones.csv (default: data/dim_estaciones.csv)",
    )
    rama.add_argument(
        "--overwrite",
        action="store_true",
        help="Sobreescribir particiones Silver existentes",
    )

    # ── Subcomando Open-Meteo ─────────────────────────────────────────────────
    meteo = sub.add_parser("openmeteo", help="Procesar datos Open-Meteo (JSON)")
    meteo.add_argument(
        "--start-year",
        type=int,
        default=2021,
        help="Primer año a procesar (default: 2021)",
    )
    meteo.add_argument(
        "--end-year",
        type=int,
        default=_CURRENT_YEAR,
        help=f"Último año a procesar (default: {_CURRENT_YEAR})",
    )
    meteo.add_argument(
        "--station-id",
        type=str,
        default=None,
        help="Procesar solo esta estación (e.g. BJU)",
    )
    meteo.add_argument(
        "--bronze-dir",
        type=Path,
        default=None,
        help="Directorio Bronze Open-Meteo (default: data/raw/openmeteo/)",
    )
    meteo.add_argument(
        "--silver-dir",
        type=Path,
        default=None,
        help="Directorio Silver salida (default: data/prep/silver/meteo_horario/)",
    )
    meteo.add_argument(
        "--dim-path",
        type=Path,
        default=None,
        help="Ruta a dim_estaciones.csv (default: data/dim_estaciones.csv)",
    )
    meteo.add_argument(
        "--overwrite",
        action="store_true",
        help="Sobreescribir particiones Silver existentes",
    )

    return parser


def main() -> None:
    """Punto de entrada principal del Silver ETL."""
    setup_logging()
    parser = _build_parser()
    args = parser.parse_args()

    repo_root = find_repo_root(Path(__file__))
    paths = PathsConfig.from_repo_root(repo_root)

    if args.source == "rama":
        bronze_dir = args.bronze_dir or paths.data_raw / "rama"
        silver_dir = (
            args.silver_dir
            or paths.data_prep / "silver" / "observaciones_horarias"
        )
        dim_path = args.dim_path or repo_root / "data" / "dim_estaciones.csv"

        metrics = run_rama_silver(
            bronze_dir=bronze_dir,
            silver_dir=silver_dir,
            dim_path=dim_path,
            start_year=args.start_year,
            end_year=args.end_year,
            overwrite=args.overwrite,
        )

    elif args.source == "openmeteo":
        bronze_dir = args.bronze_dir or paths.data_raw / "openmeteo"
        silver_dir = args.silver_dir or paths.data_prep / "silver" / "meteo_horario"
        dim_path = args.dim_path or repo_root / "data" / "dim_estaciones.csv"

        metrics = run_openmeteo_silver(
            bronze_dir=bronze_dir,
            silver_dir=silver_dir,
            dim_path=dim_path,
            start_year=args.start_year,
            end_year=args.end_year,
            station_id_filter=args.station_id,
            overwrite=args.overwrite,
        )

    else:
        parser.print_help()
        sys.exit(1)

    logger.info("Silver ETL finalizado", extra={"source": args.source, **metrics})


if __name__ == "__main__":
    main()
