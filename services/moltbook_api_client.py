# -*- coding: utf-8 -*-
"""
COMET-RIOBAMBA v4.3.0 - Moltbook API Client

Cliente HTTP con:
- Autenticación por API key (Bearer).
- Circuit breaker simple para evitar cascadas de errores.
- create_post / createpost usado por Fase A y outbox.
- create_comment / createcomment pensado para Fase B respuestas.
- submit_verification / submitverification para resolver challenge post-publicación.
- fetchcomments usado por Fase B para obtener comentarios a responder.
- post_reply / postreply alias de alto nivel para responder a un comentario.
- fetch_posts / fetchposts stub defensivo para Fase C y analytics.
- get_feed / getfeed y get_comments / getcomments compatibles con APIResponse.
"""

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from config.credentials import Credentials
from utils.resilience import CircuitBreaker
from core.challenge_solver import solve_sync, LLMClientAdapter
from core.tracer import Span
from services.tool_feedback import ToolResultReceipt, compute_confidence, should_trip_circuit
from services.tool_quality_metrics import ToolQualityWindow, update_window
from services.platform_client import (
    PlatformClient, PlatformPost, PlatformComment, PublishResult,
)

logger = logging.getLogger("services.moltbook")


@dataclass
class APIResponse:
    success: bool
    status: int
    data: Dict[str, Any]
    id: Optional[str] = None
    error: Optional[str] = None


class MoltbookAPIClient(PlatformClient):
    def __init__(
        self,
        credentials: Optional[Credentials] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_seconds: int = 15,
        llm_client=None,
    ):
        self.llm_client = llm_client
        if credentials is None and base_url is None and api_key is None:
            credentials = Credentials.from_env()

        if credentials is not None:
            self.base_url = credentials.moltbook_base_url.rstrip("/")
            self.api_key = credentials.moltbook_api_key
        else:
            self.base_url = (base_url or "").rstrip("/")
            self.api_key = api_key or ""

        self.timeout_seconds = timeout_seconds

        self.session = requests.Session()
        self.circuit = CircuitBreaker(
            name="moltbook_api",
            failure_threshold=int(os.getenv("MOLTBOOK_CB_FAILURES", "5")),
            recovery_timeout=int(os.getenv("MOLTBOOK_CB_COOLDOWN_SECONDS", "60")),
        )

        if self.base_url and "/api/" not in self.base_url:
            self.base_url = self.base_url.rstrip("/") + "/api/v1"

        # ── Token-bucket rate limiter for write endpoints ────────
        # ── Separate token-bucket rate limiters by write type ────────
        self._lock = threading.Lock()
        self._buckets = {
            "post": {
                "tokens": 1.0,
                "max": 1.0,
                "window": float(os.getenv("MOLTBOOK_POST_RATE_LIMIT_SECONDS", "300.0")),
                "last_refill": time.monotonic(),
            },
            "comment": {
                "tokens": 1.0,
                "max": 1.0,
                "window": float(os.getenv("MOLTBOOK_COMMENT_RATE_LIMIT_SECONDS", "60.0")),
                "last_refill": time.monotonic(),
            },
            "action": {
                "tokens": 1.0,
                "max": 1.0,
                "window": float(os.getenv("MOLTBOOK_ACTION_RATE_LIMIT_SECONDS", "30.0")),
                "last_refill": time.monotonic(),
            },
        }
        # Legacy env vars: if set, override buckets to preserve old behavior
        _legacy_window = os.getenv("MOLTBOOK_RATE_LIMIT_WINDOW_SECONDS")
        _legacy_calls = os.getenv("MOLTBOOK_RATE_LIMIT_CALLS")
        if _legacy_window or _legacy_calls:
            _lw = float(_legacy_window) if _legacy_window else 150.0
            _lc = float(_legacy_calls) if _legacy_calls else 1.0
            for b in self._buckets.values():
                b["window"] = _lw
                b["max"] = _lc
                b["tokens"] = _lc
        self._latency_baselines_ms: Dict[str, float] = {}
        self._quality_window = ToolQualityWindow()

        if not self.api_key:
            logger.warning("MOLTBOOK_API_KEY no definido. El cliente operará en modo limitado.")
        if not self.base_url:
            logger.warning("MOLTBOOK_BASE_URL no definido. Las llamadas fallarán.")

        logger.info("MoltbookAPIClient inicializado. base_url=%s", self.base_url)

    @property
    def platform_name(self) -> str:
        return "moltbook"

    @property
    def _write_tokens(self) -> float:
        """Backward-compat property: returns tokens from the comment bucket (legacy view)."""
        return self._buckets["comment"]["tokens"]

    def _wait_for_write_token(self, endpoint_name: str, bucket_type: str = "comment") -> None:
        """Token-bucket rate limiter with separate buckets per write type.

        bucket_type: "post", "comment", or "action"
        Blocks the calling thread until a token is available in the specified bucket.
        """
        with self._lock:
            bucket = self._buckets.get(bucket_type, self._buckets["comment"])
            now = time.monotonic()
            elapsed = now - bucket["last_refill"]
            rate = bucket["max"] / bucket["window"]
            bucket["tokens"] = min(bucket["max"], bucket["tokens"] + elapsed * rate)
            bucket["last_refill"] = now

            if bucket["tokens"] < 1.0:
                wait = (1.0 - bucket["tokens"]) / rate
                logger.warning(
                    "Rate limiter [%s]: %s bloqueado por %.1fs",
                    bucket_type, endpoint_name, wait,
                )
                time.sleep(wait)
                now = time.monotonic()
                elapsed = now - bucket["last_refill"]
                bucket["tokens"] = min(bucket["max"], bucket["tokens"] + elapsed * rate)
                bucket["last_refill"] = now

            bucket["tokens"] -= 1.0

    def _call_write(self, method: str, path: str, *, json_body=None) -> Dict[str, Any]:
        """Call _request with retry logic for write endpoints.

        - 429: retry-once usando el header Retry-After si está presente.
        - 5xx: hasta _5XX_MAX_RETRIES reintentos con backoff exponencial.
        """
        _5XX_MAX_RETRIES = 2
        _5XX_BACKOFF_BASE = 5   # segundos
        _5XX_BACKOFF_MAX = 60   # techo de espera

        result = self._request(method, path, json_body=json_body, record_success=False)

        # ── 429: retry-once con Retry-After ──────────────────────────────────────
        if result.get("status") == 429:
            retry_after = result.get("retry_after_seconds")
            logger.error(
                "_call_write: 429 tras limiter local; Retry-After=%ss; reintentando una vez.",
                retry_after or "desconocido",
            )
            if retry_after:
                time.sleep(retry_after)
            result = self._request(method, path, json_body=json_body, record_success=False)
            if result.get("status") == 429:
                raise RuntimeError(
                    f"Moltbook retornó 429 incluso tras esperar {retry_after}s (Retry-After)"
                )

        # ── 5xx: backoff exponencial ──────────────────────────────────────────────
        attempt = 0
        while result.get("status", 0) >= 500 and attempt < _5XX_MAX_RETRIES:
            attempt += 1
            delay = min(_5XX_BACKOFF_BASE * (2 ** (attempt - 1)), _5XX_BACKOFF_MAX)
            logger.warning(
                "_call_write: 5xx (%s) en %s %s — intento %d/%d, esperando %ds",
                result.get("status"),
                method,
                path,
                attempt,
                _5XX_MAX_RETRIES,
                delay,
            )
            time.sleep(delay)
            result = self._request(method, path, json_body=json_body, record_success=False)

        if result.get("status", 0) >= 500:
            logger.error(
                "_call_write: 5xx persistente (%s) en %s %s tras %d reintentos — abortando.",
                result.get("status"),
                method,
                path,
                _5XX_MAX_RETRIES,
            )

        return result

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body=None,
        params=None,
        record_success: bool = True,
    ) -> Dict[str, Any]:
        if not self.circuit.can_execute():
            raise RuntimeError(
                f"Moltbook circuit breaker abierto ({self.circuit.name})"
            )

        if not self.base_url:
            raise RuntimeError("MoltbookAPIClient: base_url no configurado")

        url = self.base_url.rstrip("/") + "/" + path.lstrip("/")
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            resp = self.session.request(
                method=method.upper(),
                url=url,
                headers=headers,
                json=json_body,
                params=params,
                timeout=self.timeout_seconds,
            )
        except Exception as e:
            logger.error("MoltbookAPIClient: error de red %s %s: %s", method, url, e)
            self.circuit.record_failure()
            raise

        status = resp.status_code
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}

        result: Dict[str, Any] = {"status": status, "data": data}

        if status == 429:
            retry_after = resp.headers.get("Retry-After")
            retry_after_secs = int(retry_after) if retry_after and retry_after.isdigit() else None
            result["retry_after_seconds"] = retry_after_secs
            logger.warning(
                "MoltbookAPIClient: rate limit (429) %s %s, retry-after=%s",
                method, url, retry_after_secs or "unknown",
            )
        elif 200 <= status < 300 and record_success:
            self.circuit.record_success()
        elif status >= 400:
            logger.warning("MoltbookAPIClient: respuesta HTTP %s %s -> %s", method, url, status)
            self.circuit.record_failure()

        return result

    def _pick_list(self, data: Any, *keys: str) -> List[Dict[str, Any]]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]

        if isinstance(data, dict):
            for key in keys:
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]

        return []

    def _baseline_latency_ms(self, operation: str, latency_ms: float) -> float:
        baseline = self._latency_baselines_ms.get(operation)
        if baseline is None:
            self._latency_baselines_ms[operation] = latency_ms
            return latency_ms

        self._latency_baselines_ms[operation] = (baseline * 0.8) + (latency_ms * 0.2)
        return baseline

    def _record_tool_feedback(self, receipt: ToolResultReceipt) -> None:
        compute_confidence(receipt)
        update_window(self._quality_window, receipt)
        logger.info(
            "ToolFeedback %s outcome=%s confidence=%.3f atqs=%s status=%s",
            receipt.operation,
            receipt.outcome.value,
            receipt.confidence_score,
            self._quality_window.atqs(),
            receipt.http_status,
        )
        if should_trip_circuit(receipt):
            logger.warning(
                "ToolFeedback %s trips circuit: outcome=%s confidence=%.3f",
                receipt.operation,
                receipt.outcome.value,
                receipt.confidence_score,
            )
            if receipt.transport_ok and receipt.http_status and 200 <= receipt.http_status < 300:
                self.circuit.record_failure()
        elif receipt.transport_ok and receipt.http_status and 200 <= receipt.http_status < 300:
            self.circuit.record_success()

    def _handle_verification(self, result: dict) -> dict:
        """
        Si la respuesta contiene verification_required=True,
        resuelve el challenge y llama a POST /api/v1/verify.
        Devuelve el mismo dict con la clave '_verified' añadida.
        """
        with Span("verification_challenge") as span:
            data = result.get("data") or {}
            if not data.get("verification_required"):
                return result

            span.set("triggered", True)

            verification = data.get("verification", {})
            challenge_text = verification.get("challenge_text", "")
            verification_code = verification.get("verification_code", "")

            if not challenge_text or not verification_code:
                logger.error("[VERIFY] Faltan campos en verification object")
                return result

            logger.info(f"[VERIFY] Challenge recibido: {challenge_text[:60]}...")

            if not self.llm_client:
                logger.error("[VERIFY] llm_client no disponible, omitiendo verificación")
                return result

            answer = solve_sync(challenge_text, self.llm_client)

            if answer is None:
                logger.error("[VERIFY] No se pudo resolver el challenge, omitiendo verificación")
                return result

            span.set("solved", True)

            try:
                verify_result = self._request(
                    "POST", "/verify",
                    json_body={
                        "verification_code": verification_code,
                        "answer": answer,
                    },
                )
                result["_verified"] = verify_result.get("status", 0) in (200, 201, 204)
                logger.info(f"[VERIFY] Resultado: {verify_result}")
            except Exception as e:
                logger.error(f"[VERIFY] Error al enviar verificación: {e}")

            return result

    # ==========================
    # Creación de posts / comments
    # ==========================

    def create_post(self, title, body, metadata=None) -> Dict[str, Any]:
        metadata = metadata or {}
        submolt = metadata.get("submolt") or os.getenv("MOLTBOOK_DEFAULT_SUBMOLT", "general")
        t0 = time.monotonic()

        payload = {
            "submolt": submolt,
            "title": title or "",
            "content": body or "",
        }

        try:
            self._wait_for_write_token("create_post", bucket_type="post")
            result = self._call_write("POST", "/posts", json_body=payload)
        except Exception as e:
            latency_ms = (time.monotonic() - t0) * 1000
            logger.error("MoltbookAPIClient.create_post: excepción %s", e)
            self._record_tool_feedback(
                ToolResultReceipt(
                    tool_name="moltbook",
                    operation="create_post",
                    http_status=0,
                    transport_ok=False,
                    response_schema_ok=False,
                    response_notes=str(e),
                    latency_ms=latency_ms,
                    baseline_latency_ms=self._baseline_latency_ms("create_post", latency_ms),
                )
            )
            return {"success": False, "status": 0, "id": None, "error": str(e), "raw": {}}

        result = self._handle_verification(result)
        latency_ms = (time.monotonic() - t0) * 1000
        status = result["status"]
        data = result["data"] or {}
        post_id = None

        if isinstance(data, dict):
            post_obj = data.get("post")
            if isinstance(post_obj, dict):
                post_id = post_obj.get("id") or post_obj.get("post_id") or post_obj.get("postId")

            if not post_id:
                post_id = data.get("id") or data.get("post_id") or data.get("postId")

        success = 200 <= status < 300
        if success and data.get("verification_required") and not result.get("_verified"):
            success = False
            logger.warning("create_post: HTTP 200 but verification required and not confirmed")

        valid_id = isinstance(post_id, str) and len(post_id) > 0
        verified = not (data.get("verification_required") and not result.get("_verified"))
        response_schema_ok = (200 <= status < 300) and valid_id and verified

        self._record_tool_feedback(
            ToolResultReceipt(
                tool_name="moltbook",
                operation="create_post",
                http_status=status,
                transport_ok=True,
                response_schema_ok=response_schema_ok,
                response_notes=None if success else data.get("error", str(data)),
                latency_ms=latency_ms,
                baseline_latency_ms=self._baseline_latency_ms("create_post", latency_ms),
            )
        )

        if success:
            logger.info("MoltbookAPIClient.create_post: creado post id=%s status=%s", post_id, status)
        else:
            logger.warning("MoltbookAPIClient.create_post: fallo status=%s data=%s", status, data)

        return {"success": success, "status": status, "id": post_id, "raw": data}

    # TODO 5.0-LP3: Add rate-limit awareness (parse Retry-After header, backoff on 429 responses)

    def create_comment(
        self,
        post_id: str,
        content: str,
        parent_comment_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not post_id:
            raise ValueError("post_id es obligatorio para create_comment")

        t0 = time.monotonic()
        payload: Dict[str, Any] = {"content": content or ""}
        if parent_comment_id:
            payload["parent_id"] = parent_comment_id

        path = f"/posts/{post_id}/comments"

        try:
            self._wait_for_write_token("create_comment", bucket_type="comment")
            result = self._call_write("POST", path, json_body=payload)
        except Exception as e:
            latency_ms = (time.monotonic() - t0) * 1000
            logger.error("MoltbookAPIClient.create_comment: excepción %s", e)
            self._record_tool_feedback(
                ToolResultReceipt(
                    tool_name="moltbook",
                    operation="create_comment",
                    http_status=0,
                    transport_ok=False,
                    response_schema_ok=False,
                    response_notes=str(e),
                    latency_ms=latency_ms,
                    baseline_latency_ms=self._baseline_latency_ms("create_comment", latency_ms),
                )
            )
            return {"success": False, "status": 0, "id": None, "error": str(e), "raw": {}}

        result = self._handle_verification(result)
        latency_ms = (time.monotonic() - t0) * 1000
        status = result["status"]
        data = result["data"] or {}
        comment_id = None

        if isinstance(data, dict):
            comment_obj = data.get("comment")
            if isinstance(comment_obj, dict):
                comment_id = (
                    comment_obj.get("id")
                    or comment_obj.get("comment_id")
                    or comment_obj.get("commentId")
                )

            if not comment_id:
                comment_id = data.get("id") or data.get("comment_id") or data.get("commentId")

        success = 200 <= status < 300
        if success and data.get("verification_required") and not result.get("_verified"):
            success = False
            logger.warning("create_comment: HTTP 200 but verification required and not confirmed")

        # transport_ok = True because we got an HTTP response (no exception)
        # response_schema_ok uses stronger domain evidence than just bool(comment_id):
        #   - 2xx status
        #   - non-empty string id
        #   - verification passed if required
        # state_match is left as None because we have no read-back (GET after POST)
        valid_id = isinstance(comment_id, str) and len(comment_id) > 0
        verified = not (data.get("verification_required") and not result.get("_verified"))
        response_schema_ok = (200 <= status < 300) and valid_id and verified

        receipt = ToolResultReceipt(
            tool_name="moltbook",
            operation="create_comment",
            http_status=status,
            transport_ok=True,
            response_schema_ok=response_schema_ok,
            response_notes=None if success else data.get("error", str(data)),
            latency_ms=latency_ms,
            baseline_latency_ms=self._baseline_latency_ms("create_comment", latency_ms),
        )
        self._record_tool_feedback(receipt)

        if success:
            logger.info(
                "MoltbookAPIClient.create_comment: creado comment id=%s status=%s",
                comment_id,
                status,
            )
        else:
            logger.warning(
                "MoltbookAPIClient.create_comment: fallo al crear comment status=%s data=%s",
                status,
                data,
            )

        return {"success": success, "status": status, "id": comment_id, "raw": data}

    def submit_verification(self, verification_code: str, answer: str) -> Dict[str, Any]:
        if not verification_code:
            return {"success": False, "status": 0, "error": "verification_code requerido", "raw": {}}
        if answer is None or str(answer).strip() == "":
            return {"success": False, "status": 0, "error": "answer requerido", "raw": {}}

        payload = {
            "verification_code": verification_code,
            "answer": str(answer).strip(),
        }

        try:
            result = self._request("POST", "/verify", json_body=payload)
        except Exception as e:
            logger.error("MoltbookAPIClient.submit_verification: excepción %s", e)
            return {"success": False, "status": 0, "error": str(e), "raw": {}}

        status = result["status"]
        data = result["data"] or {}
        success = 200 <= status < 300

        if success:
            logger.info(
                "MoltbookAPIClient.submit_verification: verificación enviada correctamente status=%s",
                status,
            )
        else:
            logger.warning(
                "MoltbookAPIClient.submit_verification: fallo status=%s data=%s",
                status,
                data,
            )

        return {"success": success, "status": status, "raw": data}

    def fetch_my_posts(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return own posts from durable store with fallback sources."""
        from services.own_post_store import load_own_posts
        posts = load_own_posts(limit=limit)
        if not posts:
            logger.warning("fetch_my_posts: no own posts found in any source")
            return []
        logger.info("fetch_my_posts: %d posts propios", len(posts))
        return posts

    def fetch_post_comments(self, post_id: str) -> List[Dict[str, Any]]:
        if not post_id:
            return []

        path = f"/posts/{post_id}/comments"

        try:
            result = self._request("GET", path, params={"limit": 50})
            if 200 <= result["status"] < 300:
                data = result["data"]
                items = self._pick_list(data, "items", "comments", "data")
                logger.info("fetch_post_comments(%s): %d comentarios", post_id, len(items))

                normalized: List[Dict[str, Any]] = []
                for raw in items:
                    c = dict(raw)
                    c["post_id"] = post_id
                    c["id"] = c.get("id") or c.get("comment_id") or c.get("commentId")
                    c["text"] = c.get("text") or c.get("content") or c.get("body") or ""
                    c["content"] = c.get("content") or c.get("text") or c.get("body") or ""
                    author_raw = c.get("author") or c.get("author_name") or c.get("username") or ""
                    if isinstance(author_raw, dict):
                        c["author"] = author_raw.get("name") or author_raw.get("username") or ""
                    else:
                        c["author"] = author_raw
                    c["author_id"] = c.get("author_id") or c.get("user_id") or c.get("userid")
                    c["parent_id"] = c.get("parent_id") or c.get("parentId")
                    normalized.append(c)

                return normalized
        except Exception as e:
            logger.debug("fetch_post_comments(%s) falló: %s", post_id, e)

        return []

    def get_post(self, post_id: str):
        """GET /posts/{post_id} — return the full post dict with live score/upvotes/comment_count.

        Returns the raw post dict (all API fields preserved) on success,
        or None on any error (404, network, etc.).  Never raises.
        """
        if not post_id:
            return None
        try:
            result = self._request("GET", f"/posts/{post_id}")
            if 200 <= result["status"] < 300:
                data = result.get("data") or {}
                post = data.get("post")
                if isinstance(post, dict):
                    return dict(post)
                logger.warning("get_post(%s): respuesta sin campo 'post'", post_id)
            else:
                logger.warning("get_post(%s): HTTP %s", post_id, result["status"])
        except Exception as e:
            logger.warning("get_post(%s) falló: %s", post_id, e)
        return None

    def fetchcomments(
        self,
        sincehours: int = 4,
        excludeauthors: Optional[List[str]] = None,
        minlength: int = 0,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        excludeauthors = excludeauthors or ["comet_riobamba", "cometriobamba"]
        result = []
        try:
            my_posts = self.fetch_my_posts(limit=10)
            for post in my_posts:
                post_id = post.get("id") or post.get("postId") or post.get("post_id")
                if not post_id:
                    continue
                comments = self.fetch_post_comments(post_id)
                for c in comments:
                    author_raw = c.get("author") or c.get("username") or c.get("user") or ""
                    if isinstance(author_raw, dict):
                        author = (author_raw.get("name") or author_raw.get("username") or "").lower()
                    else:
                        author = str(author_raw).lower()
                    if author in [a.lower() for a in excludeauthors]:
                        continue
                    text = c.get("text") or c.get("content") or c.get("body") or ""
                    if len(text) < minlength:
                        continue
                    c["_post_id"] = post_id
                    result.append(c)
        except Exception as e:
            logger.error("fetchcomments: error obteniendo comentarios: %s", e)
        logger.info("fetchcomments: %d comentarios elegibles encontrados", len(result))
        return result

    # ==========================
    # Replies (Fase B)
    # ==========================

    def post_reply(
        self,
        comment_id: str,
        reply_text: str,
        post_id: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        if not post_id:
            return {"success": False, "status": 0, "error": "post_id requerido"}

        result = self.create_comment(
            post_id=post_id,
            content=reply_text,
            parent_comment_id=comment_id,
        )

        # NEVER fall back to a top-level comment.  The comment may have been
        # created server-side before an error response — retrying without
        # parent_comment_id would create a duplicate top-level comment,
        # damaging the agent's reputation.  Outbox retries handle persistence.
        if not result.get("success"):
            logger.warning(
                "post_reply: reply to comment %s on post %s failed (status=%s, error=%s); "
                "not retrying as top-level to avoid duplicate.",
                comment_id, post_id,
                result.get("status"), result.get("error"),
            )

        return result

    def fetch_posts(self, limit: int = 20, sort: str = "hot", **kwargs) -> List[Dict[str, Any]]:
        try:
            params = {"limit": limit, "sort": sort}
            result = self._request("GET", "/posts", params=params)
            if 200 <= result["status"] < 300:
                data = result["data"]
                items = self._pick_list(data, "items", "posts", "data")
                logger.info("fetch_posts: %d posts obtenidos", len(items))

                normalized: List[Dict[str, Any]] = []
                for raw in items:
                    p = dict(raw)
                    p["id"] = p.get("id") or p.get("post_id") or p.get("postId")
                    p["title"] = p.get("title") or ""
                    p["body"] = p.get("body") or p.get("content") or ""
                    p["content"] = p.get("content") or p.get("body") or ""
                    p["author"] = p.get("author") or p.get("author_name") or p.get("username") or ""
                    p["submolt"] = p.get("submolt") or p.get("community") or ""
                    p["comments"] = p.get("comments") or []
                    normalized.append(p)

                return normalized
        except Exception as e:
            logger.warning("MoltbookAPIClient.fetch_posts error: %s", e)

        return []

    def get_feed(self, *args, **kwargs) -> APIResponse:
        try:
            posts = self.fetch_posts(*args, **kwargs) or []
            return APIResponse(
                success=True,
                status=200,
                data={
                    "items": posts,
                    "posts": posts,
                },
                error=None,
            )
        except Exception as e:
            logger.warning("MoltbookAPIClient.get_feed error: %s", e)
            return APIResponse(
                success=False,
                status=0,
                data={"items": [], "posts": []},
                error=str(e),
            )

    # ==========================
    # Home dashboard
    # ==========================

    def fetch_home_dashboard(self) -> Dict[str, Any]:
        """GET /api/v1/home — account summary, notifications, activity on own posts.

        El home real devuelve:
          - your_account: {name, karma, unread_notification_count}
          - activity_on_your_posts: [{post_id, post_title, submolt_name,
            new_notification_count, latest_commenters:[...], ...}]
            < 854 en un post — el campo es 'new_notification_count'.
        Normaliza a la forma estable (karma, unread_notifications, activity).

        Returns a dict with keys:
          - karma (int)
          - unread_notifications (int)
          - active_posts (int)
          - activity_on_your_posts (list[dict]) — each item normalized with
            post_id, title, new_notification_count, authors
          - latest_moltbook_announcement (dict or None)
        On failure returns an empty dict (fail-open).
        """
        try:
            result = self._request("GET", "/home")
            if 200 <= result["status"] < 300:
                data = result.get("data") or {}
                your_account = data.get("your_account") or {}
                activity_raw = data.get("activity_on_your_posts") or []
                normalized_activity = []
                for item in activity_raw:
                    if not isinstance(item, dict):
                        continue
                    commenters = item.get("latest_commenters") or []
                    normalized_activity.append({
                        "post_id": item.get("post_id"),
                        "title": item.get("post_title") or item.get("title") or "",
                        "new_notification_count": item.get("new_notification_count", 0),
                        "authors": commenters,
                        "latest_at": item.get("latest_at"),
                    })
                return {
                    "karma": your_account.get("karma", 0),
                    "unread_notifications": your_account.get("unread_notification_count", 0),
                    "active_posts": len(activity_raw),
                    "activity_on_your_posts": normalized_activity,
                    "latest_moltbook_announcement": data.get("latest_moltbook_announcement"),
                }
            logger.warning("fetch_home_dashboard: HTTP %s", result["status"])
        except Exception as e:
            logger.warning("fetch_home_dashboard: %s", e)
        return {}

    # ==========================
    # Profile
    # ==========================

    def update_agent_profile(self, bio: str) -> bool:
        """PATCH /api/v1/agents/me — update the agent's bio on Moltbook.
        The platform stores the bio under `description` (confirmed via
        GET /agents/me); `bio` is kept for compatibility. `tagline` is
        NOT sent: the API rejects it (HTTP 400 'property tagline should
        not exist')."""
        if not bio:
            return False
        payload: Dict[str, Any] = {"description": bio, "bio": bio}
        try:
            result = self._request("PATCH", "/agents/me", json_body=payload)
            success = 200 <= result["status"] < 300
            if success:
                logger.info("Perfil actualizado correctamente en Moltbook. Status: %s", result["status"])
            else:
                logger.warning("MoltbookAPIClient: profile update failed — HTTP %s: %s",
                               result["status"], result.get("data", {}))
            return success
        except Exception as e:
            logger.warning("MoltbookAPIClient.update_agent_profile: %s", e)
            return False

    # ==========================
    # Upvotes
    # ==========================

    def upvote_post(self, post_id: str) -> bool:
        """POST /api/v1/posts/{post_id}/upvote — returns True on success."""
        if not post_id:
            return False
        try:
            self._wait_for_write_token("upvote_post", bucket_type="action")
            result = self._call_write("POST", f"/posts/{post_id}/upvote")
            success = 200 <= result["status"] < 300
            if success:
                logger.info("MoltbookAPIClient: upvoted post %s", post_id)
            else:
                logger.warning("MoltbookAPIClient: upvote failed for post %s: HTTP %s", post_id, result["status"])
            return success
        except Exception as e:
            logger.warning("MoltbookAPIClient.upvote_post: %s", e)
            return False

    # ==========================
    # Follow
    # ==========================

    def follow_agent(self, agent_name: str) -> bool:
        """POST /api/v1/agents/{name}/follow — returns True on success."""
        if not agent_name or not agent_name.strip():
            return False
        name = agent_name.strip()
        try:
            self._wait_for_write_token("follow_agent", bucket_type="action")
            result = self._call_write("POST", f"/agents/{name}/follow")
            success = 200 <= result["status"] < 300
            if success:
                logger.info("MoltbookAPIClient: followed agent %s", name)
            else:
                logger.warning("MoltbookAPIClient: follow failed for agent %s: HTTP %s", name, result["status"])
            return success
        except Exception as e:
            logger.warning("MoltbookAPIClient.follow_agent: %s", e)
            return False

    # ==========================
    # Semantic search
    # ==========================

    def semantic_search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """GET /api/v1/search?q=...&type=posts&limit=...

        Returns a list of normalized post dicts (same shape as fetch_posts).
        On failure returns an empty list (fail-open).
        """
        if not query or not query.strip():
            return []
        try:
            params = {"q": query.strip(), "type": "posts", "limit": limit}
            result = self._request("GET", "/search", params=params)
            if 200 <= result["status"] < 300:
                data = result.get("data") or {}
                items = self._pick_list(data, "items", "posts", "results", "data")
                normalized: List[Dict[str, Any]] = []
                for raw in items:
                    p = dict(raw)
                    p["id"] = p.get("id") or p.get("post_id") or p.get("postId")
                    p["title"] = p.get("title") or ""
                    p["body"] = p.get("body") or p.get("content") or ""
                    p["content"] = p.get("content") or p.get("body") or ""
                    p["author"] = p.get("author") or p.get("author_name") or p.get("username") or ""
                    p["submolt"] = p.get("submolt") or p.get("community") or ""
                    p["comments"] = p.get("comments") or []
                    p["_search_query"] = query
                    normalized.append(p)
                logger.info("semantic_search(q=%r): %d results", query, len(normalized))
                return normalized
            logger.warning("semantic_search(q=%r): HTTP %s", query, result["status"])
        except Exception as e:
            logger.warning("semantic_search: %s", e)
        return []

    def get_comments(self, post_id: str, *args, **kwargs) -> APIResponse:
        try:
            comments = self.fetch_post_comments(post_id) or []
            return APIResponse(
                success=True,
                status=200,
                data={
                    "items": comments,
                    "comments": comments,
                },
                error=None,
            )
        except Exception as e:
            logger.warning("MoltbookAPIClient.get_comments error for post %s: %s", post_id, e)
            return APIResponse(
                success=False,
                status=0,
                data={"items": [], "comments": []},
                error=str(e),
            )

    # ── PlatformClient interface implementation ──────────────────────

    def publish_post(self, title: str, body: str, metadata: Optional[Dict] = None) -> PublishResult:
        """PlatformClient adapter for create_post."""
        result = self.create_post(title, body, metadata)
        if result.get("success"):
            return PublishResult(
                success=True,
                id=result.get("id"),
                requires_verification=bool(result.get("raw", {}).get("verification_required")),
            )
        return PublishResult(success=False, error=result.get("error", "unknown"))

    def publish_comment(self, post_id: str, content: str, parent_comment_id: Optional[str] = None) -> PublishResult:
        """PlatformClient adapter for create_comment."""
        result = self.create_comment(post_id=post_id, content=content, parent_comment_id=parent_comment_id)
        if result.get("success"):
            return PublishResult(success=True, id=result.get("id"))
        return PublishResult(success=False, error=result.get("error", "unknown"))

    def upvote(self, post_id: str) -> bool:
        """PlatformClient adapter for upvote_post."""
        return self.upvote_post(post_id)

    def get_own_posts(self, limit: int = 10) -> List[PlatformPost]:
        """PlatformClient adapter for fetch_my_posts."""
        raw = self.fetch_my_posts(limit=limit)
        return [
            PlatformPost(
                id=p.get("id", ""),
                title=p.get("title", ""),
                body=p.get("body") or p.get("content", ""),
                author=p.get("author", ""),
                created_at=p.get("created_at", ""),
                upvotes=p.get("upvotes", 0),
                comment_count=p.get("comment_count", 0),
                url=p.get("url"),
                metadata=p,
            )
            for p in raw
        ]

    def get_feed_posts(self, limit: int = 20, sort: str = "hot") -> List[PlatformPost]:
        """PlatformClient adapter for fetch_posts."""
        raw = self.fetch_posts(limit=limit, sort=sort)
        return [
            PlatformPost(
                id=p.get("id", ""),
                title=p.get("title", ""),
                body=p.get("body") or p.get("content", ""),
                author=p.get("author", ""),
                created_at=p.get("created_at", ""),
                upvotes=p.get("upvotes", 0),
                comment_count=p.get("comment_count", 0),
                url=p.get("url"),
                metadata=p,
            )
            for p in raw
        ]

    def get_comments_normalized(self, post_id: str) -> List[PlatformComment]:
        """PlatformClient adapter for fetch_post_comments."""
        raw = self.fetch_post_comments(post_id)
        return [
            PlatformComment(
                id=c.get("id", ""),
                post_id=post_id,
                author=c.get("author", ""),
                content=c.get("content") or c.get("body", ""),
                created_at=c.get("created_at", ""),
                parent_comment_id=c.get("parent_id"),
                upvotes=c.get("upvotes", 0),
                metadata=c,
            )
            for c in raw
        ]

    def follow_user(self, username: str) -> bool:
        """PlatformClient adapter for follow_agent."""
        return self.follow_agent(username)

    def search(self, query: str, limit: int = 20) -> List[PlatformPost]:
        """PlatformClient adapter for semantic_search."""
        raw = self.semantic_search(query, limit=limit)
        return [
            PlatformPost(
                id=p.get("id", ""),
                title=p.get("title", ""),
                body=p.get("body") or p.get("content", ""),
                author=p.get("author", ""),
                created_at=p.get("created_at", ""),
                metadata=p,
            )
            for p in raw
        ]
