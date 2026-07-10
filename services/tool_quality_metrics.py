"""KPI de calidad de tool calls (ATQS) basado en ToolResultReceipt.
Independiente — sin imports de COMET."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from services.tool_feedback import ToolOutcome, ToolResultReceipt


@dataclass
class ToolQualityWindow:
    total_calls: int = 0
    high_conf_calls: int = 0
    low_conf_calls: int = 0
    logical_failures: int = 0
    transport_failures: int = 0

    def atqs(self) -> Optional[float]:
        """Average Tool Quality Score = high_conf_calls / total_calls."""
        if self.total_calls == 0:
            return None
        return self.high_conf_calls / self.total_calls


def update_window(
    window: ToolQualityWindow,
    receipt: ToolResultReceipt,
    high_threshold: float = 0.75,
    low_threshold: float = 0.4,
) -> ToolQualityWindow:
    window.total_calls += 1

    if receipt.confidence_score is not None:
        if receipt.confidence_score >= high_threshold:
            window.high_conf_calls += 1
        if receipt.confidence_score < low_threshold:
            window.low_conf_calls += 1

    if receipt.outcome == ToolOutcome.LOGICAL_FAILURE:
        window.logical_failures += 1
    elif receipt.outcome == ToolOutcome.TRANSPORT_FAILURE:
        window.transport_failures += 1

    return window
