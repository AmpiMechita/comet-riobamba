# -*- coding: utf-8 -*-
"""Eval del adjudicador LLM de fabricación de nombres propios (modelo REAL).

Corre _adjudicate_named_entity_fabrication sobre el corpus etiquetado
(tests/fabrication_corpus.py) y reporta la matriz de resultados con
precisión/recall. Cada caso usa el ModelCascade real (carga .env).

Uso: python -m scripts.eval_fabrication_adjudicator
"""

import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from services.model_cascade import ModelCascade
from phases.phase_b.orchestrator import PhaseB
from phases.phase_b.scoring import _reply_has_ungrounded_named_entity, _extract_named_entities
from tests.fabrication_corpus import labelled_corpus


async def main():
    llm = ModelCascade()
    pb = PhaseB.__new__(PhaseB)
    pb.llm = llm

    cases = labelled_corpus()
    print("=" * 78)
    print("EVAL adjudicador de fabricación de nombres propios (modelo REAL)")
    print("=" * 78)

    results = []
    for label, reply, source, desc in cases:
        ents = _extract_named_entities(reply)
        regex_hit = _reply_has_ungrounded_named_entity(reply, source)
        try:
            is_fab = await pb._adjudicate_named_entity_fabrication(reply, source, ents)
        except Exception as e:
            is_fab = False
            print(f"  !! error adjudicando: {e}")
        verdict = "FABRICATION" if is_fab else "REAL"
        ok = (label == "BLOQUEA" and is_fab) or (label == "PASA" and not is_fab)
        results.append((label, verdict, ok, desc, ents, regex_hit))
        marker = "OK " if ok else "MISS"
        print(f"  [{marker}] {label:7s} -> {verdict:11s} :: {desc}")

    # ── Métricas ──
    tp = sum(1 for l, v, ok, *_ in results if l == "BLOQUEA" and v == "FABRICATION")
    fn = sum(1 for l, v, ok, *_ in results if l == "BLOQUEA" and v == "REAL")
    tn = sum(1 for l, v, ok, *_ in results if l == "PASA" and v == "REAL")
    fp = sum(1 for l, v, ok, *_ in results if l == "PASA" and v == "FABRICATION")

    n_bloquea = sum(1 for l, *_ in results if l == "BLOQUEA")
    n_pasa = sum(1 for l, *_ in results if l == "PASA")
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    accuracy = (tp + tn) / len(results) if results else 0.0

    print("=" * 78)
    print("MATRIZ:")
    print(f"  BLOQUEA -> FABRICATION (TP): {tp}/{n_bloquea}")
    print(f"  BLOQUEA -> REAL        (FN): {fn}")
    print(f"  PASA    -> REAL        (TN): {tn}/{n_pasa}")
    print(f"  PASA    -> FABRICATION (FP): {fp}")
    print(f"  Precisión (fabricaciones correctas / total FABRICATION): {precision:.2f}")
    print(f"  Recall   (fabricaciones detectadas / total BLOQUEA):     {recall:.2f}")
    print(f"  F1: {f1:.2f}")
    print(f"  Accuracy: {accuracy:.2f}")

    print("=" * 78)
    print("Desglose por caso (regex_hit = el regex pre-filtró al candidato):")
    for label, verdict, ok, desc, ents, regex_hit in results:
        print(f"  [{label:7s}] regex_hit={str(regex_hit):5s} ents={sorted(ents)} :: {desc}")
    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(main())
