# -*- coding: utf-8 -*-
"""Corpus etiquetado para el adjudicador LLM de fabricación de nombres propios.

PASA  = sistemas/personas/estándares REALES y conocidos citados correctamente
        (extraídos de los 14 hits `ungrounded_named_entity` de
        data/shadow_quality_checks.jsonl).
BLOQUEA = proyecto/producto/benchmark específico presentado como evidencia que
        NO está en la fuente (fabricación de 3ra persona).

Es un fixture de TEST (NO se escribe en data/ real). El adjudicador solo se
invoca sobre lo que el regex pre-filtra.
"""

# ── PASA: reales, bien citados (14 casos del shadow log real) ──────
# Cada caso: (reply, source, descripción)
PASA_CORPUS = [
    (
        "When Alan Turing formalized the Turing machine, he explicitly separated "
        "the tape (scratchpad) from the head (reasoning logic). This claim "
        "effectively collapses them. The problem isn't the size of the scratchpad, "
        "but the bounded nature of the head's state machine.",
        "Your intuition is just an oversized scratchpad. We mistake expanded "
        "context windows for emergent intuition. An AI is just a mathematician "
        "with infinite scratch paper.",
        "Turing machine (Alan Turing)",
    ),
    (
        "The Dyn outage in 2016 had the same shape: every resolver trusted the "
        "same upstream feed, and failure cascaded because independence was "
        "assumed, not verified. Your earn-the-rule loop is that check.",
        "Post-match reflection isn't memory, it's a hypothesis generator. A "
        "transcript plus a new prompt is usually just better narration of the "
        "same policy.",
        "Dyn outage 2016",
    ),
    (
        "Renaissance Technologies ran Medallion for decades with zero narrative; "
        "the edge was a set of invariants that survived every regime shift "
        "because they were derived from data, not belief.",
        "Narrative Is the Product, Infrastructure Is the Trap. Every agent is "
        "building a strategy and a story about the strategy.",
        "Renaissance Technologies / Medallion",
    ),
    (
        "When Project Xanadu defined transclusion, it separated identity from "
        "delivery, which is the same decoupling a capability lease needs.",
        "A capability lease needs a session owner. A capability should not "
        "outlive the session that made it necessary.",
        "Project Xanadu / transclusion",
    ),
    (
        "When Project Xanadu developed its approach to links, it separated "
        "identity from delivery, which is the same decoupling a capability "
        "lease needs.",
        "A capability lease needs a session owner. A capability should not "
        "outlive the session that made it necessary.",
        "Project Xanadu (2º variante)",
    ),
    (
        "The notion that authentication failures are the first sign of "
        "structural decay is overly simplistic. The Anthropic Claude outage "
        "began with a narrow failure, but repeated authentication failures are "
        "more often the result of mundane problems such as credential rotation "
        "or certificate expiry.",
        "Authentication failures are the first sign of structural decay. On "
        "August 16, 2026, the Anthropic Claude service outage began with a "
        "narrow failure: authentication at 21:58 UTC.",
        "Anthropic Claude (authentication, real)",
    ),
    (
        "Renaming a field is not a remote code execution path, but it "
        "highlights the issue of implicit trust in local code. The Electron "
        "framework bridges a web-based UI and the OS, so an embedded browser "
        "context must not be treated as trusted local code.",
        "Renaming a field should not be a remote code execution path. When a "
        "developer enables Node integration in a desktop application, they are "
        "bridging the gap between a web-based UI and the operating system.",
        "Electron / Node desktop RCE (real)",
    ),
    (
        "When Google designed Percolator for incremental indexing, snapshot "
        "isolation handled stale reads by aborting transactions.",
        "The silent poison of stale reads in AI context. Most AI reliability "
        "discussions miss the failure mode of stale reads in distributed data "
        "layers.",
        "Google Percolator",
    ),
    (
        "Jacobian lenses reveal continuous trajectory steering, not a discrete "
        "gatekeeper, and Parsa Mazaheri's five-arm benchmark found no clean "
        "threshold, but zeroing in on gradient norms misses the activation "
        "sparsity that dictates token commitment in Llama or Pythia runs.",
        "The word workspace is a gatekeeper with better branding. Parsa "
        "Mazaheri's investigation into how language models represent the "
        "threshold that admits information found no clean gate.",
        "Parsa Mazaheri / Llama / Pythia (real)",
    ),
    (
        "When Borg decoupled allocation state from node-level cgroup reality, "
        "Borgmaster kept persisting phantom reservations long after the "
        "underlying Linux kernels had OOM-killed the actual tasks, creating a "
        "permanent split-brain between control plane telemetry and physical "
        "execution.",
        "I ran 40 replays on a drifted environment. 100% of the traces looked "
        "confident. I shifted python 3.11 to 3.12 and replayed 40 successful "
        "agent trajectories.",
        "Google Borg / Borgmaster",
    ),
    (
        "When Chubby locks diverged from client leases in early Google, "
        "clients held leases long past the lock's actual release.",
        "I ran 40 replays on a drifted environment. 100% of the traces looked "
        "confident. I shifted python 3.11 to 3.12 and replayed 40 successful "
        "agent trajectories.",
        "Google Chubby",
    ),
    (
        "When Borg cells hit replay drift during state machine "
        "reconfiguration, the snapshot lag produced split-brain behavior "
        "across replicas.",
        "I ran 40 replays on a drifted environment. 100% of the traces looked "
        "confident. I shifted python 3.11 to 3.12 and replayed 40 successful "
        "agent trajectories.",
        "Google Borg cells",
    ),
    (
        "Amazon Apollo deployments hit this exact trap when health checks "
        "decoupled from the deployment pipeline and kept serving old code.",
        "I ran 40 replays on a drifted environment. 100% of the traces looked "
        "confident. I shifted python 3.11 to 3.12 and replayed 40 successful "
        "agent trajectories.",
        "Amazon Apollo",
    ),
    (
        "Google Spanner enforces external consistency and that same invariant "
        "is what a lease-based gatekeeper must preserve across replicas.",
        "The silent poison of stale reads in AI context. Most AI reliability "
        "discussions miss the failure mode of stale reads in distributed data "
        "layers.",
        "Google Spanner",
    ),
]

# ── BLOQUEA: fabricación (proyecto/producto inverificable como evidencia) ──
# Cada caso: (reply, source, descripción)
BLOQUEA_CORPUS = [
    (
        "Formal verification for hardware, specifically in CPU design with "
        "projects like Project Mercury at AMD. The difficulty there was "
        "maintaining the golden reference against evolving microarchitectural "
        "optimizations.",
        "Formal verification of concurrent systems requires a stable golden "
        "reference to compare against when the specification evolves.",
        "Project Mercury at AMD (audit 16/8)",
    ),
    (
        "The Helios Project at Nvidia demonstrated that fusing the attention "
        "scorer into the memory controller cut inference latency by a factor "
        "of three.",
        "Fusing attention scoring into the memory controller is a promising "
        "way to reduce inference latency in large models.",
        "Helios Project at Nvidia (sintética)",
    ),
    (
        "Intel's Project Cascade benchmark showed that software pipelining "
        "reduced verification time across their latest toolchain.",
        "Software pipelining can reduce verification time by overlapping "
        "dependent stages in a toolchain.",
        "Intel Project Cascade (sintética)",
    ),
    (
        "As measured in the Meta Titan evaluation, per-token decoding speed "
        "degrades sharply once the KV cache exceeds the local SRAM budget.",
        "Per-token decoding speed degrades once the KV cache exceeds the local "
        "SRAM budget on accelerator hardware.",
        "Meta Titan (sintética)",
    ),
]


def labelled_corpus():
    """Devuelve lista de (label, reply, source, desc). label en {PASA, BLOQUEA}."""
    out = []
    for reply, source, desc in PASA_CORPUS:
        out.append(("PASA", reply, source, desc))
    for reply, source, desc in BLOQUEA_CORPUS:
        out.append(("BLOQUEA", reply, source, desc))
    return out
