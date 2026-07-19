# -*- coding: utf-8 -*-
"""
Telegram Bot API transport layer.

Responsabilidades:
  - Recepción de updates vía polling (getUpdates)
  - Envío de mensajes (sendMessage)
  - Routing de comandos built-in (/status, /force, /clean, /stop, etc.)
  - Delegación de comandos extendidos a services.telegram_control (incl. /health)

NO maneja lógica de comandos administrativos — esos se resuelven en
services.telegram_control.handle_command(). Este módulo es solo transporte.
"""
import asyncio
import json
import logging
import os
import time
import requests
from pathlib import Path
from typing import Optional
from config import behavior_cfg, BASE_DIR
from config.agent_policy import POLICY

logger = logging.getLogger("services.telegram_client")

class TelegramClient:
    def __init__(self, bot_token: str, chat_id: str, enabled: bool = True):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = enabled and bool(bot_token) and bool(chat_id)
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

        if self.enabled:
            logger.info(f"✅ Telegram client initialized for chat {chat_id}")
        else:
            logger.info("ℹ️ Telegram client disabled")

        # ── /clean confirmation state ──
        self._pending_clean: dict | None = None

    def _send(self, method: str, payload: dict) -> bool:
        if not self.enabled: return False
        try:
            url = f"{self.base_url}/{method}"
            response = requests.post(url, json=payload, timeout=30)
            if response.status_code == 200:
                return response.json().get("ok", False)
            return False
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False

    def send_message(self, text: str, parse_mode: str = "HTML", disable_notification: bool = False) -> bool:
        if len(text) > 4000: text = text[:3900] + "\n\n...(truncado)"
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": parse_mode, "disable_notification": disable_notification}
        return self._send("sendMessage", payload)

    def send_alert(self, title: str, message: str, level: str = "WARNING") -> bool:
        emojis = {"ERROR": "🔴", "WARNING": "🟡", "INFO": "🔵", "SUCCESS": "🟢"}
        text = f"{emojis.get(level.upper(), '⚪')} <b>{title}</b>\n\n{message}"
        return self.send_message(text, parse_mode="HTML")

    OFFSET_FILE = BASE_DIR / "data" / "telegram_offset.json"
    _STALE_SECONDS = 60  # Ignore messages older than this

    def _load_offset(self) -> int:
        try:
            if self.OFFSET_FILE.exists():
                data = json.loads(self.OFFSET_FILE.read_text(encoding="utf-8"))
                offset = int(data.get("offset", 0))
                logger.info("Telegram: loaded persisted offset=%d", offset)
                return offset
        except Exception as e:
            logger.warning("Telegram: failed to load offset: %s", e)
        return 0

    def _save_offset(self, offset: int) -> None:
        try:
            self.OFFSET_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.OFFSET_FILE.write_text(
                json.dumps({"offset": offset}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Telegram: failed to save offset=%d: %s", offset, e)

    def _flush_pending_updates(self) -> int:
        """Flush all pending updates from the queue before starting the listener.
        Returns the highest update_id seen (to use as starting offset)."""
        try:
            url = f"{self.base_url}/getUpdates"
            # Get all pending updates with timeout=0 (return immediately)
            response = requests.get(url, params={"timeout": 0, "offset": -1}, timeout=10)
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    updates = result.get("result", [])
                    if updates:
                        max_id = max(u["update_id"] for u in updates)
                        new_offset = max_id + 1
                        logger.info("Telegram: flushed %d pending updates, new offset=%d", len(updates), new_offset)
                        return new_offset
        except Exception as e:
            logger.warning("Telegram: flush error: %s", e)
        return 0

    def _is_stale_message(self, message: dict) -> bool:
        """Return True if the message is older than _STALE_SECONDS."""
        msg_date = message.get("date", 0)
        if msg_date:
            age = time.time() - msg_date
            if age > self._STALE_SECONDS:
                logger.info("Telegram: ignoring stale message (age=%.0fs, date=%s, text=%s)",
                            age, msg_date, message.get("text", "")[:50])
                return True
        return False

    async def listen_for_commands(self, agent):
        if not self.enabled: return

        # ── Flush pending queue first ──
        flushed_offset = self._flush_pending_updates()

        # ── Load persisted offset, favoring the flushed value ──
        persisted_offset = self._load_offset()
        offset = max(flushed_offset, persisted_offset)
        if offset > 0:
            self._save_offset(offset)

        logger.info("Telegram listener iniciado y esperando mensajes... (offset=%d)", offset)

        while not getattr(agent, "shutdown_requested", False):
            try:
                updates = await asyncio.to_thread(self._get_updates, offset)
                if updates:
                    for update in updates:
                        offset = update["update_id"] + 1
                        self._save_offset(offset)
                        try:
                            await self._process_update(agent, update)
                        except Exception as e:
                            logger.warning("Telegram: error procesando update %s: %s", update.get("update_id"), e)
            except Exception as e:
                logger.warning("Telegram: listener tick error: %s", e)

            await asyncio.sleep(3)

    async def _process_update(self, agent, update: dict):
        """
        Procesa un update entrante de Telegram.

        Built-in commands (/status, /clean, /stop, etc.) se manejan aquí.
        Extended commands (incl. /health) se delegan a
        services.telegram_control.handle_command().
        Voice messages se delegan a _handle_voice().
        Free text se delega a _handle_assistant().
        """
        message = update.get("message", {})
        text = message.get("text", "").strip()
        chat_id = str(message.get("chat", {}).get("id"))

        if chat_id != str(self.chat_id):
            return

        # ── Ignore stale / replayed messages from history ──
        if self._is_stale_message(message):
            return

        # ── Voice message handler (v5.0: Modo Asistente con Whisper) ──
        if "voice" in message:
            await self._handle_voice(agent, message)
            return

        # ── Built-in legacy commands ──
        if text == "/status":
            await self._handle_status(agent)
        elif text == "/force":
            await self._handle_force(agent)
        elif text == "/clean":
            await self._handle_clean(agent)
        elif text == "/clean_confirm":
            await self._handle_clean_confirm(agent)
        elif text == "/reconcile":
            await self._handle_reconcile(agent)
        elif text.startswith("/reconcile_resolve "):
            parts = text.split(" ", 2)
            if len(parts) >= 3:
                await self._handle_reconcile_resolve(agent, parts[1], parts[2])
            else:
                self.send_message("❌ Uso: /reconcile_resolve &lt;id&gt; published|failed")
        elif text == "/stop":
            await self._handle_stop(agent)
        elif text == "/posts":
            await self._handle_posts(agent)
        elif text == "/ideas":
            await self._handle_ideas(agent)
        elif text.startswith("/comments "):
            await self._handle_comments(agent, text.split(" ", 1)[1])
        elif text.startswith("/thread "):
            await self._handle_thread(agent, text.split(" ", 1)[1])

        # ── v5.0: Extended commands (telegram_control) ──
        elif text.startswith("/"):
            try:
                from services.telegram_control import handle_command
                response = handle_command(text, agent=agent)
                if response:
                    self.send_message(response)
            except Exception as e:
                logger.warning("Telegram: extended command error: %s", e)

        # ── v5.0: Modo Asistente — free-text query to LLM ──
        elif text:
            await self._handle_assistant(agent, text)

    def _get_updates(self, offset: int) -> list:
        try:
            url = f"{self.base_url}/getUpdates"
            response = requests.get(url, params={"timeout": 2, "offset": offset}, timeout=30)
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"): return result.get("result", [])
        except Exception: pass
        return []

    async def _handle_status(self, agent):
        cycle = getattr(agent, "cycle_count", 0)
        posts = getattr(agent, "posts_today", 0)
        max_posts = behavior_cfg.get("max_posts_per_day", POLICY.max_posts_per_day)
        outbox_count = 0
        try:
            from services.persistence import get_conn
            with get_conn() as conn:
                outbox_count = conn.execute("SELECT count(*) FROM outbox WHERE status = 'pending'").fetchone()[0]
        except: pass

        text = (
            f"📊 <b>Estado COMET-RIOBAMBA</b>\n\n"
            f"🔄 Ciclo: <code>{cycle}</code>\n"
            f"📝 Posts hoy: <code>{posts}/{max_posts}</code>\n"
            f"📤 Outbox: <code>{outbox_count}</code> pendientes\n"
            f"🟢 Estado: <code>Operativo</code>"
        )
        self.send_message(text)

    async def _handle_force(self, agent):
        self.send_message("⚡ <b>Comando recibido</b>\nForzando ciclo inmediato...")
        agent.force_cycle_requested = True

    async def _handle_stop(self, agent):
        """v5.0: Solicita detener el agente de forma controlada."""
        self.send_message("⏹️ <b>Deteniendo agente...</b>\nCerrando ciclo actual y guardando estado.")
        agent.shutdown_requested = True
        logger.info("Telegram: /stop recibido — shutdown_requested = True")

    async def _handle_clean(self, agent):
        try:
            from services.persistence import get_conn
            with get_conn() as conn:
                pending = conn.execute(
                    "SELECT COUNT(*) FROM outbox WHERE status = 'pending'"
                ).fetchone()[0]
        except Exception as e:
            self.send_message(f"❌ Error leyendo outbox: <code>{e}</code>")
            return

        if pending == 0:
            self.send_message("📭 No hay items pendientes en el outbox.")
            return

        self._pending_clean = {"count": pending, "since": time.monotonic()}
        self.send_message(
            f"⚠️ <b>Confirmacion requerida</b>\n"
            f"Se eliminaran <code>{pending}</code> posts/comentarios pendientes "
            f"del outbox.\n\n"
            f"Esta accion es <b>IRREVERSIBLE</b>.\n\n"
            f"Envia /clean_confirm en los proximos <b>60 segundos</b> para proceder."
        )

    async def _handle_clean_confirm(self, agent):
        pending = self._pending_clean
        if not pending:
            self.send_message("❌ No hay una solicitud de /clean pendiente. Envia /clean primero.")
            return

        elapsed = time.monotonic() - pending["since"]
        self._pending_clean = None

        if elapsed > 60:
            self.send_message(
                f"⏰ La ventana de confirmacion expiro ({elapsed:.0f}s > 60s). "
                "Envia /clean de nuevo para reintentar."
            )
            return

        try:
            count = pending["count"]
            logger.warning(
                "TELEGRAM /clean_confirm: borrando %d items pending del outbox. "
                "Accion iniciada desde Telegram chat_id=%s.",
                count, self.chat_id,
            )
            from services.persistence import get_conn
            with get_conn() as conn:
                deleted = conn.execute(
                    "DELETE FROM outbox WHERE status = 'pending'"
                ).rowcount
            self.send_message(
                f"🧹 <b>Outbox limpiado</b>\n"
                f"Se eliminaron <code>{deleted}</code> items pendientes."
            )
        except Exception as e:
            self.send_message(f"❌ Error al limpiar outbox: <code>{e}</code>")


    async def _handle_reconcile(self, agent):
        """List outbox items in 'needs_reconciliation' status."""
        try:
            from services.persistence import get_conn
            with get_conn() as conn:
                rows = conn.execute(
                    "SELECT id, kind, payload_json, created_at, last_error "
                    "FROM outbox WHERE status = 'needs_reconciliation' "
                    "ORDER BY id ASC LIMIT 20"
                ).fetchall()
        except Exception as e:
            self.send_message(f"❌ Error leyendo outbox: <code>{e}</code>")
            return

        if not rows:
            self.send_message("📭 No hay items pendientes de reconciliacion.")
            return

        lines = ["⚠️ <b>Items pendientes de reconciliacion</b>\n"]
        for row in rows:
            rid, kind, payload_json, created_at, last_error = row
            payload_snippet = (payload_json or "")[:80]
            err_snippet = (last_error or "")[:60]
            lines.append(
                f"<b>ID:</b> <code>{rid}</code> | <b>{kind}</b>\n"
                f"<b>Payload:</b> {payload_snippet}\n"
                f"<b>Creado:</b> {created_at or '?'}\n"
                f"<b>Error:</b> {err_snippet}\n"
            )
        lines.append(
            "\nPara resolver: /reconcile_resolve &lt;id&gt; published|failed\n"
            "Verifica en Moltbook si el post se publico antes de decidir."
        )
        self.send_message("\n".join(lines))


    async def _handle_reconcile_resolve(self, agent, item_id_str: str, outcome: str):
        """Resolve a needs_reconciliation item as published or failed."""
        if outcome not in ("published", "failed"):
            self.send_message("❌ Outcome debe ser 'published' o 'failed'.")
            return

        item_id = None
        try:
            item_id = int(item_id_str)
        except ValueError:
            self.send_message(f"❌ ID invalido: <code>{item_id_str}</code>")
            return

        try:
            from services.persistence import get_conn
            with get_conn() as conn:
                row = conn.execute(
                    "SELECT status, kind, payload_json FROM outbox WHERE id = ?", (item_id,)
                ).fetchone()
                if not row:
                    self.send_message(f"❌ No se encontro el item <code>{item_id}</code>.")
                    return
                current_status, kind, payload_json = row
                if current_status != "needs_reconciliation":
                    self.send_message(
                        f"❌ El item <code>{item_id}</code> ya fue resuelto "
                        f"(status actual: <code>{current_status}</code>)."
                    )
                    return
        except Exception as e:
            self.send_message(f"❌ Error leyendo outbox: <code>{e}</code>")
            return

        try:
            from services.persistence import get_conn
            with get_conn() as conn:
                conn.execute(
                    "UPDATE outbox SET status = ?, updated_at = datetime('now') WHERE id = ?",
                    (outcome, item_id),
                )
            logger.warning(
                "TELEGRAM /reconcile_resolve: item %d (%s) marcado como '%s' por operador. "
                "Accion desde Telegram chat_id=%s.",
                item_id, kind, outcome, self.chat_id,
            )
            self.send_message(
                f"✅ Item <code>{item_id}</code> ({kind}) marcado como "
                f"<b>{outcome}</b>."
            )
        except Exception as e:
            self.send_message(f"❌ Error actualizando outbox: <code>{e}</code>")

    async def _handle_posts(self, agent):
        """Muestra los últimos posts publicados."""
        import json
        
        log_path = Path('data/published_posts.json')
        if not log_path.exists():
            self.send_message("📭 No hay posts registrados aún.")
            return
        
        history = json.loads(log_path.read_text(encoding='utf-8'))
        recent = history[-3:]  # Últimos 3
        
        lines = ["📝 <b>Últimos Posts Publicados</b>\n"]
        for i, post in enumerate(reversed(recent), 1):
            post_id = post.get('post_id', 'N/A')
            topic = post.get('topic', 'Sin tema')
            date = post.get('published_at', '')[:10]
            lines.append(f"<b>{i}.</b> [{date}]")
            lines.append(f"📌 {topic}")
            lines.append(f"🔗 <code>{post_id}</code>\n")
        
        lines.append("💡 Usa /comments &lt;post_id&gt; para ver comentarios")
        self.send_message("\n".join(lines))

    async def _handle_comments(self, agent, post_id: str):
        """Muestra los comentarios de un post específico."""
        moltbook = getattr(agent, 'moltbook_api_client', None)
        if not moltbook:
            self.send_message("❌ Cliente Moltbook no disponible.")
            return
        
        try:
            comments = moltbook.fetch_post_comments(post_id)
            if not comments:
                self.send_message(f"💬 No hay comentarios en el post <code>{post_id[:8]}...</code>")
                return
            
            lines = [f"💬 <b>Comentarios del post</b>\n<code>{post_id}</code>\n"]
            for c in comments[:5]:  # Máximo 5 comentarios
                author_data = c.get('author') or c.get('name') or {}
                if isinstance(author_data, dict):
                    author = author_data.get('name', 'Unknown')
                else:
                    author = str(author_data)
                
                text = c.get('text') or c.get('content') or c.get('body', '')
                text_preview = text[:150] + "..." if len(text) > 150 else text
                
                lines.append(f"👤 <b>{author}</b>:")
                lines.append(f"<i>{text_preview}</i>\n")
            
            self.send_message("\n".join(lines))
        except Exception as e:
            self.send_message(f"❌ Error: {e}")

    async def _handle_thread(self, agent, comment_id: str):
        """Muestra el contexto completo de un comentario."""
        self.send_message(f"🧵 <b>Thread</b>\n<code>{comment_id}</code>\n\n💡 Función en desarrollo. Usa /comments para ver el contexto completo.")

    async def _handle_assistant(self, agent, user_text: str):
        """v5.0 Modo Asistente: route free-text queries to the LLM with agent context."""
        logger.info("Telegram: Modo Asistente — query recibida: %s...", user_text[:80])
        try:
            from services.telegram_control import handle_assistant_query
            response = await handle_assistant_query(user_text, agent)
            self.send_message(response)
        except Exception as e:
            logger.warning("Telegram: Modo Asistente falló: %s", e)
            self.send_message("⚠️ Mi cascada LLM está degradada ahora mismo. Intenta de nuevo en un momento.")

    async def _handle_voice(self, agent, message: dict):
        """v5.0: Transcribe voice messages via Whisper and route to assistant."""
        voice = message.get("voice", {})
        file_id = voice.get("file_id")
        if not file_id:
            self.send_message("🎤 No se pudo identificar el archivo de audio.")
            return

        logger.info("Telegram: voice message recibido, file_id=%s", file_id)
        self.send_message("🎧 Transcribiendo tu nota de voz...")

        try:
            # Download voice file from Telegram
            file_info_url = f"{self.base_url}/getFile"
            resp = requests.get(file_info_url, params={"file_id": file_id}, timeout=15)
            if not resp.ok:
                raise RuntimeError(f"getFile returned {resp.status_code}")
            file_path = resp.json().get("result", {}).get("file_path")
            if not file_path:
                raise RuntimeError("No file_path in getFile response")

            download_url = f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"
            audio_resp = requests.get(download_url, timeout=30)
            if not audio_resp.ok:
                raise RuntimeError(f"Download returned {audio_resp.status_code}")

            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                tmp.write(audio_resp.content)
                audio_path = tmp.name

            # Try Whisper transcription
            transcript_text = ""
            try:
                import openai
                openai_client = openai.OpenAI()
                with open(audio_path, "rb") as audio_file:
                    transcript = openai_client.audio.transcriptions.create(
                        model="whisper-1", file=audio_file
                    )
                transcript_text = transcript.text.strip()
                logger.info("Telegram: Whisper transcript: %s", transcript_text[:100])
            except ImportError:
                logger.warning("Telegram: openai not installed, skipping Whisper transcription")
                self.send_message("⚠️ Whisper no está configurado (openai no instalado).")
                return
            except Exception as e:
                logger.warning("Telegram: Whisper transcription failed: %s", e)
                self.send_message(f"⚠️ Error al transcribir: {e}")
                return
            finally:
                try:
                    Path(audio_path).unlink(missing_ok=True)
                except Exception:
                    pass

            if not transcript_text:
                self.send_message("🎤 No se detectó texto en el audio.")
                return

            # Route transcript to assistant
            self.send_message(f"🎤 <i>Transcripción:</i> {transcript_text[:200]}")
            await self._handle_assistant(agent, transcript_text)

        except Exception as e:
            logger.warning("Telegram: voice handler error: %s", e)
            self.send_message("⚠️ No se pudo procesar la nota de voz. Intenta con texto.")

    async def _handle_ideas(self, agent):
        """Muestra las últimas ideas de proyectos I+D generadas por el agente."""
        import json
        from pathlib import Path

        ideas_path = Path("data/project_ideas.jsonl")
        if not ideas_path.exists():
            self.send_message("💡 Aún no hay ideas de proyectos I+D. Espera a que el agente sintetice conocimiento en la Fase C.")
            return

        try:
            entries = []
            for line in ideas_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entries.append(json.loads(line.strip()))

            if not entries:
                self.send_message("💡 No hay ideas de proyectos aún.")
                return

            recent = entries[-3:]
            lines = ["💡 <b>Proyectos I+D (últimos 3)</b>\n"]
            for e in reversed(recent):
                ts = e.get("timestamp", "?")[:19]
                text = e.get("ideas", "")[:400]
                cycle = e.get("cycle", "?")
                lines.append(f"📌 <i>Ciclo {cycle} — {ts}</i>")
                lines.append(f"{text}\n")

            self.send_message("\n".join(lines))
        except Exception as e:
            self.send_message(f"❌ Error: {e}")


def create_telegram_client() -> Optional[TelegramClient]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    enabled = bool(int(os.getenv("TELEGRAM_ALERTS_ENABLED", "1")))
    if not token or not chat_id: return None
    return TelegramClient(token, chat_id, enabled)
