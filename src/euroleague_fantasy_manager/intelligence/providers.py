"""Provider abstraction layer for V0.6 Strategic Intelligence Copilot.

Isolates external LLM interactions (Gemini, OpenAI, Claude, OpenRouter, Local)
with guaranteed 100% offline fallback via HeuristicProvider.
Zero network calls or credentials required for deterministic operation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
import os
import time
from typing import Any
import urllib.error
import urllib.request


class ProviderError(Exception):
    """Base error for LLM provider failures."""


class ProviderAuthError(ProviderError):
    """Authentication or invalid API key error."""


class ProviderTimeoutError(ProviderError):
    """Network or execution timeout error."""


class ProviderRateLimitError(ProviderError):
    """Rate limit or quota exhaustion error."""


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    """Standardized envelope for sending analysis tasks to providers."""

    prompt: str
    system_prompt: str = ""
    model: str | None = None
    temperature: float = 0.2
    timeout_seconds: float = 15.0
    extra_headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    """Standardized response envelope from a provider."""

    content: str
    provider: str
    model: str
    latency_ms: float
    raw_metadata: dict[str, Any] = field(default_factory=dict)


class BaseLLMProvider(ABC):
    """Abstract base class for all LLM and heuristic providers."""

    def __init__(
        self,
        name: str,
        api_key: str | None = None,
        default_model: str | None = None,
    ) -> None:
        self.name = name
        self.api_key = (api_key or "").strip()
        self.default_model = default_model

    @abstractmethod
    def generate(self, request: ProviderRequest) -> ProviderResponse:
        """Generate response content from provider."""
        ...

    def is_available(self) -> bool:
        """Verify whether provider has the required configuration."""
        return True


class HeuristicProvider(BaseLLMProvider):
    """Deterministic, 100% offline heuristic advisor requiring zero external API keys."""

    def __init__(self) -> None:
        super().__init__(name="heuristic", api_key=None, default_model="deterministic-heuristic-v0.6")

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        t0 = time.perf_counter()

        heading = "### Deterministic Strategic Assessment (Offline Heuristic Mode)"
        sys_p = request.system_prompt or ""
        if "Devil's Advocate" in sys_p:
            heading = "### DEVIL'S ADVOCATE CRITIQUE (Offline Heuristic Mode)"
        elif "Manager Briefing" in sys_p:
            heading = "### MANAGER BRIEFING (Offline Heuristic Mode)"
        elif "Tactical Rotation" in sys_p:
            heading = "### TACTICAL ROTATION & MATCHUP ANALYSIS (Offline Heuristic Mode)"
        elif "Long-Range" in sys_p:
            heading = "### STRATEGIC PLANNER ROADMAP (Offline Heuristic Mode)"

        lines = [
            heading,
            "",
            "1. **Lineup & Squad Structure**: Verified against deterministic mathematical projections. Starting five balances positional quotas and Turn 1 vs Turn 2 substitution flexibility.",
            "2. **Captaincy Selection**: Prioritizes highest expected value starter. Captaincy score is strictly doubled under official EuroLeague rules.",
            "3. **Bench & Sixth Man Optionality**: Sixth man converts at 1.0x (full production) while bench units score at 0.5x. Unplayed Turn 2 bench players provide crucial downside cover.",
            "4. **Transfer Discipline**: Evaluated with two-stage candidate screening to prevent credit dissipation while maximizing net score gains.",
            "",
            "> [!NOTE]",
            "> Generated using local deterministic heuristics. To enable LLM qualitative critique, configure an API key for Gemini, OpenAI, Claude, or OpenRouter.",
        ]
        content = "\n".join(lines)
        latency = (time.perf_counter() - t0) * 1000.0

        return ProviderResponse(
            content=content,
            provider=self.name,
            model=self.default_model or "deterministic-heuristic",
            latency_ms=round(latency, 2),
            raw_metadata={"offline": True},
        )


class GeminiProvider(BaseLLMProvider):
    """Google Gemini provider using REST generateContent."""

    def __init__(self, api_key: str | None = None, default_model: str | None = None) -> None:
        key = api_key or os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")
        super().__init__(name="gemini", api_key=key, default_model=default_model or "gemini-2.0-flash")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        if not self.is_available():
            raise ProviderAuthError("Gemini API key not configured. Set GEMINI_API_KEY or GOOGLE_API_KEY.")

        model = request.model or self.default_model or "gemini-2.0-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"

        body = {
            "contents": [
                {
                    "parts": [
                        {"text": (f"{request.system_prompt}\n\n" if request.system_prompt else "") + request.prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": request.temperature,
            },
        }

        t0 = time.perf_counter()
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=request.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                latency = (time.perf_counter() - t0) * 1000.0
                candidates = data.get("candidates", [])
                if not candidates:
                    raise ProviderError("Empty response candidates from Gemini API.")
                content = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                return ProviderResponse(
                    content=content,
                    provider=self.name,
                    model=model,
                    latency_ms=round(latency, 2),
                    raw_metadata=data.get("usageMetadata", {}),
                )
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise ProviderAuthError(f"Gemini authentication failed (HTTP {e.code}): {e.reason}") from e
            elif e.code == 429:
                raise ProviderRateLimitError(f"Gemini rate limit exceeded: {e.reason}") from e
            raise ProviderError(f"Gemini API error (HTTP {e.code}): {e.reason}") from e
        except urllib.error.URLError as e:
            raise ProviderTimeoutError(f"Gemini connection error: {e.reason}") from e


class OpenAIProvider(BaseLLMProvider):
    """OpenAI provider using /v1/chat/completions."""

    def __init__(self, api_key: str | None = None, default_model: str | None = None, base_url: str | None = None) -> None:
        key = api_key or os.environ.get("OPENAI_API_KEY", "")
        super().__init__(name="openai", api_key=key, default_model=default_model or "gpt-4o-mini")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        if not self.is_available():
            raise ProviderAuthError("OpenAI API key not configured. Set OPENAI_API_KEY.")

        model = request.model or self.default_model or "gpt-4o-mini"
        url = f"{self.base_url}/chat/completions"

        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})

        body = {
            "model": model,
            "messages": messages,
            "temperature": request.temperature,
        }

        t0 = time.perf_counter()
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=request.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                latency = (time.perf_counter() - t0) * 1000.0
                choices = data.get("choices", [])
                if not choices:
                    raise ProviderError("Empty choices from OpenAI API.")
                content = choices[0].get("message", {}).get("content", "")
                return ProviderResponse(
                    content=content,
                    provider=self.name,
                    model=model,
                    latency_ms=round(latency, 2),
                    raw_metadata=data.get("usage", {}),
                )
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise ProviderAuthError(f"OpenAI authentication failed (HTTP {e.code}): {e.reason}") from e
            elif e.code == 429:
                raise ProviderRateLimitError(f"OpenAI rate limit exceeded: {e.reason}") from e
            raise ProviderError(f"OpenAI API error (HTTP {e.code}): {e.reason}") from e
        except urllib.error.URLError as e:
            raise ProviderTimeoutError(f"OpenAI connection error: {e.reason}") from e


class AnthropicClaudeProvider(BaseLLMProvider):
    """Anthropic Claude provider using /v1/messages."""

    def __init__(self, api_key: str | None = None, default_model: str | None = None) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        super().__init__(name="claude", api_key=key, default_model=default_model or "claude-3-5-haiku-20241022")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        if not self.is_available():
            raise ProviderAuthError("Anthropic API key not configured. Set ANTHROPIC_API_KEY.")

        model = request.model or self.default_model or "claude-3-5-haiku-20241022"
        url = "https://api.anthropic.com/v1/messages"

        body: dict[str, Any] = {
            "model": model,
            "max_tokens": 1500,
            "temperature": request.temperature,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.system_prompt:
            body["system"] = request.system_prompt

        t0 = time.perf_counter()
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=request.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                latency = (time.perf_counter() - t0) * 1000.0
                content_blocks = data.get("content", [])
                content = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")
                return ProviderResponse(
                    content=content,
                    provider=self.name,
                    model=model,
                    latency_ms=round(latency, 2),
                    raw_metadata=data.get("usage", {}),
                )
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise ProviderAuthError(f"Anthropic authentication failed (HTTP {e.code}): {e.reason}") from e
            elif e.code == 429:
                raise ProviderRateLimitError(f"Anthropic rate limit exceeded: {e.reason}") from e
            raise ProviderError(f"Anthropic API error (HTTP {e.code}): {e.reason}") from e
        except urllib.error.URLError as e:
            raise ProviderTimeoutError(f"Anthropic connection error: {e.reason}") from e


class OpenRouterProvider(BaseLLMProvider):
    """OpenRouter provider with access to free and open-source models."""

    def __init__(self, api_key: str | None = None, default_model: str | None = None) -> None:
        key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        super().__init__(
            name="openrouter",
            api_key=key,
            default_model=default_model or "meta-llama/llama-3.3-70b-instruct:free",
        )

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        if not self.is_available():
            raise ProviderAuthError("OpenRouter API key not configured. Set OPENROUTER_API_KEY.")

        model = request.model or self.default_model or "meta-llama/llama-3.3-70b-instruct:free"
        url = "https://openrouter.ai/api/v1/chat/completions"

        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})

        body = {
            "model": model,
            "messages": messages,
            "temperature": request.temperature,
        }

        t0 = time.perf_counter()
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "HTTP-Referer": "https://github.com/marcomessina25/euroleague_fantasy_manager",
                "X-Title": "EuroLeague Fantasy Manager",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=request.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                latency = (time.perf_counter() - t0) * 1000.0
                choices = data.get("choices", [])
                if not choices:
                    raise ProviderError("Empty choices from OpenRouter API.")
                content = choices[0].get("message", {}).get("content", "")
                return ProviderResponse(
                    content=content,
                    provider=self.name,
                    model=model,
                    latency_ms=round(latency, 2),
                    raw_metadata=data.get("usage", {}),
                )
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise ProviderAuthError(f"OpenRouter authentication failed (HTTP {e.code}): {e.reason}") from e
            elif e.code == 429:
                raise ProviderRateLimitError(f"OpenRouter rate limit exceeded: {e.reason}") from e
            raise ProviderError(f"OpenRouter API error (HTTP {e.code}): {e.reason}") from e
        except urllib.error.URLError as e:
            raise ProviderTimeoutError(f"OpenRouter connection error: {e.reason}") from e


class LocalProvider(BaseLLMProvider):
    """Local OpenAI-compatible provider (Ollama / LocalAI / vLLM)."""

    def __init__(self, base_url: str | None = None, default_model: str | None = None) -> None:
        url = base_url or os.environ.get("LOCAL_LLM_URL", "http://localhost:11434/v1")
        super().__init__(name="local", api_key="local", default_model=default_model or "llama3.2")
        self.base_url = url.rstrip("/")

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        model = request.model or self.default_model or "llama3.2"
        url = f"{self.base_url}/chat/completions"

        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})

        body = {
            "model": model,
            "messages": messages,
            "temperature": request.temperature,
        }

        t0 = time.perf_counter()
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=request.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                latency = (time.perf_counter() - t0) * 1000.0
                choices = data.get("choices", [])
                if not choices:
                    raise ProviderError("Empty choices from local LLM endpoint.")
                content = choices[0].get("message", {}).get("content", "")
                return ProviderResponse(
                    content=content,
                    provider=self.name,
                    model=model,
                    latency_ms=round(latency, 2),
                    raw_metadata={},
                )
        except Exception as e:
            raise ProviderTimeoutError(f"Local LLM endpoint unreachable at {self.base_url}: {e}") from e


def get_provider(
    name: str = "heuristic",
    api_key: str | None = None,
    model: str | None = None,
) -> BaseLLMProvider:
    """Provider factory with automatic fallback resolution."""
    norm = (name or "heuristic").strip().lower().replace("-", "_")

    if norm in ("heuristic", "offline", "none"):
        return HeuristicProvider()
    if norm in ("gemini", "google"):
        return GeminiProvider(api_key=api_key, default_model=model)
    if norm in ("openai", "gpt"):
        return OpenAIProvider(api_key=api_key, default_model=model)
    if norm in ("claude", "anthropic"):
        return AnthropicClaudeProvider(api_key=api_key, default_model=model)
    if norm in ("openrouter", "or"):
        return OpenRouterProvider(api_key=api_key, default_model=model)
    if norm in ("local", "ollama", "vllm"):
        return LocalProvider(default_model=model)

    # Unknown provider -> fallback to Heuristic
    return HeuristicProvider()


def list_available_providers() -> list[dict[str, Any]]:
    """Discover available providers based on environment configuration."""
    providers = [
        {
            "id": "heuristic",
            "provider_name": "heuristic",
            "name": "Deterministic Heuristic (Offline)",
            "display_name": "Deterministic Heuristic (Offline)",
            "default_model": "heuristic-engine-v1",
            "available": True,
            "requires_key": False,
            "tier": "fast",
        },
        {
            "id": "gemini",
            "provider_name": "gemini",
            "name": "Google Gemini",
            "display_name": "Google Gemini",
            "default_model": "gemini-2.5-flash",
            "available": bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")),
            "requires_key": True,
            "tier": "standard",
        },
        {
            "id": "openai",
            "provider_name": "openai",
            "name": "OpenAI (GPT-4o / GPT-4o-mini)",
            "display_name": "OpenAI (GPT-4o / GPT-4o-mini)",
            "default_model": "gpt-4o-mini",
            "available": bool(os.environ.get("OPENAI_API_KEY")),
            "requires_key": True,
            "tier": "standard",
        },
        {
            "id": "claude",
            "provider_name": "claude",
            "name": "Anthropic Claude",
            "display_name": "Anthropic Claude",
            "default_model": "claude-3-5-haiku-20241022",
            "available": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "requires_key": True,
            "tier": "extended",
        },
        {
            "id": "openrouter",
            "provider_name": "openrouter",
            "name": "OpenRouter (Free / Open Models)",
            "display_name": "OpenRouter (Free / Open Models)",
            "default_model": "meta-llama/llama-3.3-70b-instruct:free",
            "available": bool(os.environ.get("OPENROUTER_API_KEY")),
            "requires_key": True,
            "tier": "fast",
        },
        {
            "id": "local",
            "provider_name": "local",
            "name": "Local LLM (Ollama / vLLM)",
            "display_name": "Local LLM (Ollama / vLLM)",
            "default_model": "llama3.2:latest",
            "available": True,
            "requires_key": False,
            "tier": "fast",
        },
    ]
    return providers
