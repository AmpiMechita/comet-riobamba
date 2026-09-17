#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Code Inventory - COMET-RIOBAMBA v5.x
Fase 1: Inventario completo de archivos Python. Solo lectura.
"""

import os
import json
import ast
import sys
import re
from datetime import datetime
from pathlib import Path, PurePath
from collections import defaultdict
from typing import Dict, List, Any, Set, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Directorios a excluir
EXCLUDE_DIRS = {
    'backups', '_audit_trash', '.venv', '__pycache__', '.pytest_cache', '.git',
    'data', 'logs', '_logs', 'exports', 'test_data', 'node_modules',
    '.mypy_cache', '.ruff_cache', 'dist', 'build', 'htmlcov'
}

# Sufijos a excluir
EXCLUDE_SUFFIXES = {
    '.bak', '.backup', '.old', '.CORRUPT', '.fuse_hidden'
}

# Extensiones a procesar
INCLUDE_EXT = {'.py'}

def get_rel_path(path: Path) -> PurePath:
    """Obtiene la ruta relativa usando PurePath para compatibilidad Windows."""
    try:
        return PurePath(os.path.relpath(str(path.resolve()), str(ROOT_DIR.resolve())))
    except Exception:
        return PurePath(path.name)

def get_category(rel_path: PurePath) -> str:
    """Clasifica el archivo por su ubicación."""
    parts = rel_path.parts
    
    if parts[0] in {'core', 'phases', 'services', 'config', 'utils', 'tests', 'scripts', 'monitoring', 'attic'}:
        return parts[0]
    elif len(parts) == 1:
        return 'raíz'
    else:
        return 'otros'

def read_file_head(path: Path, max_lines: int = 15) -> List[str]:
    """Lee las primeras N líneas del archivo."""
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = []
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                lines.append(line.rstrip('\n\r'))
            return lines
    except Exception:
        return []

def has_main_block(path: Path) -> bool:
    """Verifica si tiene if __name__ == '__main__'."""
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        return 'if __name__ == "__main__"' in content or "if __name__ == '__main__'" in content
    except Exception:
        return False

def count_lines(path: Path) -> int:
    """Cuenta líneas del archivo."""
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def should_exclude(path: Path) -> bool:
    rel = get_rel_path(path)
    parts = set(rel.parts)
    if parts & EXCLUDE_DIRS:
        return True
    for suf in EXCLUDE_SUFFIXES:
        if path.name.endswith(suf):
            return True
    return False


def parse_imports(path: Path) -> List[str]:
    """Extrae imports del archivo usando AST."""
    imports = []
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module.split('.')[0])
    except Exception:
        pass
    return imports

def find_reverse_imports(module_name: str, all_files: Dict[str, Dict]) -> List[str]:
    """Busca quién importa este módulo."""
    importers = []
    # Variaciones del nombre del módulo
    variants = [module_name]
    if module_name.endswith('._init_'):
        variants.append(module_name[:-7])
    
    for file_path, info in all_files.items():
        for imp in info.get('imports', []):
            for var in variants:
                if imp == var or imp.startswith(var + '.') or var.startswith(imp + '.'):
                    importers.append(file_path)
                    break
    return list(set(importers))

def detect_duplicates(files_info: List[Dict]) -> List[Dict]:
    """Detecta posibles duplicados por nombre o funcionalidad."""
    duplicados = []
    
    # Por nombre similar
    by_name = defaultdict(list)
    for info in files_info:
        base = Path(info['path']).stem
        by_name[base].append(info['path'])
    
    for base, paths in by_name.items():
        if len(paths) > 1:
            duplicados.append({
                'grupo': paths,
                'razon': 'nombres base idénticos'
            })
    
    # Por nombres muy similares (telegram_client / telegram_client_verified)
    name_variants = {}
    for info in files_info:
        stem = Path(info['path']).stem
        # Normalizar: quitar _verified, _old, _new, _v2, etc.
        normalized = re.sub(r'_(verified|old|new|v\d+|fixed|patched|backup)$', '', stem, flags=re.IGNORECASE)
        if normalized not in name_variants:
            name_variants[normalized] = []
        name_variants[normalized].append(info['path'])
    
    for norm, paths in name_variants.items():
        if len(paths) > 1 and paths not in [d['grupo'] for d in duplicados]:
            duplicados.append({
                'grupo': paths,
                'razon': f'nombres similares (base: {norm})'
            })
    
    return duplicados

def main():
    print("🔍 Iniciando inventario de código Python...")
    
    # 1. Encontrar todos los archivos .py
    py_files = []
    for root, dirs, files in os.walk(ROOT_DIR):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            if f.endswith('.py'):
                path = Path(root) / f
                if not should_exclude(path):
                    py_files.append(path)
    
    print(f"  Encontrados {len(py_files)} archivos .py")
    
    # 2. Analizar cada archivo
    all_files = {}
    files_info = []
    
    for path in py_files:
        rel_path = get_rel_path(path)
        stat = path.stat()
        
        # Metadatos básicos
        size_kb = round(stat.st_size / 1024, 1)
        lines = count_lines(path)
        modified = datetime.fromtimestamp(stat.st_mtime).isoformat()
        head = read_file_head(path, 15)
        is_main = has_main_block(path)
        is_test = 'test' in str(rel_path).lower() or path.name.startswith('test_')
        
        # Imports
        imports = parse_imports(path)
        
        category = get_category(rel_path)
        
        info = {
            'path': str(rel_path),
            'categoria': category,
            'kb': size_kb,
            'lineas': lines,
            'fecha': modified,
            'head': head,
            'tiene_main': is_main,
            'es_test': is_test,
            'imports': imports[:20],  # Limitar a 20
            'importado_por': [],  # Se llenará después
            'importa_a': imports[:10],  # Primeros 10
        }
        
        all_files[str(rel_path)] = info
        files_info.append(info)
    
    # 3. Resolver dependencias inversas (quién importa a quién)
    print("  Resolviendo dependencias...")
    module_to_path = {}
    for path_str, info in all_files.items():
        # Convertir path a nombre de módulo
        mod_path = PurePath(path_str).with_suffix('')
        module_name = '.'.join(mod_path.parts)
        module_to_path[module_name] = path_str
    
    for path_str, info in all_files.items():
        mod_path = PurePath(path_str).with_suffix('')
        module_name = '.'.join(mod_path.parts)
        info['importado_por'] = find_reverse_imports(module_name, all_files)
    
    # 4. Detectar duplicados
    print("  Detectando duplicados...")
    duplicados = detect_duplicates(files_info)
    
    # 5. Clasificar estado preliminar
    for info in files_info:
        path = info['path']
        imported = len(info['importado_por']) > 0
        has_main = info['tiene_main']
        is_test = info['es_test']
        
        if is_test:
            info['estado_preliminar'] = 'test'
        elif has_main and not imported:
            info['estado_preliminar'] = 'script'
        elif not imported and not has_main:
            info['estado_preliminar'] = 'huerfano'
        else:
            info['estado_preliminar'] = 'vivo'
    
    # 6. Preparar resúmenes
    por_categoria = defaultdict(list)
    for info in files_info:
        por_categoria[info['categoria']].append({
            'path': info['path'],
            'kb': info['kb'],
            'lineas': info['lineas'],
            'fecha': info['fecha'],
            'estado': info['estado_preliminar']
        })
    
    huerfanos = [
        {'path': i['path'], 'razon': 'nadie lo importa, no ejecutable, no test'}
        for i in files_info if i['estado_preliminar'] == 'huerfano'
    ]
    
    scripts = [
        {'path': i['path'], 'razon': 'tiene main, nadie lo importa'}
        for i in files_info if i['estado_preliminar'] == 'script'
    ]
    
    # 7. Guardar JSON
    output = {
        'timestamp': datetime.now().isoformat(),
        'total_archivos': len(files_info),
        'por_categoria': {k: v for k, v in por_categoria.items()},
        'huerfanos': huerfanos,
        'scripts': scripts,
        'posibles_duplicados': duplicados,
        'resumen_por_archivo': [
            {
                'path': i['path'],
                'categoria': i['categoria'],
                'kb': i['kb'],
                'lineas': i['lineas'],
                'fecha': i['fecha'],
                'es_test': i['es_test'],
                'es_ejecutable': i['tiene_main'],
                'importado_por': i['importado_por'],
                'importa_a': i['importa_a'],
                'estado_preliminar': i['estado_preliminar']
            }
            for i in files_info
        ]
    }
    
    out_file = ROOT_DIR / 'data' / f'code_inventory_{datetime.now().strftime("%Y%m%d")}.json'
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    
    # 8. Resumen consola
    print("\n" + "=" * 60)
    print("INVENTARIO CÓDIGO PYTHON - RESUMEN")
    print("=" * 60)
    print(f"Total archivos:       {len(files_info)}")
    for cat, items in sorted(por_categoria.items()):
        print(f"  {cat:12s}: {len(items):4d}")
    print(f"\nHuérfanos:            {len(huerfanos)}")
    for h in huerfanos[:20]:
        print(f"  - {h['path']}")
    if len(huerfanos) > 20:
        print(f"  ... y {len(huerfanos)-20} más")
    print(f"\nScripts sueltos:      {len(scripts)}")
    for s in scripts[:10]:
        print(f"  - {s['path']}")
    print(f"\nPosibles duplicados:  {len(duplicados)}")
    for d in duplicados:
        print(f"  - {d['grupo']} ({d['razon']})")
    
    print(f"\n✅ Inventario guardado en: {out_file}")
    return 0

if __name__ == '__main__':
    import re
    import os
    sys.exit(main())