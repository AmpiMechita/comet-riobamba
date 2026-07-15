# EVAL_PROTOCOL

## Introducción
Este protocolo define la evaluación mínima operativa de la fase D1 de COMET-RIOBAMBA.
Se aplica sobre el archivo data/community_interactions.jsonl y sus resúmenes diarios.

## Objetivo
Medir estabilidad básica, calidad del registro y señales iniciales de respuesta comunitaria.

## Datos observados
Fuente primaria:
- data/community_interactions.jsonl

Fuente derivada:
- logs/D1_DAILY_SUMMARY.md

## Métricas
1. Total de eventos por día.
2. Conteo de sentimiento positivo.
3. Conteo de sentimiento neutral.
4. Conteo de sentimiento negativo.
5. Distribución por tipo de evento.

## Criterios mínimos de validez
- Todo evento debe incluir: 	imestamp, source, post_id, event_type, ctor_handle, aw_text, sentiment_label, ction_taken, operator_review.
- El resumen diario debe poder reconstruirse sin error desde el JSONL.
- No se permiten líneas vacías con datos corruptos entre eventos.

## Procedimiento de evaluación
1. Registrar interacciones visibles en community_interactions.jsonl.
2. Ejecutar scripts/build_d1_daily_summary.ps1.
3. Verificar coherencia entre JSONL y resumen diario.
4. Marcar anomalías manualmente en operator_review.
5. Consolidar revisión humana al cierre de cada jornada.

## Regla de interpretación
- Menos de 10 eventos no permite inferencias fuertes.
- En esta fase solo se aceptan conclusiones descriptivas.
- No se deben afirmar tendencias causales sin series temporales más largas.

## Fallos que invalidan la corrida
- JSON malformado.
- Campos mínimos ausentes.
- Resumen diario inconsistente con el JSONL.
- Etiquetas de sentimiento fuera del conjunto permitido.

## Trabajo futuro
La clasificación más sofisticada solo se habilita después de siete días consecutivos con registro válido y resumen diario consistente.

## Nota de integridad
Contenido asistido por IA y sujeto a revisión humana antes de uso en producción, documentación oficial o evidencia científica.
