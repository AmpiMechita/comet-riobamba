# ADR-003: Precedencia de fuentes de tema en Phase A

## Status

Aceptado (2026-09-24). Aprobado por Rafael.

## Context

Phase A selecciona un topic por ciclo desde multiples fuentes:
own_incident, evolution, research agenda, roadmap, topic_matrix,
niche_config.

El codigo contiene dos declaraciones contradictorias:

1. choose_topic (phase_a_content.py L684-692) documenta v5.3:
   los incidentes reales propios (own_incident) comparten ese nivel
   [prioridad 2, maxima junto con watchlist_pairing]: material que
   ningun otro agente puede escribir.

2. execute (phase_a_content.py L1718) corre el bloque de evolution
   PRIMERO, con el comentario 'Topic Evolution: deepen mature claims
   (first priority)'. Si evolution devuelve algo, topic queda seteado
   y choose_topic nunca corre.

El 23/9 se reprodujo P-071: con topic_evolution_state.json teniendo
una serie status=active, el topic de own_incident es reemplazado por
el de evolution. _apply_editorial_filter rechaza el topic de evolution
y hace fallback, pero topic_source ya no empieza con 'own_incident:',
asi que _incident=None, el gate de cifras no dispara, y el post sale
sin error ni trazabilidad del incidente perdido.

## Decision

Orden de precedencia, de mayor a menor:

1. own_incident
2. evolution
3. research agenda (watchlist_pairing comparte prioridad dentro de agenda)
4. roadmap
5. topic_matrix
6. niche_config

Rationale: el material escaso y no reproducible (own_incident) gana
a material derivado e ilimitado (evolution). Retrasar una serie de
evolution un ciclo no consume recursos; perder un incidente si.

## Invariants

- INV1: si existe un incidente en data/incidents.jsonl con used=False,
  el topic del ciclo DEBE ser ese incidente (salvo retry tras fallo
  del gate).
- INV2: topic_source DEBE empezar con 'own_incident:<id>' durante todo
  el ciclo, incluyendo el fallback de _apply_editorial_filter.
- INV3: mark_incident_used(id) se llama SOLO tras publish exitoso.
  Si el gate o la API fallan, el incidente queda used=False.
- INV4: la precedencia se aplica en execute(), no solo en choose_topic.
  Cambiarla en una sola ubicacion es bug.

## Consequences

### Positivas

- Material unico deja de perderse cuando evolution esta activo.
- Coherencia entre documentacion (choose_topic v5.3) y flujo real.
- P-071 cerrado por diseno, no por parche local.

### Negativas / riesgos

- Una serie de evolution puede retrasarse un ciclo si aparece un
  incidente. Aceptable: evolution no se agota.
- Requiere mover la verificacion de own_incident antes del bloque
  evolution en execute() (o condicionar este ultimo).
- Requiere que tests/conftest.py aisle topic_evolution_state.json y
  topic_matrix_state.json para no depender del state real.

## Referencias

- P-045 (corregido), P-071 en docs/PENDING.md
- phases/phase_a_content.py: choose_topic (L654-728), execute (L1717-...)
- services/incident_store.py
- services/topic_evolution.py
- docs/adr/ADR-001-system-invariants.md
- docs/DIRECTRICES.md (reglas 1, 2, 7b, 12b)

---

*Generado 2026-09-23 (P-071). Status Aceptado 2026-09-24.*
