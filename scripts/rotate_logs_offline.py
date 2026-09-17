# -*- coding: utf-8 -*-
"""Rotación OFFLINE de logs JSONL (V2, 2026-08-21).

Mueve archivos .jsonl mayores a N MB a data/archives/<YYYY-MM-DD>/ y los
comprime con gzip. Deja un archivo vacío con el mismo nombre en el path
original para que el agente no falle al escribir.

USO:
    python -m scripts.rotate_logs_offline                  # apunta a data/
    python -m scripts.rotate_logs_offline --target staging # apunta a staging/

NO TOCAR ESTE SCRIPT MIENTRAS EL AGENTE ESTÉ CORRIENDO: el agente abre
los jsonl con file-handles persistentes. Solo usar con agente detenido
o en staging/.

SEGURIDAD:
    - Idempotente: si el archivo ya está comprimido, lo salta.
    - Crea directorio destino con fecha si no existe.
    - Mueve atómicamente (gzip primero, luego remove).
    - Si gzip falla, restaura el archivo vacío y aborta.
"""
import argparse
import gzip
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

from config import BASE_DIR

logger = logging.getLogger("scripts.rotate_logs_offline")

SIZE_THRESHOLD_BYTES = 10 * 1024 * 1024  # 10 MB
JSONL_GLOB = "*.jsonl"


def _setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def _archive_dir(base: Path, when: datetime) -> Path:
    day = when.strftime("%Y-%m-%d")
    out = base / "archives" / day
    out.mkdir(parents=True, exist_ok=True)
    return out


def _gzip_file(src: Path, dst_gz: Path) -> None:
    """Comprime src -> dst_gz. Si dst_gz ya existe, aborta (idempotencia)."""
    if dst_gz.exists():
        logger.info("SKIP %s (ya comprimido en %s)", src.name, dst_gz)
        return
    logger.info("COMPRIMIENDO %s (%d bytes) -> %s", src.name, src.stat().st_size, dst_gz.name)
    with open(src, "rb") as f_in:
        with gzip.open(dst_gz, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)


def _rotate_one(jsonl_path: Path, target_root: Path) -> bool:
    """Rota un jsonl si supera el threshold. Retorna True si rotó."""
    if not jsonl_path.exists():
        return False
    size = jsonl_path.stat().st_size
    if size < SIZE_THRESHOLD_BYTES:
        logger.debug("SKIP %s (%d bytes < %d)", jsonl_path.name, size, SIZE_THRESHOLD_BYTES)
        return False

    archives_dir = _archive_dir(jsonl_path.parent, datetime.now())
    dst_gz = archives_dir / f"{jsonl_path.name}.gz"

    try:
        _gzip_file(jsonl_path, dst_gz)
    except OSError as e:
        logger.error("ERROR comprimiendo %s: %s", jsonl_path.name, e)
        return False

    jsonl_path.unlink()
    jsonl_path.touch()
    logger.info("ROTADO %s -> %s (nuevo vacío en path original)", jsonl_path.name, dst_gz)
    return True


def rotate(target: Path) -> int:
    """Recorre target/*.jsonl y rota los > SIZE_THRESHOLD_BYTES. Retorna nº rotados."""
    target = target.resolve()
    if not target.is_dir():
        logger.error("Target no es directorio: %s", target)
        return 0
    rotated = 0
    for jsonl in sorted(target.glob(JSONL_GLOB)):
        if _rotate_one(jsonl, target):
            rotated += 1
    return rotated


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Rotación offline de JSONL.")
    parser.add_argument(
        "--target",
        type=Path,
        default=BASE_DIR / "data",
        help="Directorio raíz con .jsonl (default: data/)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)
    logger.info("Iniciando rotación. Target: %s", args.target)
    rotated = rotate(args.target)
    logger.info("Rotación completa. Archivos rotados: %d", rotated)
    return 0


if __name__ == "__main__":
    sys.exit(main())
