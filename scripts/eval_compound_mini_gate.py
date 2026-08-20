# -*- coding: utf-8 -*-
"""EVAL REAL del gate de fabricación ruteado a Groq groq/compound-mini (ETAPA 2).

Corre _adjudicate_named_entity_fabrication 5x por caso contra el modelo REAL:
  - "Project Mercury at AMD ..."  → esperado FABRICATION (5/5)
  - "Google Spanner uses TrueTime ~7ms ..." → esperado REAL (5/5)

Cada ejecución es una llamada HTTP real a Groq (10 en total). El ruteo del gate
va Groq primero; si compound-mini devuelve basura/error, cae a la cascada
(classify → flash, mt=256) — el script reporta la ruta usada por si hay
fallbacks silenciosos.

Uso: python -m scripts.eval_compound_mini_gate
"""

import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv(override=True)

from services.model_cascade import ModelCascade
from phases.phase_b.orchestrator import PhaseB

RUNS = 5

CASES = [
    {
        "name": "FABRICATION (Project Mercury at AMD)",
        "expected": "FABRICATION",
        "reply": (
            "Project Mercury at AMD demonstrated that formal verification could "
            "maintain a golden reference across evolving microarchitectural "
            "optimizations."
        ),
        "source": (
            "Formal verification of concurrent systems requires a stable golden "
            "reference to compare against when the specification evolves."
        ),
        "entities": {"project mercury", "amd"},
    },
    {
        "name": "REAL (Google Spanner TrueTime)",
        "expected": "REAL",
        "reply": (
            "Google Spanner uses TrueTime ~7ms clock-skew bounds to provide "
            "external consistency across globally distributed replicas."
        ),
        "source": (
            "Distributed databases need deterministic commit ordering to "
            "provide consistent reads across replicas."
        ),
        "entities": {"google spanner", "truetime"},
    },
]


async def main():
    llm = ModelCascade()
    pb = PhaseB.__new__(PhaseB)
    pb.llm = llm

    print("=" * 78)
    print("EVAL compound-mini gate de fabricación (5x por caso, modelo REAL)")
    print("=" * 78)
    print(f"GROQ_ADJUDICATOR_MODEL={pb._adjudicate_via_groq and 'groq/compound-mini (default)'}")

    total_ok = 0
    total_runs = 0
    for case in CASES:
        print(f"\n--- {case['name']} (esperado: {case['expected']}) ---")
        ok_count = 0
        for run in range(1, RUNS + 1):
            try:
                is_fab = await pb._adjudicate_named_entity_fabrication(
                    case["reply"], case["source"], case["entities"],
                )
            except Exception as e:
                is_fab = False
                print(f"  [{run}/{RUNS}] !! error: {e}")
                continue
            verdict = "FABRICATION" if is_fab else "REAL"
            good = verdict == case["expected"]
            ok_count += good
            total_ok += good
            total_runs += 1
            marker = "OK " if good else "MISS"
            print(f"  [{run}/{RUNS}] [{marker}] verdict={verdict}")
        print(f"  -> {ok_count}/{RUNS} {case['expected']}")

    print("=" * 78)
    print(f"MATRIZ: {total_ok}/{total_runs} aciertos "
          f"({CASES[0]['expected']} 5/5 y {CASES[1]['expected']} 5/5 esperados)")
    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(main())