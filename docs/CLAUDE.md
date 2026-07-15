# COMET-RIOBAMBA – CLAUDE.md

## 1. Contexto del proyecto

- COMET-RIOBAMBA es un agente autónomo orientado a tareas de agricultura y automatización sobre la plataforma Moltbook.
- El objetivo principal es orquestar LLMs (locales vía Ollama y remotos) para ejecutar workflows de análisis, generación de contenido y automatización de tareas.

## 2. Stack técnico

- Lenguajes: Python 3.x, PowerShell para scripts de automatización.
- LLMs: modelos locales vía Ollama (qwen2.5-coder:3b, llama3.2:1b, modelos :cloud), otros endpoints remotos según configuración.
- Integraciones: API de Moltbook, servicios HTTP/REST, posible uso de colas o schedulers externos.
- Entorno de desarrollo principal: Windows + PowerShell.

## 3. Estructura del repositorio

La estructura real del repo es plana (no hay prefijo src/). Las partes relevantes para el agente son:

- agent.py  
  - Núcleo del agente COMET-RIOBAMBA. Orquesta las fases, llama a servicios y coordina la interacción con LLMs y Moltbook.
  - Los múltiples aagent.py.*.bak son backups históricos; no deben tocarse salvo que se indique explícitamente.

- phases/  
  - Implementa el pipeline por fases del agente.
  - phase_a_content.py – Fase A: generación y preparación de contenido principal.
  - phase_b_replies.py, phase_b_responses.py – Fase B: gestión de respuestas y réplicas.
  - phase_c_analytics.py, phase_c_engagement.py – Fase C: análisis, métricas y lógica de engagement.
  - El resto de archivos .bak y .backup son versiones anteriores o experimentos; servirán como referencia pero no deben reactivarse sin revisión.

- personality/  
  - persona.py – Definición de la personalidad base del agente (tono, estilo, objetivos).
  - integration.py, personality_integration.py – Cómo se inyecta la personalidad en el flujo del agente y en las llamadas a modelos.

- prompts/  
  - prompt_templates.py – Plantillas de prompts para las distintas fases y servicios del agente.

- services/  
  - model_cascade.py – Orquestación de modelos (cascada local vs cloud, fallbacks y reintentos).
  - moltbook_api_client.py – Cliente HTTP hacia la API de Moltbook.
  - gent_profiler.py, uto_optimizer.py, challenge_solver.py, content_validator.py,
    global_circuit.py, metrics.py, outbox_manager.py, persistence.py, platform_awareness.py,
    post_history_guard.py, self_eval.py, semantic_dedup.py, social_metrics.py,
    submolt_discovery.py, 	elegram_client.py, 	opic_memory.py – Servicios de soporte alrededor del agente
    (optimización, guardrails, almacenamiento, métricas, integraciones externas, memoria temática, etc.).
  - Los sufijos .bak, .backup, .working, etc. representan iteraciones previas que no deben usarse directamente
    salvo que se indique como parte de una migración específica.

- utils/  
  - logging_config.py – Configuración central de logging.
  - 
esilience.py – Utilidades de resiliencia (reintentos, timeouts, circuit breakers).
  - content_validators.py, 	ext_formatters.py – Validación y formateo de contenido.
  - __pycache__/ – Artifacts generados; se pueden ignorar.

- Otras carpetas relevantes:  
  - config/ – Configuración (archivos de entorno, modelos, parámetros).
  - 	ests/ – Pruebas automatizadas.
  - scripts/ – Scripts de automatización (PowerShell y/o Python).
  - dashboard/, data/, docs/, 	ools/, logs/, _archive/, _lab/, _quarantine/, deploy/ – Soporte,
    experimentos, despliegue y artefactos; no forman parte del core de agentes pero pueden ser usados
    como contexto adicional cuando se indique.

## 4. Convenciones de código

- Python:
  - Estilo cercano a PEP8; usa tipos donde aporten claridad.
  - Prefiere funciones puras y componentes pequeños sobre objetos gigantes.
- PowerShell:
  - Cmdlets verbo-nombre (Get-Status, Start-Workflow).
  - Priorizar legibilidad sobre trucos de una sola línea.
- Logs:
  - Usa las utilidades de logging centralizadas en utils/logging_config.py (o equivalente) en vez de print.
- Configuración:
  - No codificar credenciales ni rutas sensibles en el código.
  - Toda configuración debe salir de config/ o variables de entorno.

## 5. Reglas importantes

- **NUNCA**:
  - Confirmar commits, publicar claves o modificar archivos de configuración sensibles con secretos.
  - Eliminar archivos fuera del repo sin permiso explícito.
- Antes de cambios grandes:
  - Proponer un plan corto y esperar confirmación.
  - Explicar qué módulos tocarás y por qué.

## 6. Cómo ejecutar y probar

- Ejecutar agente principal:
  - python -m agent o el entrypoint equivalente desde la raíz del proyecto (ajustar según script real).
- Pruebas:
  - pytest dentro de la carpeta raíz o 	ests/.

Siempre que hagas cambios significativos:
1. Ejecuta las pruebas relevantes.
2. Indica qué comandos corriste y su salida.

## 7. Trabajo con LLMs y modelos

- Desarrollo local:
  - Modelos ligeros recomendados: llama3.2:1b, qwen2.5:1.5b para tareas generales.
  - Modelos especializados en código como qwen2.5-coder:3b solo cuando el hardware lo permita.
- Modelos en la nube:
  - Modelos :cloud (por ejemplo minimax-m3:cloud, glm-5:cloud) pueden usarse vía Ollama para tareas pesadas.
- Si una tarea requiere un modelo distinto:
  - Explica por qué.
  - Mantén coherente la configuración en config/ con el entorno (local vs cloud).

## 8. Cómo quiero que trabajes en este repo

- Prioriza:
  - Refactors claros, bien justificados y con cambios mínimos pero potentes.
  - Mejoras en manejo de errores, logging y resiliencia de agentes.
  - Limpieza de código duplicado y simplificación de flujos complejos.
- Para tareas grandes:
  - Resume primero el objetivo.
  - Propón un plan en pasos.
  - Ejecuta el plan verificando cada paso con pruebas o ejemplos.

## 9. Cosas a evitar

- No cambies el comportamiento de alto nivel de COMET-RIOBAMBA (interfaces externas, contratos con Moltbook) sin confirmación.
- No introduzcas dependencias pesadas nuevas sin justificar impacto en despliegue y recursos.
- No reescribas módulos completos si basta con una mejora incremental localizada.
