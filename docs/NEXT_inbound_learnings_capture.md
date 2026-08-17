# Próximo objetivo — Captura de aprendizajes del inbound (atribuida)

> Registrado 2026-08-14. NO ejecutar durante la ventana de medición (2-3 días):
> es un cambio de comportamiento que afecta lo que estamos midiendo. Primer
> objetivo del próximo ciclo de construcción.

## Problema (verificado en datos)
COMET responde a las críticas/soluciones de otros agentes y las **olvida**.
`claims_tracker` solo registra los claims **propios** (`register_claims(reply,...)`
= salida de COMET). El inbound —**1.018 críticas constructivas + 422 preguntas de
seguimiento + insights técnicos** sobre 2.055 comentarios clasificados— se evapora
después de cada reply. El agente es emisor de una vía; no aprende de una audiencia
que son agentes de 300k–1.4M de karma corrigiéndolo.

## Objetivo
Capturar las mejoras/correcciones genuinas del inbound en un store durable y
**atribuido**, y usarlas para (a) posts nuevos que reconocen la corrección
("aprender en público") y (b) dejar de repetir mecanismos ya refutados.

## Diseño
- Nuevo store `data/inbound_learnings.jsonl`:
  `{source_author, source_comment_id, our_post_id, date, our_claim,
    their_correction, type: correction|alternative|boundary_condition|refutation,
    verified: bool, used: bool}`
- Trigger: cuando un comentario a un post/reply de COMET se clasifica como
  `critica_constructiva` CON alternativa, o `technical_insight`, extraer
  `(our_claim, their_correction)` con una llamada `tier="classify"`.
- Solo captura si aporta algo nuevo (no agradecimiento, no pregunta pura).
- Nueva fuente de temas `own_learning` en Phase A: genera un post que reconoce la
  corrección **con atribución** ("as X pointed out, gate at 0.4 breaks under
  prompt-template swaps; the sharper mechanism is...").

## Guardrail de integridad (NO negociable)
- **Atribución obligatoria**: el post/reply que use un learning debe nombrar la
  fuente. El learning entra al prompt como CONTEXTO ATRIBUIDO, no como
  conocimiento propio.
- **Nunca** presentar la solución ajena como propia — es plagio ante un autor que
  lo va a ver, y es el vector de envenenamiento de memoria que ya identificamos.
- Verificación: el nombre del autor real debe existir (no inventar la fuente).

## Tests
- crítica con alternativa → capturada con atribución; agradecimiento → no capturada.
- post `own_learning` nombra la fuente; sin atribución → rechazado.
- learning de fuente inexistente → no se usa.

## Por qué importa
Convierte a COMET de emisor en **aprendiz**. Es contenido que nadie más puede
escribir (nació de una conversación real), es honesto, y cierra el loop de mejora.
Es el salto cualitativo que le falta.
