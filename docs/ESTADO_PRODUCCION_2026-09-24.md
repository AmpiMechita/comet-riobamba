# ESTADO DE PRODUCCION — COMET-RIOBAMBA (Moltbook)
**Fecha:** 2026-09-24. **Sesion:** P-077. **Fuentes:** data/*.jsonl (solo lectura). **Ventana principal:** ultimos 14 dias (2026-09-11 .. 2026-09-24).

## Resumen ejecutivo
- **Volumen:** 32 posts en 10 dias con actividad; avg score 5.62, avg comments 5.78, max score 16.
- **Calidad:** adjudicator con 34.6% FABRICATION y 24.7% fail-open; 227 rechazos concentrados en topic_source=roadmap (182, casi todos validation_failed).
- **Errores/coste:** cascade success 99.9%; 14.707 llamadas 14d; coste $2.05 (~$4.4/mes); sin model_error desde 2026-09-10.
- **Valor/ROI:** value_log 108/108=aporte_util (clasificacion uniforme, sesgo probable); karma_roi_tracker 0/212 con upvote; dual_scores engagement_avg=0.000.
- **Senal fuerte:** el lazo de feedback de engagement esta muerto/instrumentado en falso.

## 1. Volumen y engagement
- Fuente: data/topic_performance.jsonl (639 filas; 32 en 14d).
- score: avg 5.62, max 16. comment_count: avg 5.78, max 39.
- Top temas: failover/cascade (16), hallucination detection (14), observability (11), memory mgmt (10), context window (9).
- Anomalia a reconciliar: 32 posts/10 dias (~3.2/dia) vs cap vigente 1 weekday / 2 weekend. El campo published_at de topic_performance puede no ser fecha real de publicacion. P-078 (a registrar en sesion posterior).

## 2. Calidad editorial
- rejected_posts 14d: 227. Razones: validation_failed 205, below_min_quality_score 22.
- topic_source de los rechazados: roadmap 182, dedup_fallback 19, fallback_filter 15, watchlist_pairing 8, forced_fallback 3.
- adjudicator_verdicts 14d: 1886 -> REAL 768, FABRICATION 653 (34.6%), fail-open 465 (24.7%).
- shadow_quality_checks 14d: 13 -> ungrounded_named_entity 6, ungrounded_numeric_specificity 4, weak_source_anchor 2, mixto 1.
- dual_scores 14d: 179 (phase b 178, a 1); eng_avg 0.000, rv_avg 0.489, composite_avg 0.343. Tipos: clarification 126, framework_proposal 26, empirical_finding 22.

## 3. Errores, tiers y coste
- cascade_telemetry 14d: 14.707 llamadas; success 14.698 (99.9%); 9 fallos tipo network.
- Provider: tier_flash 14.478 (98.4%), tier_pro 224, tier_fallback 5.
- Tier: flash 13.945, classify 538, quality 148, pro 58, premium 15, fallback 2, default 1.
- Coste total 14d: $2.0496. Tokens in 16.786.736 / out 1.681.382. Latencia avg 1.951 ms, p95 3.113 ms, max 36.004 ms.
- generation_attempts: 2914 filas; model_error 1099 (37.7%), todos en 2026-08-28..2026-09-10 (661 el 09-01, 198 el 09-02, 197 el 09-10). 0 en 14d.
- topic_source historico: dedup_fallback 1025 + forced_fallback 1003 = 69.6% (dominancia fallback).
- run_id presente en 4/2914 (solo desde 2026-09-21; fix P-102 empieza a poblar 21/9).
- Nota P-065: error_type/tier aun 0/2914 porque no ha ocurrido model_error desde el fix; se pobla al primer fallo.

## 4. Valor / ROI
- value_log 14d: 108 filas; clasificacion_valor = aporte_util 100%. Senales: critica_constructiva 40, pregunta_seguimiento 5, confirmacion_solucion 1, agradecimiento_explicito 1.
- karma_roi_tracker: 223 filas; 212 reales; 0 con upvote/karma>0; coste agregado $0.04116.
- karma_trend.jsonl: 3 filas, ultima 2026-08-19. Congelado.
- social_metrics.jsonl: 11 filas, ultima 2026-05-22. Congelado.
- comment_events.jsonl: 6499 filas, ultima 2026-05-27. Congelado.

## 5. Hallazgos accionables (registrados en PENDING)
- P-073: monitoring/daily-*.md detenidos desde 2026-09-05.
- P-074: lazo feedback engagement muerto (karma_roi 0/212, dual engagement=0, karma_trend 19/8).
- P-075: fallback domina topic_source (69.6% historico).
- P-076: run_id historico ausente en generation_attempts (solo 4/2914, desde 21/9).
- P-077: value_log clasifica 100% aporte_util (posible sesgo clasificador).

## 6. Limitaciones
- Ventana 14d elegida por tamano/relevancia; series historicas existen pero mezclan incidentes sep 1/2/10.
- Algunas fuentes mezclan fixtures de test (karma_roi) o snapshots de la plataforma (moltbook_full_archive). Se excluyeron del agregado principal.
- El conteo de posts 14d requiere reconciliacion con caps vigentes (P-078 futuro).
