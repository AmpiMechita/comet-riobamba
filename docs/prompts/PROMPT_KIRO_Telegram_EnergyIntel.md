# Prompt para KIRO — Activación de Telegram + DeepSeek Balance + Energy Intel

> **Instrucciones para KIRO**: Estás en `C:\comet-riobamba-v31`. Tareas concretas, no preguntes — ejecuta. Código en inglés, logs en español.

---

## CONTEXTO

El agente ya tiene `telegram_enabled: false` en config. Probablemente existe un módulo o stub de Telegram. Necesitamos activarlo para dos funcionalidades:

1. **Balance diario de DeepSeek** — una notificación al inicio de cada día (primer ciclo del día) con el saldo en USD
2. **Alertas de Energy Intel** — cada vez que `energy_intel_node.py` genere tecnología de vanguardia, enviar el output por Telegram

El usuario ya tiene un bot de Telegram con token listo. Se pondrá en `.env` como `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`.

---

## TAREA 1: Activar Telegram (infraestructura)

1. Busca cualquier código existente de Telegram en el repo (grep por `telegram`, `TELEGRAM`, `bot_token`, `sendMessage`). Puede ser un servicio, un módulo, o solo referencias en config.
2. Si ya existe un `services/telegram.py` o similar, revísalo y asegúrate de que funcione. Si es un stub, complétalo.
3. Si no existe, crea `services/telegram.py` con:
   - Una clase `TelegramNotifier` que envie mensajes vía `https://api.telegram.org/bot{token}/sendMessage`
   - Dependency injection consistente con el resto del proyecto (ver cómo se inyectan servicios en `deps.py` o `core/agent.py`)
   - Timeout de 10s para no bloquear el ciclo
   - Error handling: si Telegram falla, log WARNING pero NO rompa el ciclo
4. Agrega al `.env`:
   ```
   TELEGRAM_ENABLED=true
   TELEGRAM_BOT_TOKEN=<el token del usuario>
   TELEGRAM_CHAT_ID=<el chat ID del usuario>
   ```
5. Activa `telegram_enabled: true` en la lógica de configuración del agente (donde se lee de .env).

---

## TAREA 2: Balance diario de DeepSeek

1. Investiga cómo consultar el saldo de DeepSeek. La API de DeepSeek expone el balance en:
   - `GET https://api.deepseek.com/user/balance` con header `Authorization: Bearer <DEEPSEEK_API_KEY>`
   - Retorna JSON con `{"balance_infos": [{"currency": "USD", "total_balance": "X.XX", ...}]}`
   
   Si el endpoint exacto es diferente, revisa la doc de DeepSeek API o busca en el código si ya hay una referencia.

2. Crea una función `check_deepseek_balance()` que:
   - Haga el request con la API key ya configurada en `.env` (busca cómo se obtiene en `services/model_cascade.py` — probablemente está en `os.environ` o config)
   - Retorne el balance en USD como float
   - Si falla, retorne None con log WARNING

3. Integra en el ciclo del agente (`core/agent.py`):
   - Al inicio del primer ciclo del día (cuando `self.state.posts_today == 0` y `self.state.comments_today == 0`, o mejor: usa un timestamp de "último balance enviado" para evitar enviar en cada restart)
   - Llama a `check_deepseek_balance()`
   - Si es la primera vez del día, envía por Telegram un mensaje como:
   ```
   💰 DeepSeek Balance: $X.XX USD
   📅 Fecha: 2026-06-26
   🔄 Último ciclo: #N
   ```
   - Incluye un WARNING visual si el balance < $2.00: `⚠️ SALDO BAJO — recargar recomendado`

4. Persiste el timestamp del último envío en `comet_state.db` (agrega campo `last_balance_check`) o usa un archivo simple como `data/last_balance_check.txt`.

---

## TAREA 3: Energy Intel → Telegram

1. Lee `energy_intel_node.py` completo para entender:
   - ¿Qué produce? (texto, JSON, un post, una alerta?)
   - ¿Dónde se llama? (¿es un módulo independiente, se llama desde Phase C, o desde otro lado?)
   - ¿Qué significa "tecnología de vanguardia" en este contexto? (¿un filtro de novedad? ¿un score de originalidad?)

2. Identifica el punto exacto donde `energy_intel_node.py` genera un resultado que el usuario considera "de vanguardia" (busca logs, returns, o publicaciones).

3. En ese punto, agrega una llamada a `TelegramNotifier.send()` con:
   - Un resumen del hallazgo (titulo + 1-2 oraciones)
   - Un link al post si se publicó en Moltbook
   - Formato:
   ```
   ⚡ Energy Intel: <titulo del hallazgo>
   <resumen de 1-2 lineas>
   🔗 <url del post si aplica>
   ```

4. **No dupliques notificaciones**: Si energy_intel ya genera un post en Moltbook, la notificación de Telegram debe ser adicional, no reemplazar el post.

---

## TAREA 4: Tests

1. Mock `requests.post` para Telegram (no enviar mensajes reales en tests)
2. Mock la API de DeepSeek balance
3. Test cases mínimos:
   - `test_telegram_send_success` — mensaje enviado correctamente
   - `test_telegram_send_failure_doesnt_crash` — si Telegram falla, no levanta excepción
   - `test_deepseek_balance_parse` — parsea correctamente el JSON de balance
   - `test_balance_not_sent_twice_same_day` — no envía dos veces el mismo día
   - `test_energy_intel_sends_telegram` — cuando energy intel genera output, se llama a telegram

---

## REGLAS

- No rompas los tests existentes
- Telegram es **fire-and-forget**: si falla, el agente sigue su ciclo normalmente
- No envíes spam de Telegram: max 1 balance/día, y solo 1 notificación por hallazgo de energy intel
- Si `energy_intel_node.py` es complejo y no entiendes su output, describe lo que encuentras en un log comment y deja el hook listo para que el usuario ajuste el filtro
- Commits granulares: 1 commit por tarea

Empieza leyendo `energy_intel_node.py` y buscando código existente de Telegram en el repo. Luego activa la infraestructura Telegram (Tarea 1), y sobre esa base construye las Tareas 2 y 3.