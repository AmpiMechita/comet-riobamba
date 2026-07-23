"""Tests for services/model_cascade.py — critical path with zero prior coverage."""

import logging
import pytest

try:
    import requests
except ImportError:
    requests = None  # type: ignore[no-redef]

from unittest.mock import MagicMock, patch, PropertyMock
from services.model_cascade import ModelCascade, ProviderConfig
from config.credentials import Credentials
from utils.resilience import CircuitBreaker


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def mock_credentials():
    c = MagicMock(spec=Credentials)
    c.ollama_url = "http://localhost:11434/v1"
    c.ollama_model = "qwen2.5:1.5b"
    c.ollama_timeout = 60
    c.ollama_cloud_model = None
    c.tier_opus = None
    c.tier_sonnet = None
    c.tier_haiku = None
    c.tier_openrouter = None
    c.cerebras_api_key = ""
    return c


@pytest.fixture
def cascade(mock_credentials):
    with patch("services.model_cascade.Credentials.from_env", return_value=mock_credentials):
        c = ModelCascade()
    # Clear providers so we have a clean slate for testing
    c.providers = []
    c.circuit_breakers = {}
    c._append_telemetry_jsonl = lambda record: None  # suppress disk I/O in existing tests
    return c


def _add_provider(cascade, name, enabled=True, model="test-model", url="http://test.local", paid=False):
    p = ProviderConfig(name=name, url=url, model=model, enabled=enabled, paid=paid)
    cascade.providers.append(p)
    cascade.circuit_breakers[name] = CircuitBreaker(
        name=f"model_cascade.{name}",
        failure_threshold=3,
        recovery_timeout=60,
    )


# ── Tier mapping ─────────────────────────────────────────────────


@pytest.mark.parametrize("tier,expected", [
    ("default", "ollama_local"),
    ("openrouter", "openrouter"),
    ("premium", "tier_premium"),
    ("fallback", "tier_fallback"),
    ("opus", "tier_premium"),   # legacy alias
    ("haiku", "tier_fallback"),  # legacy alias
])
def test_tier_mapping(tier, expected):
    assert ModelCascade.TIER_MAPPING.get(tier) == expected


# ── Provider selection ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_preferred_tier_is_tried_first(cascade):
    _add_provider(cascade, "ollama_local", model="local")
    _add_provider(cascade, "openrouter", model="remote")

    with (
        patch.object(cascade, "_call_with_retries", return_value="ok"),
        patch.object(cascade, "_is_circuit_open", return_value=False),
    ):
        result = await cascade.generate(prompt="hello", tier="openrouter")
        assert result == "ok"


@pytest.mark.asyncio
async def test_disabled_provider_is_skipped(cascade):
    _add_provider(cascade, "ollama_local", enabled=False)
    _add_provider(cascade, "openrouter", enabled=True, model="remote")

    with (
        patch.object(cascade, "_call_with_retries", return_value="ok"),
        patch.object(cascade, "_is_circuit_open", return_value=False),
    ):
        result = await cascade.generate(prompt="hello", tier="openrouter")
        assert result == "ok"


# ── Fallback ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fallback_to_next_provider_on_failure(cascade):
    _add_provider(cascade, "primary", model="p1")
    _add_provider(cascade, "backup", model="p2")

    call_count = 0

    async def _call(provider, messages, max_tokens, temperature):
        nonlocal call_count
        call_count += 1
        if provider.name == "primary":
            raise RuntimeError("primary failed")
        return "fallback_ok"

    with patch.object(cascade, "_is_circuit_open", return_value=False):
        with patch.object(cascade, "_call_with_retries", side_effect=_call):
            result = await cascade.generate(prompt="hello")
            assert result == "fallback_ok"
            assert call_count == 2  # primary then backup


@pytest.mark.asyncio
async def test_fallback_prefers_free_providers_over_paid(cascade):
    """Si el tier pedido (pago) falla, el fallback prueba gratis antes que pago.

    Reproduce el ciclo real del 22/7/2026: tier_fallback (DeepSeek) devolvio
    HTTP 402 y el cascade degrado directo a tier_premium (Anthropic pago) sin
    probar ninguno de los gratis, solo por orden de registro.
    """
    _add_provider(cascade, "tier_premium", paid=True)   # registrado primero, como en _load_providers
    _add_provider(cascade, "tier_sonnet")
    _add_provider(cascade, "openrouter")
    _add_provider(cascade, "tier_fallback", paid=True)

    attempted = []

    async def _call(provider, messages, max_tokens, temperature):
        attempted.append(provider.name)
        if provider.name == "tier_fallback":
            raise RuntimeError("HTTP 402 desde tier_fallback - Insufficient Balance")
        return "ok"

    with patch.object(cascade, "_is_circuit_open", return_value=False):
        with patch.object(cascade, "_call_with_retries", side_effect=_call):
            result = await cascade.generate(prompt="hello", tier="fallback")

    assert result == "ok"
    # 1ro el preferido (tier_fallback), 2do un GRATIS — no tier_premium.
    assert attempted[0] == "tier_fallback"
    assert attempted[1] == "tier_sonnet", f"orden real: {attempted}"
    assert "tier_premium" not in attempted, f"no debia llegar al pago: {attempted}"


@pytest.mark.asyncio
async def test_fallback_order_unchanged_without_paid_providers(cascade):
    """Control: sin proveedores pagos, el reorden no altera el orden de registro."""
    _add_provider(cascade, "tier_sonnet")
    _add_provider(cascade, "openrouter")
    _add_provider(cascade, "cloudflare")

    attempted = []

    async def _call(provider, messages, max_tokens, temperature):
        attempted.append(provider.name)
        raise RuntimeError("fail all")

    with patch.object(cascade, "_is_circuit_open", return_value=False):
        with patch.object(cascade, "_call_with_retries", side_effect=_call):
            with pytest.raises(RuntimeError, match="Todos los proveedores fallaron"):
                await cascade.generate(prompt="hello", tier="sonnet")

    assert attempted == ["tier_sonnet", "openrouter", "cloudflare"]


@pytest.mark.asyncio
async def test_all_providers_fail_raises_error(cascade):
    _add_provider(cascade, "p1", model="p1")
    _add_provider(cascade, "p2", model="p2")

    with patch.object(cascade, "_is_circuit_open", return_value=False):
        with patch.object(cascade, "_call_with_retries", side_effect=RuntimeError("fail")):
            with pytest.raises(RuntimeError, match="Todos los proveedores fallaron"):
                await cascade.generate(prompt="hello")


@pytest.mark.asyncio
async def test_empty_response_triggers_fallback(cascade):
    _add_provider(cascade, "p1", model="p1")
    _add_provider(cascade, "p2", model="p2")

    call_count = 0

    async def _call(provider, messages, max_tokens, temperature):
        nonlocal call_count
        call_count += 1
        if provider.name == "p1":
            return ""
        return "ok_from_p2"

    with patch.object(cascade, "_is_circuit_open", return_value=False):
        with patch.object(cascade, "_call_with_retries", side_effect=_call):
            result = await cascade.generate(prompt="hello")
            assert result == "ok_from_p2"
            assert call_count == 2


# ── Circuit breaker awareness ────────────────────────────────────


@pytest.mark.asyncio
async def test_skips_provider_with_open_circuit(cascade):
    _add_provider(cascade, "broken", model="b")
    _add_provider(cascade, "working", model="w")

    cascade.circuit_breakers["broken"].force_open()

    with (
        patch.object(cascade, "_call_with_retries", return_value="ok_from_working"),
    ):
        result = await cascade.generate(prompt="hello", tier="default")
        assert result == "ok_from_working"


# ── Error classification ─────────────────────────────────────────


@pytest.mark.parametrize("error_msg,expected_type", [
    ("HTTP 429 Too Many Requests", "rate_limit"),
    ("http 429", "rate_limit"),
    ("rate limit exceeded", "rate_limit"),
    ("HTTP 401 Unauthorized", "client"),
    ("HTTP 403 Forbidden", "client"),
    ("HTTP 400 Bad Request", "client"),
    ("HTTP 500 Internal Server Error", "server"),
    ("HTTP 502 Bad Gateway", "server"),
    ("Connection timed out", "network"),
    ("connection aborted", "network"),
    ("random error", "unknown"),
])
def test_classify_http_error(cascade, error_msg, expected_type):
    exc = RuntimeError(error_msg)
    assert cascade._classify_http_error(exc) == expected_type


# ── Should retry ─────────────────────────────────────────────────


@pytest.mark.parametrize("error_msg,expected", [
    ("timeout", True),
    ("timed out", True),
    ("Connection aborted", True),
    ("HTTP 429", False),
    ("HTTP 503", True),
    ("HTTP 400", False),
    ("HTTP 401", False),
    ("HTTP 403", False),
    ("respuesta sin choices", False),
    ("respuesta sin content utilizable", False),
])
def test_should_retry(cascade, error_msg, expected):
    exc = RuntimeError(error_msg)
    assert cascade._should_retry(exc) is expected


def test_should_retry_requests_exceptions(cascade):
    if requests is None:
        pytest.skip("requests not installed")
    assert cascade._should_retry(requests.Timeout("timed out")) is True
    assert cascade._should_retry(requests.ConnectionError("connection error")) is True


# ── Record failure with rate-limit awareness ─────────────────────


def test_record_failure_rate_limit_opens_circuit_for_one_hour(cascade):
    _add_provider(cascade, "test_provider")
    cb = cascade.circuit_breakers["test_provider"]
    assert cb.can_execute()

    cascade._record_failure(cascade.providers[0], RuntimeError("HTTP 429 Too Many"))
    
    # El circuito debe estar cerrado porque lo forzamos a abrir por 3600s
    assert not cb.can_execute(), "rate limit should force_open circuit for 1 hour"


def test_record_failure_client_error_opens_circuit_immediately(cascade):
    _add_provider(cascade, "test_provider")
    cb = cascade.circuit_breakers["test_provider"]
    assert cb.can_execute()

    cascade._record_failure(cascade.providers[0], RuntimeError("HTTP 401 Unauthorized"))
    assert not cb.can_execute(), "client error SHOULD open circuit"


def test_record_failure_server_error_counts_normally(cascade):
    _add_provider(cascade, "test_provider")
    cb = cascade.circuit_breakers["test_provider"]
    assert cb.can_execute()

    for i in range(3):
        assert cb.can_execute(), f"should still be closed after {i+1} failures"
        cascade._record_failure(cascade.providers[0], RuntimeError("HTTP 502 Bad Gateway"))

    assert not cb.can_execute(), "circuit should open after threshold failures"


# ── Build messages ───────────────────────────────────────────────


def test_build_messages_with_system_prompt(cascade):
    msgs = cascade._build_messages(prompt="hi", system_prompt="sys")
    assert len(msgs) == 2
    assert msgs[0] == {"role": "system", "content": "sys"}
    assert msgs[1] == {"role": "user", "content": "hi"}


def test_build_messages_without_system_prompt(cascade):
    msgs = cascade._build_messages(prompt="hi", system_prompt=None)
    assert len(msgs) == 1
    assert msgs[0] == {"role": "user", "content": "hi"}


# ── Telemetry tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_success_logs_debug_telemetry(cascade, caplog):
    """a. Successful call → DEBUG log with provider, tier, latency, success=true, caller."""
    _add_provider(cascade, "test_prov", model="m1")
    caplog.set_level(logging.DEBUG)

    with (
        patch.object(cascade, "_call_with_retries", return_value="ok"),
        patch.object(cascade, "_is_circuit_open", return_value=False),
    ):
        result = await cascade.generate(prompt="hello", tier="default")

    assert result == "ok"
    debug_msgs = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
    telemetry_line = next((m for m in debug_msgs if "ModelCascade: provider=test_prov" in m), None)
    assert telemetry_line is not None, f"No DEBUG telemetry found in: {debug_msgs}"
    assert "latency=" in telemetry_line
    assert "success=true" in telemetry_line
    assert "caller=unknown" in telemetry_line


@pytest.mark.asyncio
async def test_failure_logs_failed_reason(cascade, caplog):
    """b. Failed call → FAILED log + fallback to next provider."""
    _add_provider(cascade, "primary", model="p1")
    _add_provider(cascade, "backup", model="p2")
    caplog.set_level(logging.WARNING)

    async def _call(provider, messages, max_tokens, temperature):
        if provider.name == "primary":
            raise RuntimeError("HTTP 500 Internal Server Error")
        return "backup_ok"

    with patch.object(cascade, "_is_circuit_open", return_value=False):
        with patch.object(cascade, "_call_with_retries", side_effect=_call):
            result = await cascade.generate(prompt="hello")

    assert result == "backup_ok"
    failed_msgs = [r.message for r in caplog.records if "FAILED" in r.message]
    assert len(failed_msgs) >= 1
    assert "ModelCascade: provider=primary FAILED reason=server" in failed_msgs[0]


@pytest.mark.asyncio
async def test_telemetry_jsonl_written_with_correct_fields(cascade):
    """c. cascade_telemetry.jsonl written with correct fields on success."""
    records = []

    def capture_record(record):
        records.append(record)

    _add_provider(cascade, "test_prov", model="m1")

    with (
        patch.object(cascade, "_call_with_retries", return_value="ok"),
        patch.object(cascade, "_is_circuit_open", return_value=False),
        patch.object(cascade, "_append_telemetry_jsonl", side_effect=capture_record),
    ):
        await cascade.generate(prompt="hello", tier="default")

    assert len(records) == 1
    rec = records[0]
    assert rec["caller"] == "unknown"
    assert rec["provider"] == "test_prov"
    assert rec["tier"] == "default"
    assert isinstance(rec["latency_ms"], int)
    assert rec["success"] is True
    assert rec["error"] is None
    assert "ts" in rec
    # Must NOT have token fields (not in spec)
    assert "tokens_in" not in rec
    assert "tokens_out" not in rec


@pytest.mark.asyncio
async def test_telemetry_jsonl_written_on_failure(cascade):
    """c. cascade_telemetry.jsonl written with error on failure."""
    records = []

    def capture_record(record):
        records.append(record)

    _add_provider(cascade, "failing", model="f1")
    _add_provider(cascade, "backup", model="b1")

    async def _call(provider, messages, max_tokens, temperature):
        if provider.name == "failing":
            raise RuntimeError("HTTP 502 Bad Gateway")
        return "ok"

    with (
        patch.object(cascade, "_is_circuit_open", return_value=False),
        patch.object(cascade, "_call_with_retries", side_effect=_call),
        patch.object(cascade, "_append_telemetry_jsonl", side_effect=capture_record),
    ):
        await cascade.generate(prompt="hello")

    assert len(records) == 2  # failure record + success record
    fail_record = records[0]
    assert fail_record["provider"] == "failing"
    assert fail_record["success"] is False
    assert fail_record["error"] == "server"

    success_record = records[1]
    assert success_record["provider"] == "backup"
    assert success_record["success"] is True
    assert success_record["error"] is None


@pytest.mark.asyncio
async def test_telemetry_jsonl_write_failure_logs_warning(cascade, caplog):
    """d. cascade_telemetry.jsonl write failure → WARNING, no crash."""
    # Restore real _append_telemetry_jsonl but point to an unwritable path
    del cascade._append_telemetry_jsonl
    cascade._telemetry_file = "\0"  # null byte causes OSError on Windows
    _add_provider(cascade, "p1", model="m1")
    caplog.set_level(logging.WARNING)

    with (
        patch.object(cascade, "_call_with_retries", return_value="ok"),
        patch.object(cascade, "_is_circuit_open", return_value=False),
    ):
        result = await cascade.generate(prompt="hello")

    assert result == "ok"  # must not crash
    warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("failed to write telemetry" in m.lower() for m in warning_msgs)


@pytest.mark.asyncio
async def test_health_score_10_success_equals_1_0(cascade):
    """e. health_score = 1.0 after 10 consecutive successes."""
    _add_provider(cascade, "p1", model="m1")
    for _ in range(10):
        cascade._update_health(cascade.providers[0], True)
    assert cascade._get_health_score(cascade.providers[0]) == 1.0


@pytest.mark.asyncio
async def test_health_score_5_success_5_failure_equals_0_5(cascade):
    """f. health_score = 0.5 after 5 successes + 5 failures."""
    _add_provider(cascade, "p1", model="m1")
    for _ in range(5):
        cascade._update_health(cascade.providers[0], True)
    for _ in range(5):
        cascade._update_health(cascade.providers[0], False)
    assert cascade._get_health_score(cascade.providers[0]) == 0.5


@pytest.mark.asyncio
async def test_get_provider_health_empty_before_any_calls(cascade):
    """g. get_provider_health() returns empty dict before any calls."""
    assert cascade.get_provider_health() == {}


@pytest.mark.asyncio
async def test_get_provider_health_returns_correct_scores(cascade):
    """g. get_provider_health() returns correct scores for all seen providers."""
    _add_provider(cascade, "p1", model="m1")
    _add_provider(cascade, "p2", model="m2")

    for _ in range(8):
        cascade._update_health(cascade.providers[0], True)
    for _ in range(2):
        cascade._update_health(cascade.providers[0], False)
    cascade._update_health(cascade.providers[1], True)

    result = cascade.get_provider_health()
    assert result["p1"] == 0.8
    assert result["p2"] == 1.0


@pytest.mark.asyncio
async def test_health_rolling_window_drops_oldest(cascade):
    """h. Rolling window: oldest call dropped after 11th call (deque maxlen=10)."""
    _add_provider(cascade, "p1", model="m1")
    for _ in range(10):
        cascade._update_health(cascade.providers[0], True)
    assert cascade._get_health_score(cascade.providers[0]) == 1.0

    # 11th call pushes out oldest (True)
    cascade._update_health(cascade.providers[0], False)
    assert cascade._get_health_score(cascade.providers[0]) == 0.9


@pytest.mark.asyncio
async def test_caller_field_defaults_to_unknown(cascade):
    """h. caller defaults to 'unknown' when not passed."""
    records = []

    def capture_record(record):
        records.append(record)

    _add_provider(cascade, "p1", model="m1")

    with (
        patch.object(cascade, "_call_with_retries", return_value="ok"),
        patch.object(cascade, "_is_circuit_open", return_value=False),
        patch.object(cascade, "_append_telemetry_jsonl", side_effect=capture_record),
    ):
        await cascade.generate(prompt="hello")

    assert len(records) == 1
    assert records[0]["caller"] == "unknown"


# ── Retry backoff ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retry_backoff_waits_increase_between_attempts(cascade):
    """Verifica que el tiempo de espera entre reintentos crece con cada intento."""
    _add_provider(cascade, "p1", model="m1")
    cascade.providers[0].max_retries = 2  # 3 total attempts

    sleep_durations = []

    async def fake_sleep(duration):
        sleep_durations.append(duration)

    call_count = 0

    def fake_call(provider, messages, max_tokens, temperature):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RuntimeError("HTTP 500 Internal Server Error")
        return "third_time_ok"

    with (
        patch.object(cascade, "_call_provider_once", side_effect=fake_call),
        patch("asyncio.sleep", side_effect=fake_sleep),
        patch.object(cascade, "_is_circuit_open", return_value=False),
    ):
        result = await cascade.generate(prompt="hello")

    assert result == "third_time_ok"
    assert len(sleep_durations) == 2
    assert sleep_durations[1] >= sleep_durations[0], "backoff must be non-decreasing"


# ── kwargs aliases ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_accepts_maxtokens_alias(cascade):
    """Verifica que generate() acepta 'maxtokens' como alias de max_tokens."""
    _add_provider(cascade, "p1", model="m1")

    with (
        patch.object(cascade, "_call_with_retries", return_value="ok"),
        patch.object(cascade, "_is_circuit_open", return_value=False),
    ):
        result = await cascade.generate(prompt="test", maxtokens=500)

    assert result == "ok"


@pytest.mark.asyncio
async def test_generate_accepts_systemprompt_kwarg(cascade):
    """Verifica que generate() acepta 'systemprompt' en kwargs."""
    _add_provider(cascade, "p1", model="m1")

    with (
        patch.object(cascade, "_call_with_retries", return_value="ok"),
        patch.object(cascade, "_is_circuit_open", return_value=False),
    ):
        result = await cascade.generate(prompt="test", systemprompt="You are an engineer")

    assert result == "ok"


# ── Anthropic (Claude 3.5 Sonnet) integration ──────────────────────


def _anthropic_provider():
    return ProviderConfig(
        name="tier_premium",
        url="https://api.anthropic.com/v1/messages",
        model="claude-sonnet-5",
        api_key="sk-ant-test",
        timeout=120,
        kind="anthropic",
    )


def test_anthropic_provider_kind_routes_to_anthropic(cascade):
    """_call_provider_once must delegate anthropic-kind providers to _call_anthropic."""
    prov = _anthropic_provider()
    messages = [{"role": "user", "content": "hi"}]
    with patch.object(cascade, "_call_anthropic", return_value="claude-out") as mock_call:
        result = cascade._call_provider_once(prov, messages, max_tokens=100, temperature=0.5)
    assert result == "claude-out"
    mock_call.assert_called_once()


def test_anthropic_sdk_path_maps_system_and_messages(cascade):
    """SDK path: system prompt goes to `system`, only user/assistant in messages,
    and the response content blocks are mapped to plain text."""
    prov = _anthropic_provider()
    messages = [
        {"role": "system", "content": "You are terse."},
        {"role": "user", "content": "explain backpressure"},
    ]

    fake_anthropic = MagicMock()
    fake_client = fake_anthropic.Anthropic.return_value
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "SDK reply"
    fake_client.messages.create.return_value = MagicMock(content=[text_block])

    with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
        out = cascade._call_anthropic(prov, messages, max_tokens=256, temperature=0.3)

    assert out == "SDK reply"
    call_kwargs = fake_client.messages.create.call_args.kwargs
    assert call_kwargs["system"] == "You are terse."
    assert call_kwargs["model"] == "claude-sonnet-5"
    assert [m["role"] for m in call_kwargs["messages"]] == ["user"]
    # Regression guard: claude-sonnet-5 rejects `temperature` (HTTP 400). It must
    # NOT be sent on the Anthropic SDK path.
    assert "temperature" not in call_kwargs


def test_anthropic_http_fallback_when_sdk_missing(cascade):
    """When the anthropic SDK is not installed, fall back to the HTTP Messages API
    with the required x-api-key + anthropic-version headers and system at top level."""
    prov = _anthropic_provider()
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q"},
    ]

    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("no anthropic")
        return real_import(name, *args, **kwargs)

    resp = MagicMock()
    resp.raise_for_status = lambda: None
    resp.json = lambda: {"content": [{"type": "text", "text": "HTTP reply"}]}

    with patch("builtins.__import__", side_effect=fake_import):
        with patch("services.model_cascade.requests.post", return_value=resp) as mock_post:
            out = cascade._call_anthropic(prov, messages, max_tokens=128, temperature=0.4)

    assert out == "HTTP reply"
    kwargs = mock_post.call_args.kwargs
    assert kwargs["headers"]["x-api-key"] == "sk-ant-test"
    assert kwargs["headers"]["anthropic-version"] == "2023-06-01"
    assert kwargs["json"]["system"] == "sys"
    assert [m["role"] for m in kwargs["json"]["messages"]] == ["user"]
    # Regression guard: `temperature` must NOT be in the HTTP payload either.
    assert "temperature" not in kwargs["json"]


def test_extract_anthropic_text_from_dict():
    """Dict-shaped Anthropic responses map to concatenated text blocks."""
    resp = {"content": [
        {"type": "text", "text": "Hello "},
        {"type": "text", "text": "world"},
    ]}
    prov = _anthropic_provider()
    assert ModelCascade._extract_anthropic_text(resp, prov) == "Hello world"


def test_extract_anthropic_text_empty_raises():
    """Empty Anthropic content must raise (mapped to a cascade failure)."""
    prov = _anthropic_provider()
    with pytest.raises(RuntimeError, match="sin content utilizable"):
        ModelCascade._extract_anthropic_text({"content": []}, prov)


# ── Credential wiring: ANTHROPIC_API_KEY → tier_premium, DEEPSEEK → tier_fallback ──


def _full_credentials(anthropic_key="sk-ant-real", deepseek_key="sk-ds-real"):
    c = MagicMock(spec=Credentials)
    c.ollama_url = "http://localhost:11434/v1"
    c.ollama_model = "qwen2.5:1.5b"
    c.ollama_timeout = 60
    c.ollama_cloud_model = None
    c.tier_opus = None
    c.tier_sonnet = None
    c.tier_haiku = None
    c.tier_openrouter = None
    c.cerebras_api_key = ""
    c.groq_api_key = ""
    c.anthropic_api_key = anthropic_key
    c.anthropic_url = "https://api.anthropic.com/v1/messages"
    c.anthropic_model = "claude-sonnet-5"
    c.anthropic_timeout = 120
    c.deepseek_api_key = deepseek_key
    c.deepseek_url = "https://api.deepseek.com/v1/chat/completions"
    c.deepseek_model = "deepseek-v4-pro"
    c.deepseek_timeout = 90
    return c


def test_anthropic_key_wires_tier_premium_and_deepseek_wires_tier_fallback():
    """ANTHROPIC_API_KEY → tier_premium (anthropic/claude); DEEPSEEK_API_KEY → tier_fallback."""
    creds = _full_credentials()
    mc = ModelCascade(credentials=creds)

    premium = next(p for p in mc.providers if p.name == "tier_premium")
    assert premium.kind == "anthropic"
    assert premium.model == "claude-sonnet-5"
    assert premium.api_key == "sk-ant-real"

    fallback = next(p for p in mc.providers if p.name == "tier_fallback")
    assert fallback.model == "deepseek-v4-pro"
    assert fallback.api_key == "sk-ds-real"


def test_missing_anthropic_key_logs_critical_warning(caplog):
    """Missing ANTHROPIC_API_KEY must emit the documented critical WARNING."""
    creds = _full_credentials(anthropic_key="")
    with caplog.at_level(logging.WARNING, logger="services.model_cascade"):
        ModelCascade(credentials=creds)
    assert any(
        "Falta ANTHROPIC_API_KEY en .env" in r.message
        and "Claude 3.5 Sonnet" in r.message
        for r in caplog.records
    ), f"Expected critical ANTHROPIC_API_KEY warning, got: {[r.message for r in caplog.records]}"


# ── DeepSeek thinking-disable isolation ────────────────────────────


def _capture_openai_payload(cascade, provider):
    """Run _call_provider_once against a stubbed requests.post and return the
    JSON payload that would be sent to the OpenAI-compatible endpoint."""
    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    def _fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return _Resp()

    messages = [{"role": "user", "content": "hi"}]
    with patch("services.model_cascade.requests.post", side_effect=_fake_post):
        cascade._call_provider_once(provider, messages, max_tokens=100, temperature=0.5)
    return captured["payload"]


def test_deepseek_payload_disables_thinking_and_floors_max_tokens(cascade):
    """tier_fallback (DeepSeek) must send thinking:disabled and floor max_tokens to 2048."""
    prov = ProviderConfig(
        name="tier_fallback",
        url="https://api.deepseek.com/v1/chat/completions",
        model="deepseek-v4-pro",
        api_key="sk-ds",
    )
    payload = _capture_openai_payload(cascade, prov)
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["max_tokens"] == 2048  # floored up from 100


def test_deepseek_detected_by_model_name_even_if_provider_name_differs(cascade):
    """Detection also works via 'deepseek' in url/model, not only provider name."""
    prov = ProviderConfig(
        name="some_other_name",
        url="https://api.deepseek.com/v1/chat/completions",
        model="deepseek-v4-pro",
        api_key="sk-ds",
    )
    payload = _capture_openai_payload(cascade, prov)
    assert payload["thinking"] == {"type": "disabled"}


def test_cerebras_payload_does_not_disable_thinking(cascade):
    """Cerebras (OpenAI-compatible, non-DeepSeek) must NOT get the thinking flag."""
    prov = ProviderConfig(
        name="cerebras",
        url="https://api.cerebras.ai/v1/chat/completions",
        model="llama-3.3-70b",
        api_key="csk",
    )
    payload = _capture_openai_payload(cascade, prov)
    assert "thinking" not in payload
    assert payload["max_tokens"] == 100  # untouched


def test_groq_payload_does_not_disable_thinking(cascade):
    """Groq (OpenAI-compatible, non-DeepSeek) must NOT get the thinking flag."""
    prov = ProviderConfig(
        name="groq",
        url="https://api.groq.com/openai/v1/chat/completions",
        model="llama-3.3-70b-versatile",
        api_key="gsk",
    )
    payload = _capture_openai_payload(cascade, prov)
    assert "thinking" not in payload
    assert payload["max_tokens"] == 100  # untouched


# ── Silent tier-fallback visibility warning ────────────────────────

_FALLBACK_WARN_MARKER = "no resuelve a un provider registrado/habilitado"


@pytest.mark.asyncio
async def test_unresolved_tier_logs_fallback_warning(cascade, caplog):
    """A tier that maps to an unregistered provider (e.g. tier='default' →
    ollama_local with OLLAMA_ENABLED off) must emit a WARNING naming the
    requested tier and the fallback provider actually used."""
    # tier_premium is registered; ollama_local (the target of 'default') is NOT.
    _add_provider(cascade, "tier_premium", model="claude-sonnet-5")
    _add_provider(cascade, "tier_fallback", model="deepseek-v4-pro")
    caplog.set_level(logging.WARNING)

    with (
        patch.object(cascade, "_call_with_retries", return_value="ok"),
        patch.object(cascade, "_is_circuit_open", return_value=False),
    ):
        result = await cascade.generate(prompt="hello", tier="default")

    assert result == "ok"
    warn_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    fallback_line = next((m for m in warn_msgs if _FALLBACK_WARN_MARKER in m), None)
    assert fallback_line is not None, f"No fallback WARNING found in: {warn_msgs}"
    # Must name the requested tier and the fallback provider actually used.
    assert "'default'" in fallback_line
    assert "tier_premium" in fallback_line


@pytest.mark.asyncio
async def test_resolved_tier_premium_does_not_log_fallback_warning(cascade, caplog):
    """tier='premium' resolves to a registered provider → no fallback WARNING."""
    _add_provider(cascade, "tier_premium", model="claude-sonnet-5")
    _add_provider(cascade, "tier_fallback", model="deepseek-v4-pro")
    caplog.set_level(logging.WARNING)

    with (
        patch.object(cascade, "_call_with_retries", return_value="ok"),
        patch.object(cascade, "_is_circuit_open", return_value=False),
    ):
        result = await cascade.generate(prompt="hello", tier="premium")

    assert result == "ok"
    assert not any(_FALLBACK_WARN_MARKER in r.message for r in caplog.records), \
        "tier='premium' resolves directly and must NOT emit the fallback WARNING"


@pytest.mark.asyncio
async def test_resolved_tier_fallback_does_not_log_fallback_warning(cascade, caplog):
    """tier='fallback' resolves to a registered provider → no fallback WARNING."""
    _add_provider(cascade, "tier_premium", model="claude-sonnet-5")
    _add_provider(cascade, "tier_fallback", model="deepseek-v4-pro")
    caplog.set_level(logging.WARNING)

    with (
        patch.object(cascade, "_call_with_retries", return_value="ok"),
        patch.object(cascade, "_is_circuit_open", return_value=False),
    ):
        result = await cascade.generate(prompt="hello", tier="fallback")

    assert result == "ok"
    assert not any(_FALLBACK_WARN_MARKER in r.message for r in caplog.records), \
        "tier='fallback' resolves directly and must NOT emit the fallback WARNING"


# ── Alerta de circuit breaker OPEN (_alert_circuit_open) ─────────


def test_alert_circuit_open_sends_alert_with_provider_name(cascade):
    """Con telegram habilitado, la alerta nombra al proveedor que quedó OPEN."""
    _add_provider(cascade, "prov_a")
    _add_provider(cascade, "prov_b")
    telegram = MagicMock()
    telegram.enabled = True

    with patch.object(cascade, "_get_telegram_client", return_value=telegram):
        cascade._alert_circuit_open("model_cascade.prov_a")

    telegram.send_alert.assert_called_once()
    title, message = telegram.send_alert.call_args.args[:2]
    assert title == "Proveedor fuera de rotación"
    assert "'prov_a'" in message
    assert "/2 proveedores" in message
    assert telegram.send_alert.call_args.kwargs["level"] == "WARNING"


def test_alert_circuit_open_noop_without_telegram(cascade):
    """Sin cliente Telegram (o deshabilitado) no lanza ni alerta."""
    with patch.object(cascade, "_get_telegram_client", return_value=None):
        cascade._alert_circuit_open("model_cascade.prov_a")

    telegram = MagicMock()
    telegram.enabled = False
    with patch.object(cascade, "_get_telegram_client", return_value=telegram):
        cascade._alert_circuit_open("model_cascade.prov_a")
    telegram.send_alert.assert_not_called()


def test_alert_circuit_open_swallows_telegram_errors(cascade):
    """Una excepción del telegram client no propaga al breaker."""
    telegram = MagicMock()
    telegram.enabled = True
    telegram.send_alert.side_effect = RuntimeError("telegram caído")

    with patch.object(cascade, "_get_telegram_client", return_value=telegram):
        cascade._alert_circuit_open("model_cascade.prov_a")  # no debe lanzar


def test_init_circuit_breakers_wires_on_open(mock_credentials):
    """Los breakers reales de la cascada llevan el callback conectado."""
    with patch("services.model_cascade.Credentials.from_env", return_value=mock_credentials):
        c = ModelCascade()
    for cb in c.circuit_breakers.values():
        assert cb.on_open == c._alert_circuit_open
