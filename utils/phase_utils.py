import functools
import inspect
import logging
import traceback
from typing import Any, Dict, List, Optional

from services.counters import incr

ERROR_METRICS: Dict[str, str] = {
    "phase_a": "phase_a_errors",
    "phase_b": "phase_b_errors",
    "phase_c_analytics": "phase_c_analytics_errors",
    "phase_c_engagement": "phase_c_engagement_errors",
}


def phase_error_boundary(
    logger: logging.Logger,
    phase_name: str,
    fallback_return: Any = None,
):
    if phase_name not in ERROR_METRICS:
        logger.warning("phase_error_boundary: unknown phase_name=%s, no metric will be incremented", phase_name)

    metric_name = ERROR_METRICS.get(phase_name)

    def decorator(func):
        is_coro = inspect.iscoroutinefunction(func)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                tb = traceback.format_exc()
                logger.error(
                    "phase_error_boundary [%s]: %s: %s\n%s",
                    phase_name,
                    type(e).__name__,
                    e,
                    "".join(tb.splitlines(keepends=True)[-6:]),
                )
                if metric_name:
                    incr(metric_name)
                if fallback_return is not None:
                    return fallback_return
                raise

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                tb = traceback.format_exc()
                logger.error(
                    "phase_error_boundary [%s]: %s: %s\n%s",
                    phase_name,
                    type(e).__name__,
                    e,
                    "".join(tb.splitlines(keepends=True)[-6:]),
                )
                if metric_name:
                    incr(metric_name)
                if fallback_return is not None:
                    return fallback_return
                raise

        return async_wrapper if is_coro else sync_wrapper

    return decorator


def validate_phase_deps(deps: Any, required_attrs: List[str]) -> None:
    for attr in required_attrs:
        if not hasattr(deps, attr):
            raise ValueError(
                f"PhaseDeps missing required attribute '{attr}'. "
                f"Ensure the deps dataclass includes this field."
            )
        val = getattr(deps, attr, None)
        if val is None:
            logger = logging.getLogger("utils.phase_utils")
            logger.warning("PhaseDeps attribute '%s' is None at init time", attr)
