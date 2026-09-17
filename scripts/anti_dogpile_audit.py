#!/usr/bin/env python3
"""Auditoría de uso de skip_anti_dogpile en logs del agente COMET-RIOBAMBA.

Analiza los logs del agente para estadísticas sobre el uso de skip_anti_dogpile,
identificando patrones de uso legítimo (posts propios con debate activo) vs. uso
potencialmente incorrecto (sin condiciones adecuadas).

Uso:
    python scripts/anti_dogpile_audit.py [--log-file <ruta>]

Opcional:
    --log-file: Archivo de log específico a analizar (si no se especifica, usa el más reciente).
"""

import re
import sys
import os
from pathlib import Path
from datetime import datetime


def main():
    parser = __import__("argparse").ArgumentParser(
        description="Auditoría de skip_anti_dogpile"
    )
    parser.add_argument(
        "--log-file",
        type=str,
        help="Ruta específica del archivo de log a analizar",
    )
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent.resolve()
    log_dir = project_root / "logs"

    # Determinar qué log analizar
    if args.log_file:
        log_path = Path(args.log_file)
        if not log_path.exists():
            print(f"❌ Error: El archivo {args.log_file} no existe.")
            sys.exit(1)
        log_files = [log_path]
    elif log_dir.exists():
        log_files = sorted(log_dir.glob("*.log"))
        if not log_files:
            print("❌ No se encontraron archivos de log en", log_dir)
            sys.exit(1)
        log_path = log_files[-1]  # Usar el más reciente
    else:
        print("❌ No se encontró directorio de logs:", log_dir)
        sys.exit(1)

    print(f"Analizando log: {log_path.name}")
    print("=" * 60)

    # Leer el log
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            log_content = f.read()
    except Exception as e:
        print(f"❌ Error al leer el log: {e}")
        sys.exit(1)

    # Patrón para encontrar entries de skip_anti_dogpile
    # Formato esperado: [SKIP_ANTI_DOGPILE] post_id=XXX author=XXX: skip_anti_dogpile=True -> own_post=XXX substantive_replies=X skip_anti_dogpile_applied=X
    pattern = re.compile(
        r"\[SKIP_ANTI_DOGPILE\]\s+post_id=(\S+)\s+author=(\S+):\s+"
        r"skip_anti_dogpile=True\s+->\s+own_post=(\S+)\s+"
        r"substantive_replies=(\d+)\s+skip_anti_dogpile_applied=(\w+)"
    )

    # Estadísticas
    stats = {
        "total_entries": 0,
        "own_post_exemptions": 0,  # skip_anti_dogpile con own_post=True y condiciones cumplidas
        "anti_dogpile_activated": 0,  # skip_anti_dogpile en posts ajenos (siempre activado)
        "no_conditions": 0,  # skip_anti_dogpile en posts propios sin suficiente debate
        "cycles_analyzed": set(),
    }

    for match in pattern.finditer(log_content):
        stats["total_entries"] += 1
        post_id = match.group(1)
        author = match.group(2)
        own_post_str = match.group(3)
        substantive_replies = int(match.group(4))
        applied_str = match.group(5)

        # Determinar cycle (buscar en el mismo bloque del log)
        # Por simplicidad, extraemos el cycle del contexto si está disponible
        is_own = own_post_str.strip().lower() == "true"

        # Contar según el tipo
        if not is_own:
            # Posts ajenos: anti-dogpile siempre se activa
            stats["anti_dogpile_activated"] += 1
        else:
            # Posts propios
            stats["own_post_exemptions"] += 1  # Contamos todos los own-post como exenciones potenciales
            if substantive_replies < 3:
                # No cumplen el umbral de 3 replies sustantivas
                stats["no_conditions"] += 1
            # Si substantive_replies >= 3, se considera exención legitimada

    # Mostrar resultados
    print("=" * 60)
    print(f"Estadísticas de anti-dogpile en {log_path.name}")
    print("=" * 60)
    print(f"  Total de entries: {stats['total_entries']}")
    print(f"  Exenciones own-post (con o sin condiciones): {stats['own_post_exemptions']}")
    print(f"  Anti-dogpile activado (posts ajenos): {stats['anti_dogpile_activated']}")
    print(f"  Sin condiciones suficientes (substantive_replies < 3): {stats['no_conditions']}")
    print()

    # Porcentaje de uso correcto
    if stats["total_entries"] > 0:
        correct_usage = (stats["total_entries"] - stats["no_conditions"]) / stats["total_entries"] * 100
        print(f"  Porcentaje de uso correcto: {correct_usage:.1f}%")
    else:
        print("  Porcentaje de uso correcto: N/A (sin entries)")

    # Advertencias
    print()
    if stats["no_conditions"] > 0:
        print(f"⚠️  ALERTA: Se detectaron {stats['no_conditions']} uses de skip_anti_dogpile")
        print("   sin condiciones adecuadas (substantive_replies < 3).")
        print("   Revisar la configuración y los flujos de publicación.")
        print()
        print("   Acciones recomendadas:")
        print("   1. Verificar posts propios con debate activo (>=3 replies sustantivas)")
        print("   2. Ajustar umbrales si el debate natural tiene fewer replies")
        print("   3. Considerar desactivar skip_anti_dogpile si no es necesario")
    else:
        print("✅  OK: Todos los usos de skip_anti_dogpile tienen condiciones adecuadas.")

    if stats["total_entries"] == 0:
        print("\nℹ️  Nota: No se encontraron entries con el patrón esperado SKIP_ANTI_DOGPILE.")
        print("   Esto podría significar:")
        print("   - El logging aún no está activo en el agente")
        print("   - El formato de log ha cambiado")
        print("   - No se han publicado replies recientemente")


if __name__ == "__main__":
    main()