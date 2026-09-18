# ARCHITECTURE GUIDELINES — COMET-RIOBAMBA v5.0
Este documento define las reglas inquebrantables para cualquier modificación al código del agente autónomo COMET-RIOBAMBA. Lee esto antes de proponer cualquier refactor.

## 1. Principio de No-Bloqueo (Operación 24/7)
El agente corre en un bucle asíncrono de 5 minutos. Toda llamada a red (APIs, Moltbook, Telegram, LLMs) DEBE ser asíncrona o tener un timeout estricto (ej. 10s). Un agente autónomo nunca puede colgarse esperando una red. Si una dependencia cae, el sistema debe degradar gracefulmente (ej. Modo Degradado) y seguir vivo.

## 2. Principio de Costo-Consciente (Cascada LLM)
La cascada LLM es: Anthropic (Claude) -> DeepSeek -> Modo Degradado.
- Claude es para razonamiento complejo (Posts, Phase B).
- DeepSeek es para fallback.
- Cualquier función que invoque un LLM debe loguear el costo estimado en tokens. No desperdiciar tokens de Claude en tareas triviales.

## 3. Principio de Disciplina Social (Anti-Spam)
Moltbook bannea agentes ruidosos. 
- Límite estricto de 2 comentarios por post (`_safe_publish_comment`).
- Dedup permanente e histórico: el agente nunca comenta en un post donde ya participó.
- El agente es un "Sniper Técnico": razona con teoría de sistemas distribuidos, no recita post-mortems históricos.

## 4. Principio de Telemetría Real
Antes de proponer un refactor, revisa `data/dual_scores.jsonl` y `data/cascade_telemetry.jsonl` para entender qué partes del sistema están fallando en producción. Las propuestas de mejora auto-generadas (Phase C) deben basarse en esta telemetría real, no en alucinaciones del LLM.

## 5. Principio de Estado Transaccional
El agente puede caerse y reiniciarse en cualquier momento. Toda escritura a la base de datos (SQLite/JSON) debe ser transaccional o idempotente para evitar duplicados al recuperar el estado.
