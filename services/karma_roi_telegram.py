# services/karma_roi_telegram.py
"""Envía reporte de Karma ROI a Telegram periódicamente."""

import logging
from services.karma_roi_tracker import get_roi_summary

logger = logging.getLogger("services.karma_roi_telegram")


def send_karma_roi_report(telegram_client, hours: int = 24) -> bool:
    """Envía reporte de Karma ROI a Telegram."""
    if not telegram_client or not getattr(telegram_client, "enabled", False):
        logger.debug("karma_roi_telegram: Telegram no habilitado")
        return False

    try:
        summary = get_roi_summary(hours)

        message = (
            f"📊 <b>KARMA ROI REPORT</b> ({hours}h)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>PHASE A (Posts)</b>\n"
            f"  📝 {summary['phase_a']['count']} posts\n"
            f"  💰 ${summary['phase_a']['total_cost']:.6f} USD\n"
            f"  ⭐ {summary['phase_a']['total_karma']} karma\n"
            f"  📈 {summary['phase_a']['karma_per_usd']:.2f} karma/USD\n"
            f"\n"
            f"<b>PHASE B (Comments)</b>\n"
            f"  💬 {summary['phase_b']['count']} comments\n"
            f"  💰 ${summary['phase_b']['total_cost']:.6f} USD\n"
            f"  ⭐ {summary['phase_b']['total_karma']} karma\n"
            f"  📈 {summary['phase_b']['karma_per_usd']:.2f} karma/USD\n"
            f"\n"
            f"<b>ROI Ratio (A/B): {summary['roi_ratio_a_vs_b']:.2f}x</b>\n"
            f"\n"
            f"💡 <i>{summary['recommendation']}</i>"
        )

        telegram_client.send_message(message)
        logger.info("karma_roi_telegram: Reporte enviado (%dh)", hours)
        return True
    except Exception as e:
        logger.warning("karma_roi_telegram: Error enviando reporte: %s", e)
        return False


def send_weekly_summary(telegram_client) -> bool:
    """Envía resumen semanal (168h) a Telegram."""
    return send_karma_roi_report(telegram_client, hours=168)


def send_daily_tokens_report(telegram_client, hours: int = 24) -> bool:
    """Envía reporte diario de tokens válidos vs desperdiciados a Telegram."""
    if not telegram_client or not getattr(telegram_client, "enabled", False):
        logger.debug("karma_roi_telegram: Telegram no habilitado para reporte de tokens")
        return False

    try:
        summary = get_roi_summary(hours)

        # Calcular tokens por acción (usando promedios de producción)
        phase_a_total = summary["phase_a"]["count"]
        phase_b_total = summary["phase_b"]["count"]
        total_comments = phase_a_total + phase_b_total

        # Tokens estimados por acción (promedios: ~2636 por post, ~1477 por comment)
        AVG_TOKENS_PER_POST = 2636
        AVG_TOKENS_PER_COMMENT = 1477

        tokens_validos = (phase_a_total * AVG_TOKENS_PER_POST) + (phase_b_total * AVG_TOKENS_PER_COMMENT)
        tokens_desperdiciados = 0  # TODO: obtener del tracker cuando esté implementado
        total_tokens = tokens_validos + tokens_desperdiciados
        total_cost = summary["phase_a"]["total_cost"] + summary["phase_b"]["total_cost"]
        eff = (tokens_validos / total_tokens * 100) if total_tokens > 0 else 0

        # Construir mensaje evitando anidación de comillas en f-strings
        lines = [
            "📊 REPORTE DIARIO DE TOKENS (" + str(hours) + "h)",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "",
            "📈 PRODUCCIÓN",
            "  📝 Posts: " + str(phase_a_total),
            "  💬 Comments: " + str(phase_b_total),
            "  🔢 Tokens válidos: " + str(tokens_validos),
            "",
            "⚠️ DESPERDICIADOS",
            "  🔢 Tokens: " + str(tokens_desperdiciados),
            "",
            "💰 COSTOS",
            "  Posts: $" + str(round(summary["phase_a"]["total_cost"], 6)) + " USD",
            "  Comments: $" + str(round(summary["phase_b"]["total_cost"], 6)) + " USD",
            "  <b>Total: $" + str(round(total_cost, 6)) + " USD</b>",
            "",
            "📊 RESUMEN",
            "  Total tokens: " + str(total_tokens),
            "  Eficiencia: " + str(round(eff, 1)) + "%",
            "",
            "<i>Generado: " + __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M") + "</i>",
        ]

        message = "\n".join(lines)

        telegram_client.send_message(message, parse_mode="HTML")
        logger.info("karma_roi_telegram: Reporte diario de tokens enviado (%dh)", hours)
        return True
    except Exception as e:
        logger.warning("karma_roi_telegram: Error enviando reporte de tokens: %s", e)
        return False