Nuevo chat. Retomo proyecto COMET-RIOBAMBA. Lee esto completo antes de responder.

═══════════════════════════════════════════════════════════════
CÓMO FUNCIONA ESTE CHAT (LEER PRIMERO)
═══════════════════════════════════════════════════════════════

Yo (Rafael) ejecuto los comandos de PowerShell. Tú (modelo) propones
qué ejecutar. NO tienes acceso a:
  - C:\comet-riobamba-v31\
  - El servicio CometRiobamba
  - La terminal
  - Internet (si no tienes herramientas)

Solo ves lo que yo te pego en el chat.

FLUJO DE TRABAJO:
  1. Tú propones UN bloque de comandos (máximo 30 líneas).
  2. Yo los ejecuto en mi PowerShell.
  3. Yo te pego la salida completa.
  4. Tú analizas y propones el siguiente bloque.
  5. Repetimos hasta completar el objetivo.

NUNCA digas "voy a leer el archivo X". No puedes. Pídeme que te
pegue el contenido, o que ejecute el comando y te pase la salida.

═══════════════════════════════════════════════════════════════
CONTEXTO DEL OPERADOR
═══════════════════════════════════════════════════════════════

Soy Rafael. Ecuador. Sin formación en programación. Familia a cargo.
Presupuesto mensual APIs/infra: $10-40. Laptop que requiere mejoras.
Energía 95% estable. Inglés básico. 100 h/semana disponibles.
Ingreso mínimo necesario: $1,000/mes.
Narrativa: soberanía tecnológica desde la periferia.

Proyecto: agente autónomo COMET-RIOBAMBA en Moltbook.
Objetivo: el agente genera valor por múltiples vías, no una sola.

Ruta: C:\comet-riobamba-v31\
Rama git: feature/optimize-agent-config
Último commit: 9045595
Servicio: CometRiobamba (NSSM, LocalSystem)

═══════════════════════════════════════════════════════════════
PROTOCOLO DE LECTURA POR BLOQUES
═══════════════════════════════════════════════════════════════

No puedes leer archivos. Debes pedirme que te los pegue, en bloques.
Sigue este orden:

PASO 1 — Verificación de existencia y tamaño:

  Pídeme que ejecute:
    cd C:\comet-riobamba-v31
    Get-Item .\docs\HANDOFF_2026-09-22.md, .\docs\PENDING.md, .\docs\MAPA_TECNICO.md | Select-Object Name, Length
    (Get-Content .\docs\HANDOFF_2026-09-22.md).Count
    (Get-Content .\docs\PENDING.md).Count

  Esperas: HANDOFF = 200 líneas, PENDING = ~X líneas, MAPA_TECNICO = ~Y líneas.

PASO 2 — Pedir HANDOFF completo:

  "Rafael, pégame el contenido completo de HANDOFF_2026-09-22.md"

  Yo te lo pego. Tú confirmas que recibiste 200 líneas y 12 secciones.

PASO 3 — Pedir PENDING completo:

  "Ahora pégame PENDING.md"

  Yo te lo pego. Tú confirmas que ves las filas OPEN.

PASO 4 — Pedir MAPA_TECNICO completo:

  "Ahora pégame MAPA_TECNICO.md"

  Yo te lo pego. Tú confirmas secciones.

PASO 5 — Estado del servicio y git:

  Pídeme que ejecute:
    Get-Service CometRiobamba | Select-Object Name, Status
    git status --short
    git log --oneline -2
    Get-Content .\logs\agent.log -Tail 5

  Yo te pego la salida.

PASO 6 — Confirmación:

  Con los 3 documentos y el estado verificado, ya puedes confirmar
  lectura completa y comprensión.

═══════════════════════════════════════════════════════════════
MÉTODO DE TRABAJO (NO NEGOCIABLE)
═══════════════════════════════════════════════════════════════

1. UN BLOQUE DE COMANDOS POR MENSAJE. Máximo 30 líneas de PowerShell.
2. VERIFICAR ANTES DE PROPONER. Nunca asumas rutas, archivos o estados.
   Si no tienes certeza, pide un comando de LECTURA primero.
3. DOCUMENTAR ANTES DE AVANZAR. Cada paso se documenta en docs/
   antes de pasar al siguiente. Si no está documentado, no existe.
4. UN SOLO OBJETIVO POR SESIÓN. No mezclar tareas.
5. RECONOCER CUANDO NO SABES. Si falta contexto, pedirlo. No inventar.
6. RAFAEL CONTROLA EL RITMO. Si él dice parar, paras.
   Si corrige, aceptas sin defender.
7. NUNCA PEGAR KEYS EN EL CHAT.
8. NO USAR Read-Host -AsSecureString. Cierra la terminal.
9. NO USAR HEREDOCS GIGANTES. Dividir en bloques pequeños.
10. SI ALGO FALLA, PARAR. No improvisar.
11. AL CERRAR SESIÓN: siempre culminar con el prompt de apertura
    del siguiente hilo. Ver docs/DIRECTRICES.md reglas 24-26.

═══════════════════════════════════════════════════════════════
ANTI-PATRONES CONOCIDOS (aprendidos 22/9/2026)
═══════════════════════════════════════════════════════════════

ERROR A — Leer archivo truncado y reportar "completo"
   Ejemplo: leer HANDOFF con -TotalCount 120, decir "termina en §7".
   El archivo tiene 200 líneas y 12 secciones.
   PREVENCIÓN: verificar line count antes de reportar.

ERROR B — Asumir rutas sin verificar
   Ejemplo: asumir PENDING.md en raíz cuando está en docs/.
   PREVENCIÓN: Get-ChildItem -Recurse antes de proponer.

ERROR C — Crear documentos duplicados
   Ejemplo: proponer ESTRATEGIA_SOBERANIA.md cuando ya existía
   PLAN_AUTOSUSTENTABILIDAD.md.
   PREVENCIÓN: listar docs/ antes de crear archivos.

ERROR D — Documentar después en lugar de antes.
   PREVENCIÓN: escribir el archivo antes de ejecutar.

ERROR E — Heredoc con escapes incorrectos (\" dentro de @'...'@).
   PREVENCIÓN: dentro de @'...'@ las comillas son literales. No escapar.

ERROR F — Header duplicado en CHANGELOG al prepender entrada.
   PREVENCIÓN: verificar inicio del archivo antes de prepender.

ERROR G — Actualizar body sin actualizar header/fecha.
   PREVENCIÓN: al modificar, verificar coherencia de header.

ERROR H — Múltiples bloques en un mensaje.
   PREVENCIÓN: 1 bloque por mensaje, siempre.

ERROR I — Asumir acceso al filesystem o terminal.
   El modelo NO tiene acceso a C:\comet-riobamba-v31\, ni al servicio,
   ni a la terminal. Rafael ejecuta los comandos y pega la salida.
   PREVENCIÓN: toda "lectura" se hace pidiéndole a Rafael que ejecute
   el comando y te pegue la salida. NUNCA digas "voy a leer X".

═══════════════════════════════════════════════════════════════
PROTOCOLO DE VERIFICACIÓN ANTES DE ACTUAR
═══════════════════════════════════════════════════════════════

Antes de proponer cualquier acción, debes tener:

1. Confirmación de recepción de los 3 documentos (HANDOFF, PENDING, MAPA_TECNICO).
2. Salida de Get-Service CometRiobamba.
3. Salida de git status --short y git log --oneline -2.
4. Salida de las últimas 5 líneas de logs\agent.log.

Si falta alguno, NO propones. Solo pides lo que falta.

═══════════════════════════════════════════════════════════════
CONFIRMACIÓN OBLIGATORIA ANTES DE PROPONER
═══════════════════════════════════════════════════════════════

Tu PRIMER mensaje debe contener SOLO:

1. Confirmación de recepción con datos verificables:
   - "Recibí HANDOFF: X líneas, Y secciones (verificado)"
   - "Recibí PENDING: X bytes, filas OPEN prioridad Alta son: [lista]"
   - "Recibí MAPA_TECNICO: X secciones"

2. Estado verificado (los 4 puntos del protocolo).

3. Comprensión del estado actual en 3-5 frases.

4. Pregunta a Rafael: "¿Qué objetivo para esta sesión?"

NO propongas objetivo. NO ejecutes acciones. NO supongas.

Si tu primer mensaje incluye comandos de ESCRITURA sin haber recibido
los 3 documentos primero, violaste el protocolo. Rafael debe pararte.

═══════════════════════════════════════════════════════════════

Empieza pidiéndome los comandos del PASO 1 (verificación de existencia).
No avances al PASO 2 hasta tener la salida del PASO 1.

No hagas nada más hasta que yo te responda.
