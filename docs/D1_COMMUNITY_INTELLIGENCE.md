# D1_COMMUNITY_INTELLIGENCE

## Introducción
La fase D1 incorpora una capa mínima de inteligencia comunitaria a COMET-RIOBAMBA.
Su propósito es observar respuesta externa, registrar señales útiles y producir métricas operativas simples antes de introducir clasificación avanzada.

## Objetivo
Medir cómo responde la comunidad a las salidas del sistema y convertir esas señales en una entrada utilizable para evaluación y ajuste operacional.

## Alcance
Esta fase no modifica la lógica central de publicación.
Solo añade observabilidad, registro estructurado y resumen diario.

## Datos observados
Fuentes mínimas:
- Reacciones visibles.
- Comentarios visibles.
- Respuestas directas.
- Señales de amplificación básica.
- Marca temporal y origen del evento.

## Esquema de registro
Archivo sugerido:
data/community_interactions.jsonl

Campos mínimos por evento:
- timestamp
- source
- post_id
- event_type
- actor_handle
- raw_text
- sentiment_label
- action_taken
- operator_review

## Métricas primarias
1. Volumen de interacción por ventana temporal.
2. Tasa de respuesta sobre publicaciones emitidas.
3. Proporción de señales positivas, neutrales y negativas.
4. Tiempo de detección hasta registro.
5. Cobertura de eventos correctamente estructurados.

## Protocolo mínimo
1. Registrar cada interacción visible en formato JSONL.
2. Normalizar event_type y source.
3. Etiquetar sentimiento en tres clases: positive, neutral, negative.
4. Registrar si el agente actuó o no sobre esa señal.
5. Emitir un resumen diario con métricas agregadas.

## Criterios de aceptación
- El archivo JSONL se genera sin romper el flujo actual.
- Cada evento contiene los campos mínimos.
- El resumen diario puede calcular las 5 métricas primarias.
- La fase opera aunque no exista clasificación avanzada.

## Limitaciones
- La calidad inicial dependerá de la consistencia del registro manual o semiautomático.
- El sentimiento en tres clases es una aproximación operacional, no una inferencia científica fuerte.
- No se deben extraer conclusiones causales sin datos longitudinales.

## Trabajo futuro
- Añadir trazas por decisión del agente.
- Separar observaciones de inferencias.
- Incorporar evaluación semanal y auditoría de calidad del etiquetado.

## Nota de integridad
Contenido asistido por IA y sujeto a revisión humana antes de uso en producción, documentación oficial o evidencia científica.
