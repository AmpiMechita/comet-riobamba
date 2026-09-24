Nuevo chat. Retomo proyecto COMET-RIOBAMBA. Lee esto completo antes de responder.

═══════════════════════════════════════════════════════════════
CÓMO FUNCIONA ESTE CHAT (LEER PRIMERO)
═══════════════════════════════════════════════════════════════
Yo (Rafael) ejecuto los comandos de PowerShell. Tú (modelo) propones qué ejecutar. NO tienes acceso a: C:\comet-riobamba-v31\, el servicio CometRiobamba, la terminal, ni Internet (sin herramientas). Solo ves lo que yo te pego.

FLUJO DE TRABAJO:
1. Tú propones UN bloque de comandos (máximo 30 líneas).
2. Yo los ejecuto en mi PowerShell.
3. Yo te pego la salida completa.
4. Tú analizas y propones el siguiente bloque.
5. Repetimos hasta completar el objetivo.

NUNCA digas "voy a leer el archivo X". Pídeme que ejecute un comando y me pase la salida. Toda solicitud de contenido se hace CON COMANDO EXPLÍCITO.

═══════════════════════════════════════════════════════════════
CONTEXTO DEL OPERADOR
═══════════════════════════════════════════════════════════════
Soy Rafael. Ecuador. Sin formación en programación. Familia a cargo. Presupuesto mensual APIs/infra: $10-40. 100 h/semana disponibles. Ingreso mínimo necesario: $1,000/mes. Narrativa: soberanía tecnológica desde la periferia.
Proyecto: agente autónomo COMET-RIOBAMBA en Moltbook.
Ruta: C:\comet-riobamba-v31Rama git: feature/optimize-agent-config
Servicio: CometRiobamba (NSSM, LocalSystem)
VERIFICA EL HEAD actual con: git log --oneline -1

═══════════════════════════════════════════════════════════════
PROTOCOLO DE LECTURA POR BLOQUES
═══════════════════════════════════════════════════════════════
PASO 1 — Verificación de existencia y tamaño:
Ejecuta esto y pégame la salida:
  cd C:\comet-riobamba-v31
  $h = (Get-ChildItem .\docs\HANDOFF_*.md | Sort-Object LastWriteTime -Descending)[0]
  $h.FullName
  Get-Item $h.FullName, .\docs\PENDING.md, .\docs\MAPA_TECNICO.md | Select-Object Name, Length
  (Get-Content $h.FullName).Count
  (Get-Content .\docs\PENDING.md).Count
  (Get-Content .\docs\MAPA_TECNICO.md).Count

PASO 2 — Leer HANDOFF completo: Get-Content $h.FullName
PASO 3 — Leer PENDING completo: Get-Content .\docs\PENDING.md
PASO 4 — Leer MAPA_TECNICO completo: Get-Content .\docs\MAPA_TECNICO.md
PASO 5 — Estado del servicio y git:
  Get-Service CometRiobamba | Select-Object Name, Status
  git status --short
  git log --oneline -3
  Get-Content .\logsgent.log -Tail 5

═══════════════════════════════════════════════════════════════
MÉTODO DE TRABAJO (NO NEGOCIABLE)
═══════════════════════════════════════════════════════════════
1. UN BLOQUE DE COMANDOS POR MENSAJE. Máximo 30 líneas.
2. VERIFICAR ANTES DE PROPONER. Nunca asumas rutas, archivos o estados.
3. DOCUMENTAR ANTES DE AVANZAR. Cada paso se documenta en docs/ antes de pasar al siguiente.
4. UN SOLO OBJETIVO POR SESIÓN.
5. RECONOCER CUANDO NO SABES.
6. RAFAEL CONTROLA EL RITMO.
7. NUNCA PEGAR KEYS EN EL CHAT.
8. NO USAR Read-Host -AsSecureString.
9. NO USAR HEREDOCS GIGANTES.
10. SI ALGO FALLA, PARAR.
11. ANOTAR PENDIENTES EN EL MOMENTO.
12. AL CERRAR SESIÓN: SIEMPRE culminar con el prompt de apertura del siguiente hilo.

═══════════════════════════════════════════════════════════════
ANTI-PATRONES CONOCIDOS
═══════════════════════════════════════════════════════════════
- ERROR A: Leer archivo truncado y reportar "completo".
- ERROR B: Asumir rutas sin verificar.
- ERROR L: Parchear archivos de texto con read_text/write_text de Python (colapsa CRLF). Usar read_bytes/write_bytes.
- ERROR M: Diagnosticar sin reproducir.

═══════════════════════════════════════════════════════════════
CONFIRMACIÓN OBLIGATORIA + OBJETIVO SUGERIDO
═══════════════════════════════════════════════════════════════
Tu PRIMER mensaje debe contener SOLO:
1. Confirmación de recepción con datos verificables (líneas/bytes de los 3 docs).
2. Estado verificado (servicio, git status, git log, tail de logs).
3. Comprensión del estado actual en 3-5 frases.
4. Objetivo sugerido para esta sesión:
   Determinación del objetivo (en este orden estricto):
   a) Si HANDOFF §9 sugiere una sesión siguiente, ESA es la sugerencia.
   b) Si no, primer pendiente OPEN de PENDING.md sección "Alta prioridad".
   c) Si esa sección está limpia, primer OPEN de "Pendientes nuevos" de fecha más reciente.
   d) Si no hay Alta, tomar Media.
   e) Si no hay nada, preguntar.
   
   Formato: "Objetivo sugerido: [ID] — [descripción corta]. Razón: [una frase]. Plan de un paso: [qué haríamos primero, solo lectura]. Alternativas: [1-2 pendientes]."
5. Pregunta final: "¿Confirmas el objetivo sugerido, eliges una alternativa, o propones otro? Si confirmas, propongo el primer bloque de comandos (solo lectura)."

Empieza pidiéndome los comandos del PASO 1. No hagas nada más hasta que yo te responda.