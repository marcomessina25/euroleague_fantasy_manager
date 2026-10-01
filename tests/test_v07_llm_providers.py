"""V0.7 W4 — LLM provider parity with `fpl-manager`.

The Python backend already implemented Heuristic, Gemini, OpenAI, Claude,
OpenRouter and Local providers and already accepted `api_key`/`model` on the
copilot advise request. The gap was: no server-driven sub-model catalog, no
GUI affordances for a key or a sub-model, no `"auto"` provider mode, and no
secret redaction on provider error paths. These tests pin all of it end to end
with zero network calls: the heuristic provider is the offline fallback and
every "paid" provider under test is a recording/failing stub, never a real
HTTP client.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from euroleague_fantasy_manager.intelligence.providers import (
    BaseLLMProvider,
    HeuristicProvider,
    ProviderAuthError,
    ProviderRequest,
    ProviderResponse,
    get_provider,
    list_available_providers,
)
from euroleague_fantasy_manager.intelligence.security import redact_secrets
from euroleague_fantasy_manager.web.app import create_app

APP_JS = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "euroleague_fantasy_manager"
    / "web"
    / "static"
    / "js"
    / "app.js"
)
INDEX_HTML = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "euroleague_fantasy_manager"
    / "web"
    / "templates"
    / "index.html"
)

_KEY_ENV_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY")


@pytest.fixture(autouse=True)
def _clean_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test in this module runs with no LLM keys configured, unless it sets one itself."""
    for var in _KEY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


# =========================================================================
# D1 — Server-driven model catalog
# =========================================================================
def test_every_provider_has_a_models_list() -> None:
    providers = list_available_providers()
    assert providers, "list_available_providers() must return at least one provider"
    for p in providers:
        assert "models" in p, f"provider '{p.get('id')}' is missing a models catalog"
        assert isinstance(p["models"], list)


def test_openrouter_catalog_is_mostly_free_with_exactly_one_paid_model() -> None:
    providers = {p["provider_name"]: p for p in list_available_providers()}
    models = providers["openrouter"]["models"]

    paid = [m for m in models if m["free"] is False]
    free = [m for m in models if m["free"] is True]

    assert len(paid) == 1, f"expected exactly one paid OpenRouter model, got {paid}"
    assert len(free) >= 3, f"expected at least three free OpenRouter models, got {free}"


def test_default_model_appears_in_its_own_catalog() -> None:
    for p in list_available_providers():
        models = p["models"]
        if not models:
            continue
        model_ids = {m["id"] for m in models}
        assert p["default_model"] in model_ids, (
            f"provider '{p['id']}' default_model '{p['default_model']}' is not in its own catalog {model_ids}"
        )


# =========================================================================
# D6 — "auto" provider mode
# =========================================================================
def test_auto_mode_falls_back_to_heuristic_with_no_keys_configured() -> None:
    provider = get_provider("auto")
    assert isinstance(provider, HeuristicProvider)


def test_auto_mode_selects_first_configured_provider_in_priority_order(monkeypatch: pytest.MonkeyPatch) -> None:
    # Nothing configured yet -> heuristic.
    assert get_provider("auto").name == "heuristic"

    # Only OpenRouter configured -> openrouter, even though it is last priority.
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key-1234567890")
    assert get_provider("auto").name == "openrouter"

    # Gemini outranks OpenRouter once both are configured.
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    assert get_provider("auto").name == "gemini"


def test_auto_mode_never_forwards_a_gui_supplied_key_to_the_wrong_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user pasting an OpenRouter key while "auto" is selected must not leak it to Gemini."""
    monkeypatch.setenv("GEMINI_API_KEY", "env-gemini-key")

    provider = get_provider("auto", api_key="sk-or-v1-USERSECRET")

    assert provider.name == "gemini"
    assert provider.api_key == "env-gemini-key"
    assert "USERSECRET" not in provider.api_key


# =========================================================================
# D5 — Secret redaction
# =========================================================================
@pytest.mark.parametrize(
    "secret",
    [
        "sk-abcdefghijklmnopqrstuvwx1234567890",
        "sk-proj-abcd1234EFGH_ijkl-mnop",
        "sk-or-v1-abcdefghijklmnopqrstuvwx1234567890",
        "sk-ant-api03-abcdefghijklmnopqrstuvwx1234567890",
        "AIzaSyD-abcdefghijklmnopqrstuvwxyz123456",
    ],
)
def test_redact_secrets_scrubs_known_key_formats(secret: str) -> None:
    text = f"Authentication failed for key {secret}: invalid credentials"
    redacted = redact_secrets(text)
    assert secret not in redacted
    assert "invalid credentials" in redacted


def test_redact_secrets_scrubs_bearer_tokens_and_query_params() -> None:
    bearer_text = "Request failed: Authorization: Bearer abc123.def456-ghi789"
    assert "abc123.def456-ghi789" not in redact_secrets(bearer_text)

    query_text = "GET https://api.example.com/v1/models?api_key=sk-super-secret-value&foo=bar"
    redacted = redact_secrets(query_text)
    assert "sk-super-secret-value" not in redacted
    assert "foo=bar" in redacted, "unrelated query parameters must survive redaction"


def test_redact_secrets_does_not_mangle_ordinary_prose() -> None:
    prose = (
        "Captaincy score is strictly doubled under official EuroLeague rules. "
        "Please check your API key configuration if the provider keeps timing out."
    )
    assert redact_secrets(prose) == prose


def test_redact_secrets_handles_empty_and_none_input() -> None:
    assert redact_secrets("") == ""
    assert redact_secrets(None) == ""


# =========================================================================
# End-to-end: api_key / model reach the provider layer, and errors are redacted
# =========================================================================
class _RecordingProvider(BaseLLMProvider):
    def __init__(self) -> None:
        super().__init__(name="recording", api_key="k", default_model="rec-v1")
        self.requests: list[ProviderRequest] = []

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        return ProviderResponse(content="Recorded.", provider=self.name, model=request.model or "rec-v1", latency_ms=1.0)


class _LeakyAuthFailureProvider(BaseLLMProvider):
    """Simulates a real provider echoing a secret back into its error message."""

    def __init__(self) -> None:
        super().__init__(name="leaky", api_key="k")

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        raise ProviderAuthError(
            "OpenRouter authentication failed (HTTP 401): invalid key sk-or-v1-leakedsecret1234567890"
        )


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "test_v07_llm_providers.sqlite3"
    return TestClient(create_app(db_path=db_path))


def test_copilot_advise_forwards_api_key_and_model_to_provider_factory(client: TestClient) -> None:
    rec = _RecordingProvider()
    calls: dict[str, object] = {}

    def fake_get_provider(name: str, api_key: str | None = None, model: str | None = None) -> BaseLLMProvider:
        calls["name"] = name
        calls["api_key"] = api_key
        calls["model"] = model
        return rec

    with patch("euroleague_fantasy_manager.intelligence.copilot.get_provider", side_effect=fake_get_provider):
        res = client.post(
            "/api/workstation/copilot/advise",
            json={
                "team_id": "team_1",
                "persona": "briefing",
                "provider": "recording",
                "tier": "standard",
                "model": "rec-v2",
                "api_key": "test-secret-key-should-reach-provider",
            },
        )

    assert res.status_code == 200, res.text
    data = res.json()
    assert not data["is_fallback"]

    assert calls["name"] == "recording"
    assert calls["api_key"] == "test-secret-key-should-reach-provider"
    assert calls["model"] == "rec-v2"

    assert len(rec.requests) == 1
    assert rec.requests[0].model == "rec-v2"


def test_provider_error_containing_a_secret_is_redacted_before_reaching_http_response(client: TestClient) -> None:
    with patch("euroleague_fantasy_manager.intelligence.copilot.get_provider", return_value=_LeakyAuthFailureProvider()):
        res = client.post(
            "/api/workstation/copilot/advise",
            json={"team_id": "team_1", "persona": "briefing", "provider": "leaky", "tier": "standard"},
        )

    assert res.status_code == 200, res.text
    data = res.json()
    assert data["is_fallback"] is True
    assert "sk-or-v1-leakedsecret1234567890" not in data["fallback_reason"]
    assert "sk-or-v1-leakedsecret1234567890" not in res.text


# =========================================================================
# Static GUI assertions
# =========================================================================
def test_index_html_declares_model_and_api_key_fields() -> None:
    source = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="copilot-model"' in source
    assert 'id="copilot-api-key"' in source
    assert 'type="password"' in source


def test_app_js_sends_api_key_and_model_and_persists_per_provider() -> None:
    source = APP_JS.read_text(encoding="utf-8")

    assert "api_key: apiKey" in source or "api_key:" in source
    assert "model: model" in source or "model:" in source
    assert "elf_copilot_api_key_" in source
    assert "elf_copilot_model_" in source


def test_app_js_renders_paid_model_marker() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert "m.free ? m.name" in source or "Requires paid account credits" in source
    assert "Requires paid account credits" in source


def test_app_js_warns_when_auto_mode_would_ignore_a_pasted_key() -> None:
    """"auto" silently drops a GUI-supplied key, so the GUI must say so instead of hiding it."""
    source = APP_JS.read_text(encoding="utf-8")
    assert 'provider === "auto" && apiKey' in source
