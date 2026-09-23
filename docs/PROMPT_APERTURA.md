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

NUNCA digas "voy a leer el archivo X". No puedes. Pídeme que ejecute
un comando y me pases la salida.

REGLA CLAVE: toda solicitud de contenido se hace CON COMANDO EXPLÍCITO.
Nunca digas "pégame el contenido de X". Di "ejecuta este comando y
pégame la salida: <comando>".

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
Servicio: CometRiobamba (NSSM, LocalSystem)

VERIFICA EL HEAD actual con: git log --oneline -1
(No confíes en valores que aparezcan en documentos: siempre verifica con git.)

═══════════════════════════════════════════════════════════════
PROTOCOLO DE LECTURA POR BLOQUES
═══════════════════════════════════════════════════════════════

No puedes leer archivos. Debes pedirme que ejecute comandos y me pases
la salida. Toda solicitud de contenido lleva un comando explícito.

PASO 1 — Verificación de existencia y tamaño:

  Ejecuta esto y pégame la salida:

    cd C:\comet-riobamba-v31
    Get-Item .\docs\HANDOFF_2026-09-22.md, .\docs\PENDING.md, .\docs\MAPA_TECNICO.md | Select-Object Name, Length
    (Get-Content .\docs\HANDOFF_2026-09-22.md).Count
    (Get-Content .\docs\PENDING.md).Count
    (Get-Content .\docs\MAPA_TECNICO.md).Count

  Esperas: HANDOFF = 200 líneas, PENDING = ~140 líneas, MAPA_TECNICO = ~97 líneas.

PASO 2 — Leer HANDOFF completo:

  Ejecuta esto y pégame la salida completa:

    Get-Content .\docs\HANDOFF_2026-09-22.md

  Confirma que recibiste 200 líneas y 12 secciones antes de pasar al PASO 3.

PASO 3 — Leer PENDING completo:

  Ejecuta esto y pégame la salida completa:

    Get-Content .\docs\PENDING.md

  Confirma que ves las filas OPEN prioridad Alta antes de pasar al PASO 4.

PASO 4 — Leer MAPA_TECNICO completo:

  Ejecuta esto y pégame la salida completa:

    Get-Content .\docs\MAPA_TECNICO.md

  Confirma que ves las secciones 1-9 antes de pasar al PASO 5.

PASO 5 — Estado del servicio y git:

  Ejecuta esto y pégame la salida:

    Get-Service CometRiobamba | Select-Object Name, Status
    git status --short
    git log --oneline -3
    Get-Content .\logs\agent.log -Tail 5

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
11. AL CERRAR SESIÓN: SIEMPRE culminar con el prompt de apertura
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

ERROR J — Pedir contenido sin dar comando de lectura.
   Ejemplo: "Rafael, pégame el contenido de X" sin dar el comando.
   Rafael queda obligado a abrir el archivo manualmente, copiarlo y pegarlo.
   Eso rompe el flujo del chat.
   PREVENCIÓN: toda solicitud de contenido lleva comando explícito:
     - Archivo completo: Get-Content .\ruta\archivo.ext
     - Últimas N líneas: Get-Content .\ruta\archivo.ext -Tail N
     - Buscar patrón: Select-String -Path .\ruta\archivo.ext -Pattern "patron"
     - Estado de servicio: Get-Service <nombre>
     - Git: git log --oneline -N, git status --short

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