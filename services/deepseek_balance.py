# -*- coding: utf-8 -*-
"""DeepSeek balance checker — queries the API for remaining USD balance."""

import logging
import os
from datetime import date
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger("services.deepseek_balance")

_BALANCE_URL = "https://api.deepseek.com/user/balance"
_LAST_CHECK_FILE = Path("data/last_balance_check.txt")


def check_deepseek_balance() -> Optional[float]:
    """Query the DeepSeek API for the current USD balance.

    Returns the total balance in USD as a float, or None on failure.
    """
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        logger.warning("DeepSeek balance: no API key configured (DEEPSEEK_API_KEY)")
        return None

    try:
        response = requests.get(
            _BALANCE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if response.status_code != 200:
            logger.warning(
                "DeepSeek balance: HTTP %s — %s",
                response.status_code, response.text[:200],
            )
            return None

        data = response.json()
        balance_infos = data.get("balance_infos", [])
        for info in balance_infos:
            if info.get("currency", "").upper() == "USD":
                return float(info.get("total_balance", 0))

        # If no USD entry, try first entry
        if balance_infos:
            return float(balance_infos[0].get("total_balance", 0))

        logger.warning("DeepSeek balance: empty balance_infos in response")
        return None

    except requests.RequestException as e:
        logger.warning("DeepSeek balance: request failed — %s", e)
        return None
    except (ValueError, KeyError, TypeError) as e:
        logger.warning("DeepSeek balance: parse error — %s", e)
        return None


def was_balance_sent_today() -> bool:
    """Check if the daily balance notification was already sent today."""
    try:
        if _LAST_CHECK_FILE.exists():
            last_date = _LAST_CHECK_FILE.read_text(encoding="utf-8").strip()
            return last_date == str(date.today())
    except Exception:
        pass
    return False


def mark_balance_sent() -> None:
    """Record that the daily balance notification was sent."""
    try:
        _LAST_CHECK_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LAST_CHECK_FILE.write_text(str(date.today()), encoding="utf-8")
    except Exception as e:
        logger.warning("Could not persist balance check timestamp: %s", e)


def format_balance_message(balance: float, cycle: int) -> str:
    """Format the Telegram balance notification message."""
    today_str = str(date.today())
    lines = [
        f"💰 <b>DeepSeek Balance:</b> ${balance:.2f} USD",
        f"📅 Fecha: {today_str}",
        f"🔄 Ciclo: #{cycle}",
    ]
    if balance < 2.0:
        lines.append("⚠️ <b>SALDO BAJO — recargar recomendado</b>")
    return "\n".join(lines)
