"""
utils/resilience.py — Circuit Breaker canónico + Retry con Exponential Backoff
COMET-RIOBAMBA v4.3

Implementación única de CircuitBreaker usada por:
- services/global_circuit.py (con persistencia SQLite)
- services/model_cascade.py (por proveedor, en memoria)
- services/moltbook_api_client.py (en memoria)
"""
import asyncio
import logging
import random
import time
from abc import ABC, abstractmethod
from enum import Enum
from functools import wraps
from typing import Any, Callable, Optional, Type, Tuple

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitPersistence(ABC):
    @abstractmethod
    def load(self, name: str) -> Optional[dict]:
        ...

    @abstractmethod
    def save(self, name: str, state: dict) -> None:
        ...


class SQLiteCircuitPersistence(CircuitPersistence):
    def load(self, name: str) -> Optional[dict]:
        from services.persistence import get_flag
        return get_flag(name)

    def save(self, name: str, state: dict) -> None:
        from services.persistence import set_flag
        set_flag(name, state)


class CircuitBreaker:
    """
    Circuit Breaker canónico.
    CLOSED → OPEN (tras failure_threshold fallos)
    OPEN → HALF_OPEN (tras recovery_timeout segundos)
    HALF_OPEN → CLOSED (tras success_threshold éxitos consecutivos)

    Si se proporciona persistence, el estado se persiste entre reinicios.
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 1,
        persistence: Optional[CircuitPersistence] = None,
        on_open: Optional[Callable[[str], None]] = None,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.persistence = persistence
        self.on_open = on_open

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._last_error: str = ""

        if persistence:
            self._load()

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - (self._last_failure_time or 0) >= self.recovery_timeout:
                logger.info(
                    "🔌 CircuitBreaker [%s]: OPEN → HALF_OPEN (timeout %.0fs)",
                    self.name, self.recovery_timeout,
                )
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
                self._save()
        return self._state

    def record_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.success_threshold:
                logger.info(
                    "✅ CircuitBreaker [%s]: HALF_OPEN → CLOSED (%d/%d successes)",
                    self.name, self._success_count, self.success_threshold,
                )
                self._state = CircuitState.CLOSED
        elif self._state == CircuitState.OPEN:
            pass
        self._failure_count = 0
        self._last_failure_time = None
        self._last_error = ""
        self._save()

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self.failure_threshold and self._state != CircuitState.OPEN:
            logger.warning(
                "⚡ CircuitBreaker [%s]: CLOSED → OPEN (fallos: %d/%d)",
                self.name, self._failure_count, self.failure_threshold,
            )
            self._state = CircuitState.OPEN
            if self.on_open:
                try:
                    self.on_open(self.name)
                except Exception as e:
                    logger.warning("CircuitBreaker [%s]: on_open callback failed: %s", self.name, e)
        self._last_error = ""
        self._save()

    def force_open(self, reason: str = "", duration_seconds: Optional[float] = None) -> None:
        if duration_seconds is not None:
            self.recovery_timeout = duration_seconds
        was_open = self._state == CircuitState.OPEN
        self._state = CircuitState.OPEN
        if self.on_open and not was_open:
            try:
                self.on_open(self.name)
            except Exception as e:
                logger.warning("CircuitBreaker [%s]: on_open callback failed: %s", self.name, e)
        self._failure_count = self.failure_threshold
        self._success_count = 0
        self._last_failure_time = time.monotonic()
        self._last_error = reason
        logger.warning("🚫 CircuitBreaker [%s]: force_open (reason=%s, timeout=%.0fs)", self.name, reason, self.recovery_timeout)
        self._save()

    def can_execute(self) -> bool:
        return self.state != CircuitState.OPEN

    def reset(self) -> None:
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
        self._last_error = ""
        logger.info("🔄 CircuitBreaker [%s]: reset → CLOSED", self.name)
        self._save()

    def get_stats(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "failure_threshold": self.failure_threshold,
            "success_threshold": self.success_threshold,
            "recovery_timeout": self.recovery_timeout,
            "last_error": self._last_error,
        }

    def _load(self) -> None:
        if not self.persistence:
            return
        data = self.persistence.load(self.name) or {}
        try:
            self._state = CircuitState(data.get("state", "closed"))
        except ValueError:
            self._state = CircuitState.CLOSED
        self._failure_count = int(data.get("failure_count", 0))
        self._success_count = int(data.get("success_count", 0))
        self._last_failure_time = data.get("last_failure_time")
        self._last_error = data.get("last_error", "")

    def _save(self) -> None:
        if not self.persistence:
            return
        data = {
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure_time": self._last_failure_time,
            "last_error": self._last_error,
        }
        self.persistence.save(self.name, data)


async def async_retry(
    func: Callable,
    *args,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    jitter_max: float = 1.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    circuit_breaker: Optional[CircuitBreaker] = None,
    **kwargs,
) -> Any:
    last_exception = None

    for attempt in range(1, max_attempts + 1):
        if circuit_breaker and not circuit_breaker.can_execute():
            raise RuntimeError(
                f"CircuitBreaker [{circuit_breaker.name}] abierto. "
                f"Reintentando después del cooldown."
            )

        try:
            result = await func(*args, **kwargs)
            if circuit_breaker:
                circuit_breaker.record_success()
            return result

        except retryable_exceptions as exc:
            last_exception = exc
            if circuit_breaker:
                circuit_breaker.record_failure()

            if attempt == max_attempts:
                logger.error(
                    f"❌ async_retry: todos los {max_attempts} intentos fallaron. "
                    f"Último error: {exc}"
                )
                raise

            wait_time = min(base_delay * (backoff_factor ** (attempt - 1)), max_delay)
            wait_time += random.uniform(0, jitter_max)

            logger.warning(
                f"⚠️ Intento {attempt}/{max_attempts} falló: {exc}. "
                f"Reintentando en {wait_time:.2f}s..."
            )
            await asyncio.sleep(wait_time)

    raise last_exception


def retry_sync(
    max_attempts: int = 3,
    base_delay: float = 0.5,
    backoff_factor: float = 2.0,
    jitter_max: float = 0.5,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """Decorator para funciones síncronas."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        raise
                    wait = min(base_delay * (backoff_factor ** (attempt - 1)), 30.0)
                    wait += random.uniform(0, jitter_max)
                    logger.debug(f"retry_sync: intento {attempt} falló ({exc}), esperando {wait:.2f}s")
                    time.sleep(wait)
            raise last_exc
        return wrapper
    return decorator
