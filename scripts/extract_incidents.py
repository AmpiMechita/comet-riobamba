# -*- coding: utf-8 -*-
"""
Bootstrap del store de incidentes reales (data/incidents.jsonl).

Propone entradas a partir de `git log`: los mensajes 'fix:'/'feat:' de este
repo ya narran sintoma -> causa -> fix con numeros reales. El resultado es
UN PUNTO DE PARTIDA: la curacion (quedarse con los 8-12 mejores, quitar
rutas internas/nombres de archivo/claves, pasar a ingles) es humana.

Uso:
  python -m scripts.extract_incidents --commits 25
  python -m scripts.extract_incidents --commits 25 --output data/incidents_proposed.jsonl

Sin --output escribe las propuestas a stdout (una por linea) y el conteo a stderr.
"""

import argparse
import json
import re
import subprocess
import sys
from typing import List, Optional

GIT_FORMAT = "%h|%ad|%s"
PREFIX_RE = re.compile(r"^(fix|feat|docs|chore|test|refactor)\s*:\s*", re.IGNORECASE)
# Separador narrativo de este repo: "sintoma — causa — fix"
CLAUSE_RE = re.compile(r"\s*(?:—|–|\u2014|-)\s+")
# Numeros con unidades/relaciones tipicas: 410/410, 10->30, 85 min, ~218, 300→400
NUMBER_RE = re.compile(r"\d+(?:[.,/:xX+~\-→]*\d+)*%?")


def run_git_log(commits: int) -> List[tuple]:
    out = subprocess.run(
        ["git", "log", f"-{commits}", f"--format={GIT_FORMAT}", "--date=short"],
        capture_output=True, text=True, check=True,
    ).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            rows.append((parts[0].strip(), parts[1].strip(), parts[2].strip()))
    return rows


def extract_numbers(text: str) -> List[str]:
    seen, out = set(), []
    for m in NUMBER_RE.findall(text):
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def build_proposal(short_hash: str, date: str, subject: str) -> Optional[dict]:
    if not subject.startswith(("fix:", "feat:")):
        return None
    cleaned = PREFIX_RE.sub("", subject).strip()
    clauses = [c.strip() for c in CLAUSE_RE.split(cleaned) if c.strip()]
    symptom = clauses[0] if clauses else cleaned
    root_cause = clauses[1] if len(clauses) > 1 else ""
    fix = " ".join(clauses[2:]) if len(clauses) > 2 else ""
    return {
        "id": f"inc-{short_hash}",
        "date": date,
        "title": symptom[:90],
        "symptom": symptom,
        "root_cause": root_cause,
        "fix": fix,
        "real_numbers": "; ".join(extract_numbers(subject)),
        "used": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commits", type=int, default=25, help="ultimos N commits a escanear")
    parser.add_argument("--output", default=None, help="archivo de salida JSONL (stdout si se omite)")
    args = parser.parse_args()

    proposals = []
    for short_hash, date, subject in run_git_log(args.commits):
        proposal = build_proposal(short_hash, date, subject)
        if proposal:
            proposals.append(proposal)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            for p in proposals:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
    else:
        for p in proposals:
            print(json.dumps(p, ensure_ascii=False))
    print(f"# {len(proposals)} propuesta(s) desde los ultimos {args.commits} commits (curacion manual pendiente)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
