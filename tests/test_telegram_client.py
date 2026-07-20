import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from services.telegram_client import TelegramClient


@pytest.fixture
def client():
    return TelegramClient(bot_token="fake", chat_id="123", enabled=True)


def _make_update(text: str, chat_id: str = "123") -> dict:
    return {
        "message": {
            "chat": {"id": chat_id},
            "text": text,
            "date": int(time.time()),
            "message_id": 1,
        }
    }


# ── Caso A: comando /status ─────────────────────────────────

class TestStatusCommand:

    @pytest.mark.asyncio
    async def test_sends_status_with_cycle_and_outbox_count(self, client):
        client.send_message = MagicMock()
        agent = MagicMock()
        agent.cycle_count = 42
        agent.posts_today = 5

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = [3]

        with patch("services.persistence.get_conn") as mock_get:
            mock_get.return_value.__enter__.return_value = mock_conn
            await client._handle_status(agent)

        sent = client.send_message.call_args[0][0]
        assert "42" in sent
        assert "5" in sent
        assert "3" in sent
        assert "Estado" in sent

    @pytest.mark.asyncio
    async def test_status_handles_db_failure_gracefully(self, client):
        client.send_message = MagicMock()
        agent = MagicMock()
        agent.cycle_count = 1
        agent.posts_today = 0

        with patch("services.persistence.get_conn") as mock_get:
            mock_get.side_effect = RuntimeError("DB unavailable")
            await client._handle_status(agent)

        sent = client.send_message.call_args[0][0]
        assert "0" in sent or "1" in sent


# ── Caso B: comando /health (vía routing extendido) ──────────

class TestHealthCommand:

    @pytest.mark.asyncio
    async def test_health_routes_to_telegram_control(self, client):
        client.send_message = MagicMock()
        agent = MagicMock()

        with patch(
            "services.telegram_control.handle_command",
            return_value="🔧 **Health Check:**\n  Cycle: 10",
        ) as mock_handle:
            await client._process_update(agent, _make_update("/health"))

        mock_handle.assert_called_once_with("/health", agent=agent)
        sent = client.send_message.call_args[0][0]
        assert "Health Check" in sent

    @pytest.mark.asyncio
    async def test_health_without_agent_shows_partial(self, client):
        client.send_message = MagicMock()

        with patch(
            "services.telegram_control.handle_command",
            return_value="🔧 **Health Check:**\n  State: unavailable",
        ):
            await client._process_update(None, _make_update("/health"))

        sent = client.send_message.call_args[0][0]
        assert "Health Check" in sent

    @pytest.mark.asyncio
    async def test_health_routing_error_logged(self, client, caplog):
        client.send_message = MagicMock()
        agent = MagicMock()
        import logging
        caplog.set_level(logging.WARNING)

        with patch(
            "services.telegram_control.handle_command",
            side_effect=ValueError("unexpected"),
        ):
            await client._process_update(agent, _make_update("/health"))

        assert "unexpected" in caplog.text
        client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_health_ignores_wrong_chat(self, client):
        client.send_message = MagicMock()
        agent = MagicMock()

        await client._process_update(agent, _make_update("/health", chat_id="999"))
        client.send_message.assert_not_called()


# ── /status vía routing completo ────────────────────────────

class TestStatusRouting:

    @pytest.mark.asyncio
    async def test_status_routes_and_responds(self, client):
        client.send_message = MagicMock()
        agent = MagicMock()
        agent.cycle_count = 7
        agent.posts_today = 2

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = [0]

        with patch("services.persistence.get_conn") as mock_get:
            mock_get.return_value.__enter__.return_value = mock_conn
            await client._process_update(agent, _make_update("/status"))

        sent = client.send_message.call_args[0][0]
        assert "7" in sent
