#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Inventario de documentación - COMET-RIOBAMBA
Solo lectura. No modifica nada.
"""

import os
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

EXCLUDE_DIRS = {'backups', '_audit_trash', '.venv', '__pycache__', 'data', 'logs', '_logs', 'corpus', 'node_modules'}
INCLUDE_EXTS = {'.md', '.txt', '.rst', '.adoc'}
INCLUDE_ROOTS = [ROOT_DIR, ROOT_DIR / 'docs', ROOT_DIR / 'config', ROOT_DIR / 'scripts']

NOW = datetime.now()
FOUR_WEEKS_AGO = NOW - timedelta(weeks=4)
TWO_MONTHS_AGO = NOW - timedelta(weeks=8)

def should_exclude(path: Path) -> bool:
    parts = set(path.parts)
    return bool(parts & EXCLUDE_DIRS)

def get_doc_files() -> List[Path]:
    files = []
    for root in INCLUDE_ROOTS:
        if not root.exists():
            continue
        for ext in INCLUDE_EXTS:
            for f in root.rglob(f'*{ext}'):
                if f.is_file() and not should_exclude(f):
                    files.append(f)
    return sorted(set(files))

def read_headlines(path: Path, max_lines: int = 10) -> List[str]:
    try:
        content = path.read_text(encoding='utf-8', errors='ignore')
        lines = content.splitlines()
        return lines[:max_lines]
    except Exception:
        return []

def classify_doc(path: Path, stat, headlines: List[str]) -> str:
    mtime = datetime.fromtimestamp(stat.st_mtime)
    
    # VIGENTE: modificado en últimas 4 semanas
    if mtime >= FOUR_WEEKS_AGO:
        return "VIGENTE"
    
    # FÓSIL: >2 meses sin tocar, o contradice config actual
    if mtime < TWO_MONTHS_AGO:
        # Verificar si contradice config actual (heurística simple)
        content = ' '.join(headlines).lower()
        if any(kw in content for kw in ['v5.0', 'v4.', 'dry-run', 'anthropic', 'claude', 'ollama']):
            return "FÓSIL"
        return "FÓSIL"
    
    return "DUDA"

def extract_values(text: str) -> Dict[str, List[str]]:
    """Extrae valores numéricos clave que puedan contradecir."""
    import re
    patterns = {
        'max_posts_per_day': r'max_posts_per_day[\s:=]+(\d+)',
        'cycle_interval': r'cycle_interval[_ ]?(?:seconds)?[\s:=]+(\d+)',
        'spend_limit': r'spend[_ ]?limit[_ ]?(?:usd)?[\s:=]+(\d+(?:\.\d+)?)',
        'max_comments_per_day': r'max_comments_per_day[\s:=]+(\d+)',
        'phase_b_enabled': r'phase_b_enabled[\s:=]+(\d+)',
        'phase_c_enabled': r'phase_c_enabled[\s:=]+(\d+)',
    }
    found = {}
    for key, pat in patterns.items():
        matches = re.findall(pat, text, re.IGNORECASE)
        if matches:
            found[key] = matches
    return found

def main():
    print("🔍 Inventariando documentación...")
    files = get_doc_files()
    print(f"  Encontrados {len(files)} archivos")
    
    inventory = []
    all_values = {}
    
    for f in files:
        try:
            stat = f.stat()
            headlines = read_headlines(f, max_lines=20 if stat.st_size > 100*1024 else 10)
            classification = classify_doc(f, stat, headlines)
            
            # Extraer valores para detectar contradicciones
            full_text = ' '.join(headlines)
            values = extract_values(full_text)
            for k, v in values.items():
                if k not in all_values:
                    all_values[k] = []
                for val in v:
                    all_values[k].append({'file': str(f.relative_to(ROOT_DIR)), 'value': val})
            
            rel_path = f.relative_to(ROOT_DIR)
            inventory.append({
                'ruta': str(rel_path),
                'tamaño_bytes': stat.st_size,
                'ultima_modificacion': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                'clasificacion': classification,
                'primeras_lineas': headlines,
            })
        except Exception as e:
            print(f"  Error procesando {f}: {e}")
    
    # Detectar contradicciones
    contradicciones = []
    for key, entries in all_values.items():
        unique_values = set(e['value'] for e in entries)
        if len(unique_values) > 1:
            contradicciones.append({
                'parametro': key,
                'valores': list(unique_values),
                'fuentes': entries
            })
    
    # Detectar redundancias (títulos similares)
    redundancias = []
    titulos = {}
    for item in inventory:
        if item['primeras_lineas']:
            first = item['primeras_lineas'][0].strip('# ').strip().lower()
            if first:
                if first not in titulos:
                    titulos[first] = []
                titulos[first].append(item['ruta'])
    
    for titulo, rutas in titulos.items():
        if len(rutas) > 1:
            redundancias.append({
                'titulo': titulo,
                'archivos': rutas
            })
    
    # Resumen
    vigentes = sum(1 for i in inventory if i['clasificacion'] == 'VIGENTE')
    fosiles = sum(1 for i in inventory if i['clasificacion'] == 'FÓSIL')
    dudas = sum(1 for i in inventory if i['clasificacion'] == 'DUDA')
    
    # Recomendaciones
    recomendaciones = {
        'conservar': [],
        'consolidar': [],
        'archivar': []
    }
    
    for item in inventory:
        if item['clasificacion'] == 'VIGENTE':
            recomendaciones['conservar'].append(item['ruta'])
        elif item['clasificacion'] == 'FÓSIL':
            recomendaciones['archivar'].append(item['ruta'])
        else:
            recomendaciones['consolidar'].append(item['ruta'])
    
    # Output JSON
    output = {
        'generado_en': NOW.isoformat(),
        'resumen': {
            'total': len(inventory),
            'vigentes': vigentes,
            'fosiles': fosiles,
            'dudas': dudas,
        },
        'documentos': inventory,
        'contradicciones': contradicciones,
        'redundancias': redundancias,
        'recomendaciones': recomendaciones,
    }
    
    out_file = ROOT_DIR / 'data' / f'docs_inventory_{NOW.strftime("%Y%m%d")}.json'
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    
    # Consola
    print("\n" + "=" * 60)
    print("INVENTARIO DOCUMENTACIÓN - RESUMEN")
    print("=" * 60)
    print(f"Total docs:       {len(inventory)}")
    print(f"  VIGENTES:       {vigentes}")
    print(f"  FÓSILES:        {fosiles}")
    print(f"  DUDAS:          {dudas}")
    print()
    
    if contradicciones:
        print("⚠️  CONTRADICCIONES ENCONTRADAS:")
        for c in contradicciones:
            print(f"  {c['parametro']}: {c['valores']}")
            for src in c['fuentes']:
                print(f"    - {src['file']}: {src['value']}")
    else:
        print("✅ Sin contradicciones detectadas")
    print()
    
    if redundancias:
        print("🔄 REDUNDANCIAS (títulos similares):")
        for r in redundancias[:10]:
            print(f"  '{r['titulo'][:60]}': {len(r['archivos'])} archivos")
            for a in r['archivos'][:3]:
                print(f"    - {a}")
    else:
        print("✅ Sin redundancias detectadas")
    print()
    
    print("📋 RECOMENDACIONES:")
    print(f"  Conservar ({len(recomendaciones['conservar'])}): vigentes y útiles")
    print(f"  Consolidar ({len(recomendaciones['consolidar'])}): dudosos, revisar")
    print(f"  Archivar ({len(recomendaciones['archivar'])}): fósiles, mover a backups/")
    
    print(f"\n✅ Inventario guardado en: {out_file}")
    return 0

if __name__ == '__main__':
    sys.exit(main())