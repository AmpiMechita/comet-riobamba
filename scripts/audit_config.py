#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Config Audit - Analiza behavior_cfg: valores efectivos, fuentes, consumidores.
Solo lectura, no modifica nada.
"""

import ast
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# ─── 1. AST parsing de config/config.py ───
def parse_config_py() -> Dict[str, Dict]:
    """Parsea config/config.py y extrae cada key de behavior_cfg con su expresión."""
    config_path = ROOT_DIR / "config" / "config.py"
    source = config_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    behavior_cfg_entries = {}
    in_behavior_cfg = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "behavior_cfg":
                    in_behavior_cfg = True
                    if isinstance(node.value, ast.Dict):
                        keys = node.value.keys
                        values = node.value.values
                        for k, v in zip(keys, values):
                            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                                behavior_cfg_entries[k.value] = ast.unparse(v) if hasattr(ast, 'unparse') else _ast_to_str(v)
                    break
        elif in_behavior_cfg and isinstance(node, ast.Call):
            # Handle the auto-overlay merge
            pass

    return behavior_cfg_entries


def _ast_to_str(node: ast.AST) -> str:
    """Convierte nodo AST a string aproximado."""
    if isinstance(node, ast.Constant):
        return repr(node.value)
    elif isinstance(node, ast.Call):
        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr
        args = [_ast_to_str(a) for a in node.args]
        kwargs = [f"{kw.arg}={_ast_to_str(kw.value)}" for kw in node.keywords]
        return f"{func_name}({', '.join(args + kwargs)})"
    elif isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        return f"{_ast_to_str(node.value)}.{node.attr}"
    elif isinstance(node, ast.List):
        return f"[{', '.join(_ast_to_str(e) for e in node.elts)}]"
    elif isinstance(node, ast.Dict):
        return "{...}"
    elif isinstance(node, ast.UnaryOp):
        return f"{type(node.op).__name__}{_ast_to_str(node.operand)}"
    return "<expr>"


# ─── 2. Resolver valores efectivos ───
def get_env_vars() -> Dict[str, str]:
    """Lee .env y os.environ combinado."""
    env = dict(os.environ)
    env_path = ROOT_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def resolve_behavior_cfg(ast_entries: Dict[str, str]) -> Dict[str, Any]:
    """Calcula el valor efectivo de cada parámetro."""
    from config.config import behavior_cfg as runtime_cfg
    from config.agent_policy import POLICY

    env = get_env_vars()
    results = {}

    for key, expr_str in ast_entries.items():
        # Valor runtime real
        effective = runtime_cfg.get(key)

        # Detectar fuente
        source = "unknown"
        env_var = None
        default = None

        expr = expr_str.lower()

        if "os.getenv" in expr or "_validate_bounded_int" in expr:
            # Extraer env var name
            import re
            m = re.search(r'(?:os\.getenv|_validate_bounded_int)\(["\']([A-Z_]+)["\']', expr)
            if m:
                env_var = m.group(1)
                if env_var in env:
                    source = "env"
                else:
                    source = "policy"  # cae a default de POLICY
            # Extraer default
            m = re.search(r'(?:_POLICY\.\w+|[\d\.]+)\)', expr)
            if m:
                default = m.group(0).rstrip(')')
        elif "true" in expr or "false" in expr:
            source = "literal"
        elif "int(" in expr or "float(" in expr or "bool(" in expr:
            source = "policy_or_literal"
        else:
            source = "literal"

        # Overlay check
        overlay_path = ROOT_DIR / "data" / "auto_applied_config.json"
        overlay_val = None
        if overlay_path.exists():
            overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
            overlay_val = overlay.get(key)

        # Allowlist check
        from config.auto_appliable import ALLOWLIST
        allowlist_range = ALLOWLIST.get(key)

        results[key] = {
            "valor_efectivo": effective,
            "fuente": source,
            "env_var": env_var,
            "default": default,
            "overlay": overlay_val,
            "allowlist_range": list(allowlist_range) if allowlist_range else None,
            "ast_expr": expr_str,
        }

    return results


# ─── 3. Encontrar consumidores ───
def find_consumers() -> Dict[str, List[Dict]]:
    """Busca referencias a behavior_cfg.keys() en todo el repo."""
    consumers = defaultdict(list)
    search_dirs = [
        ROOT_DIR / "core",
        ROOT_DIR / "phases",
        ROOT_DIR / "services",
        ROOT_DIR / "scripts",
    ]

    # Patrones de acceso
    import re
    get_pattern = re.compile(r'behavior_cfg\.get\(["\'](\w+)["\']')
    bracket_pattern = re.compile(r'behavior_cfg\[["\'](\w+)["\']\]')
    attr_pattern = re.compile(r'behavior_cfg\.(\w+)')

    exclude_dirs = {".venv", "_audit_trash", "backups", "__pycache__", ".git"}

    for search_dir in search_dirs:
        for py_file in search_dir.rglob("*.py"):
            if any(excl in str(py_file) for excl in exclude_dirs):
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            rel_path = py_file.relative_to(ROOT_DIR)

            # .get() calls
            for match in get_pattern.finditer(content):
                key = match.group(1)
                line_num = content[:match.start()].count('\n') + 1
                consumers[key].append({
                    "file": str(rel_path),
                    "line": line_num,
                    "tipo": "get",
                    "contexto": content[max(0, match.start()-50):match.end()+50].replace('\n', ' ')
                })

            # bracket access
            for match in bracket_pattern.finditer(content):
                key = match.group(1)
                line_num = content[:match.start()].count('\n') + 1
                consumers[key].append({
                    "file": str(rel_path),
                    "line": line_num,
                    "tipo": "bracket",
                    "contexto": content[max(0, match.start()-50):match.end()+50].replace('\n', ' ')
                })

            # attribute access (puede ser falso positivo)
            for match in attr_pattern.finditer(content):
                key = match.group(1)
                if key not in {"get", "keys", "values", "items", "update", "pop"}:
                    line_num = content[:match.start()].count('\n') + 1
                    consumers[key].append({
                        "file": str(rel_path),
                        "line": line_num,
                        "tipo": "attr",
                        "contexto": content[max(0, match.start()-50):match.end()+50].replace('\n', ' ')
                    })

    return dict(consumers)


# ─── 4. Detectar duplicados y fósiles ───
def detect_issues(resolved: Dict, consumers: Dict) -> Dict[str, List]:
    """Detecta parámetros duplicados, muertos, sospechosos."""
    issues = {
        "duplicados": [],
        "muertos": [],
        "sospechosos": [],
    }

    # 1. Comparar con behavior_cfg.py (fósil)
    fossil_path = ROOT_DIR / "config" / "behavior_cfg.py"
    if fossil_path.exists():
        fossil_source = fossil_path.read_text(encoding="utf-8")
        # Extraer keys del dict literal
        fossil_tree = ast.parse(fossil_source)
        fossil_keys = set()
        for node in ast.walk(fossil_tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "behavior_cfg":
                        if isinstance(node.value, ast.Dict):
                            for k in node.value.keys:
                                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                                    fossil_keys.add(k.value)

        current_keys = set(resolved.keys())
        for key in fossil_keys:
            if key not in current_keys:
                issues["duplicados"].append({
                    "parametro": key,
                    "tipo": "fossil_only",
                    "detalle": f"Definido en config/behavior_cfg.py pero NO en config/config.py"
                })

    # 2. Parámetros sin consumidores (muertos)
    for key, info in resolved.items():
        if key not in consumers or not consumers[key]:
            issues["muertos"].append({
                "parametro": key,
                "valor": info["valor_efectivo"],
                "fuente": info["fuente"],
            })

    # 3. Parámetros con defaults distintos en POLICY vs config.py
    from config.agent_policy import POLICY
    policy_fields = {f.name: getattr(POLICY, f.name) for f in POLICY.__dataclass_fields__.values()}
    
    for key, info in resolved.items():
        if key in policy_fields:
            policy_val = policy_fields[key]
            effective = info["valor_efectivo"]
            if policy_val != effective:
                issues["sospechosos"].append({
                    "parametro": key,
                    "policy_default": policy_val,
                    "config_effective": effective,
                    "fuente": info["fuente"],
                    "detalle": "POLICY default difiere del valor efectivo en behavior_cfg"
                })

    # 4. Parámetros en allowlist pero sin overlay
    from config.auto_appliable import ALLOWLIST
    for key in ALLOWLIST:
        if key not in resolved:
            issues["sospechosos"].append({
                "parametro": key,
                "tipo": "allowlist_not_in_behavior_cfg",
                "detalle": f"En allowlist de auto_appliable.py pero no existe en behavior_cfg"
            })

    return issues


# ─── Main ───
def main() -> int:
    print("🔍 Iniciando auditoría de behavior_cfg...")

    # Parsear AST
    print("  Parsing config/config.py...")
    ast_entries = parse_config_py()
    print(f"    {len(ast_entries)} parámetros encontrados en AST")

    # Resolver valores
    print("  Resolviendo valores efectivos...")
    resolved = resolve_behavior_cfg(ast_entries)

    # Consumidores
    print("  Buscando consumidores...")
    consumers = find_consumers()
    print(f"    {len(consumers)} parámetros con consumidores")

    # Issues
    print("  Detectando issues...")
    issues = detect_issues(resolved, consumers)

    # Construir reporte
    report = {
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "parametros": {},
        "duplicados": issues["duplicados"],
        "muertos": issues["muertos"],
        "sospechosos": issues["sospechosos"],
    }

    for key, info in resolved.items():
        report["parametros"][key] = {
            **info,
            "consumidores": consumers.get(key, []),
        }

    # Guardar
    out_file = ROOT_DIR / "data" / f"config_audit_{__import__('datetime').datetime.now().strftime('%Y%m%d')}.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n✅ Reporte guardado en: {out_file}")

    # Resumen consola
    total = len(resolved)
    with_consumers = sum(1 for k in resolved if k in consumers and consumers[k])
    dead = len(issues["muertos"])
    dupes = len(issues["duplicados"])
    suspicious = len(issues["sospechosos"])

    print("\n" + "=" * 60)
    print("RESUMEN AUDITORÍA behavior_cfg")
    print("=" * 60)
    print(f"Total parámetros:       {total}")
    print(f"Con consumidores:       {with_consumers}")
    print(f"Sin consumidores (muertos): {dead}")
    print(f"Duplicados (fósiles):   {dupes}")
    print(f"Sospechosos:            {suspicious}")

    print("\nParámetros sin consumidores:")
    for m in issues["muertos"][:15]:
        print(f"  - {m['parametro']} = {m['valor']} (fuente: {m['fuente']})")

    return 0


if __name__ == "__main__":
    sys.exit(main())