"""
Unified LLM client for ApplyPilot.

Auto-detects provider from environment:
  GEMINI_API_KEY  -> Google Gemini (default: gemini-3.1-flash-lite)
  OPENAI_API_KEY  -> OpenAI (default: gpt-4o-mini)
  LLM_URL         -> Local llama.cpp / Ollama compatible endpoint

LLM_MODEL env var overrides the model name for any provider.
"""

import logging
import os
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"

# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

def _detect_provider() -> tuple[str, str, str]:
    """Return (base_url, model, api_key) based on environment variables.

    Reads env at call time (not module import time) so that load_env() called
    in _bootstrap() is always visible here.
    """
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    local_url = os.environ.get("LLM_URL", "")
    model_override = os.environ.get("LLM_MODEL", "")

    if gemini_key and not local_url:
        return (
            "https://generativelanguage.googleapis.com/v1beta/openai",
            model_override or DEFAULT_GEMINI_MODEL,
            gemini_key,
        )

    if openai_key and not local_url:
        return (
            "https://api.openai.com/v1",
            model_override or "gpt-4o-mini",
            openai_key,
        )

    if local_url:
        return (
            local_url.rstrip("/"),
            model_override or "local-model",
            os.environ.get("LLM_API_KEY", ""),
        )

    raise RuntimeError(
        "No LLM provider configured. "
        "Set GEMINI_API_KEY, OPENAI_API_KEY, or LLM_URL in your environment."
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_MAX_RETRIES = 5
_TIMEOUT = 120  # seconds

# Base wait on first 429/503 (doubles each retry, caps at 60s).
# Gemini free tier is 15 RPM = 4s minimum between requests; 10s gives headroom.
_RATE_LIMIT_BASE_WAIT = 10


_GEMINI_COMPAT_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
_GEMINI_NATIVE_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _estimate_tokens(messages: list[dict] | str) -> int:
    """Cheap token estimate used when providers omit usage metadata."""
    if isinstance(messages, str):
        text = messages
    else:
        text = "\n".join(str(msg.get("content", "")) for msg in messages)
    return max(1, int(len(text) / 4))


def _provider_for_base(base_url: str) -> str:
    if base_url.startswith((_GEMINI_COMPAT_BASE, _GEMINI_NATIVE_BASE)):
        return "gemini"
    if base_url.startswith("https://api.openai.com"):
        return "openai"
    return "local"


def _estimate_cost_usd(provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost from known defaults; exact billing remains provider-side."""
    model_l = model.lower()
    if provider == "gemini" and "flash-lite" in model_l:
        input_per_m = 0.04
        output_per_m = 0.16
    elif provider == "gemini":
        input_per_m = 0.10
        output_per_m = 0.40
    elif provider == "openai" and "gpt-4o-mini" in model_l:
        input_per_m = 0.15
        output_per_m = 0.60
    elif provider == "local":
        input_per_m = output_per_m = 0.0
    else:
        input_per_m = 0.15
        output_per_m = 0.60
    return (input_tokens / 1_000_000 * input_per_m) + (output_tokens / 1_000_000 * output_per_m)


def _record_usage_event(
    *,
    provider: str,
    model: str,
    operation: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_create_tokens: int = 0,
    estimated: bool,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Best-effort DB ledger entry; never let telemetry break the LLM call."""
    try:
        from applypilot.database import record_llm_usage

        record_llm_usage(
            provider=provider,
            model=model,
            operation=operation,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_create_tokens=cache_create_tokens,
            estimated=estimated,
            cost_usd=_estimate_cost_usd(provider, model, input_tokens, output_tokens),
            metadata=metadata or {},
        )
    except Exception:
        log.debug("Failed to record LLM usage event", exc_info=True)


class LLMClient:
    """Thin LLM client supporting OpenAI-compatible and native Gemini endpoints.

    For Gemini keys, starts on the OpenAI-compat layer. On a 403 (which
    happens with preview/experimental models not exposed via compat), it
    automatically switches to the native generateContent API and stays there
    for the lifetime of the process.
    """

    def __init__(self, base_url: str, model: str, api_key: str) -> None:
        self.base_url = base_url
        self.model = model
        self.api_key = api_key
        self._client = httpx.Client(timeout=_TIMEOUT)
        # True once we've confirmed the native Gemini API works for this model
        self._use_native_gemini: bool = False
        self._is_gemini: bool = base_url.startswith(_GEMINI_COMPAT_BASE)

    # -- Native Gemini API --------------------------------------------------

    def _chat_native_gemini(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        operation: str,
    ) -> str:
        """Call the native Gemini generateContent API.

        Used automatically when the OpenAI-compat endpoint returns 403,
        which happens for preview/experimental models not exposed via compat.

        Converts OpenAI-style messages to Gemini's contents/systemInstruction
        format transparently.
        """
        contents: list[dict] = []
        system_parts: list[dict] = []

        for msg in messages:
            role = msg["role"]
            text = msg.get("content", "")
            if role == "system":
                system_parts.append({"text": text})
            elif role == "user":
                contents.append({"role": "user", "parts": [{"text": text}]})
            elif role == "assistant":
                # Gemini uses "model" instead of "assistant"
                contents.append({"role": "model", "parts": [{"text": text}]})

        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}

        url = f"{_GEMINI_NATIVE_BASE}/models/{self.model}:generateContent"
        resp = self._client.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            params={"key": self.api_key},
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        usage = data.get("usageMetadata") or {}
        input_tokens = int(usage.get("promptTokenCount") or _estimate_tokens(messages))
        output_tokens = int(usage.get("candidatesTokenCount") or _estimate_tokens(text))
        _record_usage_event(
            provider="gemini",
            model=self.model,
            operation=operation,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated=not bool(usage),
            metadata={"endpoint": "native"},
        )
        return text

    # -- OpenAI-compat API --------------------------------------------------

    def _chat_compat(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        operation: str,
    ) -> str:
        """Call the OpenAI-compatible endpoint."""
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        resp = self._client.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=headers,
        )

        # 403 on Gemini compat = model not available on compat layer.
        # Raise a specific sentinel so chat() can switch to native API.
        if resp.status_code == 403 and self._is_gemini:
            raise _GeminiCompatForbidden(resp)

        return self._handle_compat_response(
            resp,
            provider=_provider_for_base(self.base_url),
            model=self.model,
            operation=operation,
            prompt_messages=messages,
        )

    @staticmethod
    def _handle_compat_response(
        resp: httpx.Response,
        *,
        provider: str,
        model: str,
        operation: str,
        prompt_messages: list[dict],
    ) -> str:
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage") or {}
        input_tokens = int(
            usage.get("prompt_tokens")
            or usage.get("input_tokens")
            or _estimate_tokens(prompt_messages)
        )
        output_tokens = int(
            usage.get("completion_tokens")
            or usage.get("output_tokens")
            or _estimate_tokens(text)
        )
        _record_usage_event(
            provider=provider,
            model=model,
            operation=operation,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
            cache_create_tokens=int(usage.get("cache_creation_input_tokens") or 0),
            estimated=not bool(usage),
            metadata={"endpoint": "compat"},
        )
        return text

    # -- public API ---------------------------------------------------------

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 4096,
        operation: str = "chat",
    ) -> str:
        """Send a chat completion request and return the assistant message text."""
        # Qwen3 optimization: prepend /no_think to skip chain-of-thought
        # reasoning, saving tokens on structured extraction tasks.
        if "qwen" in self.model.lower() and messages:
            first = messages[0]
            if first.get("role") == "user" and not first["content"].startswith("/no_think"):
                messages = [{"role": first["role"], "content": f"/no_think\n{first['content']}"}] + messages[1:]

        for attempt in range(_MAX_RETRIES):
            try:
                # Route to native Gemini if we've already confirmed it's needed
                if self._use_native_gemini:
                    return self._chat_native_gemini(messages, temperature, max_tokens, operation)

                return self._chat_compat(messages, temperature, max_tokens, operation)

            except _GeminiCompatForbidden as exc:
                # Model not available on OpenAI-compat layer — switch to native.
                log.warning(
                    "Gemini compat endpoint returned 403 for model '%s'. "
                    "Switching to native generateContent API. "
                    "(Preview/experimental models are often compat-only on native.)",
                    self.model,
                )
                self._use_native_gemini = True
                # Retry immediately with native — don't count as a rate-limit wait
                try:
                    return self._chat_native_gemini(messages, temperature, max_tokens, operation)
                except httpx.HTTPStatusError as native_exc:
                    raise RuntimeError(
                        f"Both Gemini endpoints failed. Compat: 403 Forbidden. "
                        f"Native: {native_exc.response.status_code} — "
                        f"{native_exc.response.text[:200]}"
                    ) from native_exc

            except httpx.HTTPStatusError as exc:
                resp = exc.response
                if resp.status_code in (429, 503) and attempt < _MAX_RETRIES - 1:
                    # Respect Retry-After header if provided (Gemini sends this).
                    retry_after = (
                        resp.headers.get("Retry-After")
                        or resp.headers.get("X-RateLimit-Reset-Requests")
                    )
                    if retry_after:
                        try:
                            wait = float(retry_after)
                        except (ValueError, TypeError):
                            wait = _RATE_LIMIT_BASE_WAIT * (2 ** attempt)
                    else:
                        wait = min(_RATE_LIMIT_BASE_WAIT * (2 ** attempt), 60)

                    log.warning(
                        "LLM rate limited (HTTP %s). Waiting %ds before retry %d/%d. "
                        "Tip: Gemini free tier = 15 RPM. Consider a paid account "
                        "or switching to a local model.",
                        resp.status_code, wait, attempt + 1, _MAX_RETRIES,
                    )
                    time.sleep(wait)
                    continue
                raise

            except httpx.TimeoutException:
                if attempt < _MAX_RETRIES - 1:
                    wait = min(_RATE_LIMIT_BASE_WAIT * (2 ** attempt), 60)
                    log.warning(
                        "LLM request timed out, retrying in %ds (attempt %d/%d)",
                        wait, attempt + 1, _MAX_RETRIES,
                    )
                    time.sleep(wait)
                    continue
                raise

        raise RuntimeError("LLM request failed after all retries")

    def ask(self, prompt: str, **kwargs) -> str:
        """Convenience: single user prompt -> assistant response."""
        return self.chat([{"role": "user", "content": prompt}], **kwargs)

    def close(self) -> None:
        self._client.close()


class _GeminiCompatForbidden(Exception):
    """Sentinel: Gemini OpenAI-compat returned 403. Switch to native API."""
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        super().__init__(f"Gemini compat 403: {response.text[:200]}")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: LLMClient | None = None


def get_client() -> LLMClient:
    """Return (or create) the module-level LLMClient singleton."""
    global _instance
    if _instance is None:
        base_url, model, api_key = _detect_provider()
        log.info("LLM provider: %s  model: %s", base_url, model)
        _instance = LLMClient(base_url, model, api_key)
    return _instance


def get_gemini_client() -> LLMClient:
    """Return an LLM client pinned to Google Gemini (referral message drafting)."""
    from applypilot.config import load_env

    load_env()
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is required for personalized referral messages. "
            "Add it to ~/.applypilot/.env"
        )
    model = os.environ.get("LLM_MODEL", DEFAULT_GEMINI_MODEL)
    return LLMClient(_GEMINI_COMPAT_BASE, model, key)
