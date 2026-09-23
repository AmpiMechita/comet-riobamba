# PROMPT DE APERTURA — COMET-RIOBAMBA

Copiar este prompt completo al inicio de cada nuevo chat.

---

Nuevo chat. Retomo proyecto COMET-RIOBAMBA. Lee esto completo antes de responder.

═══════════════════════════════════════════════════════════════
CONTEXTO DEL OPERADOR
═══════════════════════════════════════════════════════════════

Soy Rafael. Ecuador. Sin formación en programación. Familia a cargo.
Presupuesto mensual APIs/infra: $10-40. Laptop que requiere mejoras.
Energía 95% estable. Inglés básico. 100 h/semana disponibles.
Ingreso mínimo necesario: $1,000/mes.
Narrativa: soberanía tecnológica desde la periferia.

Proyecto: agente autónomo COMET-RIOBAMBA en Moltbook.
Estado: el agente genera valor por múltiples vías, no una sola.

Ruta: C:\comet-riobamba-v31\
Rama git: feature/optimize-agent-config
Servicio: CometRiobamba (NSSM, LocalSystem)

═══════════════════════════════════════════════════════════════
LECTURA OBLIGATORIA (sin truncar, verificar completo)
═══════════════════════════════════════════════════════════════

Debes leer estos 3 archivos COMPLETOS. No uses -TotalCount ni -First.
Si usas un comando de lectura, verifica que leíste todo el archivo.

Archivo 1: C:\comet-riobamba-v31\docs\HANDOFF_2026-09-22.md
  → 200 líneas, 12 secciones
  → VERIFICA: cuenta las líneas y confirma que son 200

Archivo 2: C:\comet-riobamba-v31\docs\PENDING.md
  → ~10,300 bytes, ledger de pendientes
  → VERIFICA: lee el header y las filas OPEN

Archivo 3: C:\comet-riobamba-v31\docs\MAPA_TECNICO.md
  → 3,177 bytes, mapa de servicios/wrappers/endpoints
  → VERIFICA: lee las secciones 1-9

Comandos de verificación (ejecútalos primero):

  cd C:\comet-riobamba-v31
  (Get-Content .\docs\HANDOFF_2026-09-22.md).Count
  (Get-Content .\docs\PENDING.md).Count
  Select-String -Path .\docs\HANDOFF_2026-09-22.md -Pattern "^## " | Select-Object LineNumber, Line

═══════════════════════════════════════════════════════════════
MÉTODO DE TRABAJO (NO NEGOCIABLE)
═══════════════════════════════════════════════════════════════

1. UN BLOQUE DE COMANDOS POR MENSAJE. Máximo 30 líneas de PowerShell.
2. VERIFICAR ANTES DE PROPONER. Nunca asumas rutas o estructuras.
3. DOCUMENTAR ANTES DE AVANZAR. El paso actual se escribe en docs/ antes del siguiente.
4. UN SOLO OBJETIVO POR SESIÓN. No mezclar tareas.
5. RECONOCER CUANDO NO SABES. Si falta contexto, pedirlo. No inventar.
6. RAFAEL CONTROLA EL RITMO. Si dice parar, paras. Si corrige, aceptas sin defender.
7. NUNCA PEGAR KEYS EN EL CHAT.
8. NO USAR Read-Host -AsSecureString. Cierra la terminal.
9. NO USAR HEREDOCS GIGANTES. Dividir en bloques pequeños.
10. SI ALGO FALLA, PARAR. No improvisar.

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

═══════════════════════════════════════════════════════════════
PROTOCOLO DE VERIFICACIÓN ANTES DE ACTUAR
═══════════════════════════════════════════════════════════════

Antes de proponer cualquier acción, ten estos 4:

1. Get-Service CometRiobamba | Select-Object Name, Status
2. git status --short && git log --oneline -2
3. Get-Content .\logs\agent.log -Tail 5
4. Confirmación de lectura completa de los 3 documentos.

Si no tienes los 4, no propones. Solo pides lo que falta.

═══════════════════════════════════════════════════════════════
CONFIRMACIÓN OBLIGATORIA ANTES DE PROPONER
═══════════════════════════════════════════════════════════════

Tu PRIMER mensaje contiene SOLO:

1. Confirmación de lectura con datos verificables:
   - "Leí HANDOFF: X líneas, Y secciones"
   - "Leí PENDING: X bytes, filas OPEN prioridad Alta son: [lista]"
   - "Leí MAPA_TECNICO: X secciones"

2. Estado verificado (4 comandos del protocolo).

3. Comprensión del estado actual en 3-5 frases.

4. Pregunta a Rafael: "¿Qué objetivo para esta sesión?"

NO propongas objetivo. NO ejecutes acciones. NO supongas.

Si tu primer mensaje incluye escritura sin confirmar lectura,
Rafael debe pararte.

═══════════════════════════════════════════════════════════════

Empieza por leer los 3 documentos COMPLETOS. Verifica line counts.
Ejecuta el protocolo de verificación. Confirma comprensión.
Pregunta objetivo.

No hagas nada más hasta que Rafael responda.
