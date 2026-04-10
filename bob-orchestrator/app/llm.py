"""Model-agnostic LLM adapter for BOB.

BOB used to be locked to Claude Opus via langchain_anthropic. This module
abstracts the provider so the same orchestrator works on Anthropic, OpenAI,
or any Ollama-compatible local backend (Qwen, Llama, DeepSeek, etc.) with
no code changes — just an env var.

Design goals:
1. Single function `get_llm()` returns a LangChain BaseChatModel.
2. Provider chosen by `BOB_LLM_PROVIDER` env var (anthropic | openai | ollama).
3. Each provider's package is imported lazily so users don't pay the install
   cost for providers they don't use.
4. Tool-calling support is preserved across all providers — LangGraph's
   `create_react_agent` calls `bind_tools()` on whatever we return, and all
   three supported providers implement it.
5. Configuration is per-provider but follows a consistent pattern: model name,
   max tokens, temperature, optional base URL, optional API key override.

Adding a new provider:
1. Add a branch in `get_llm()` below.
2. Add the package to requirements.txt.
3. Document the new provider in LLM_PROVIDERS.md.
4. The new provider must support `bind_tools()` — verify by running the
   quickstart against it before merging.
"""

import logging
import os
from typing import Any

logger = logging.getLogger("bob.llm")


# ── Provider defaults ───────────────────────────────────────────────────────

DEFAULT_MODELS = {
    "anthropic": "claude-opus-4-6",
    "openai": "gpt-4o",
    "ollama": "qwen2.5:14b",
}

# Sensible per-provider defaults if the user doesn't override
DEFAULT_BASE_URLS = {
    "anthropic": None,  # Uses Anthropic SDK default
    "openai": None,     # Uses OpenAI SDK default
    "ollama": "http://localhost:11434",
}


# ── Public factory ──────────────────────────────────────────────────────────

def get_llm(
    provider: str | None = None,
    model: str | None = None,
    max_tokens: int = 8192,
    temperature: float | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> Any:
    """Return a LangChain BaseChatModel for the configured provider.

    Args:
        provider:    'anthropic', 'openai', or 'ollama'. Defaults to BOB_LLM_PROVIDER env var, then 'anthropic'.
        model:       Model name. Provider-specific. Defaults to BOB_MODEL env var, then DEFAULT_MODELS[provider].
        max_tokens:  Max tokens per response.
        temperature: Sampling temperature. None = provider default.
        base_url:    Override the API endpoint. Useful for vLLM, LiteLLM proxy, custom Ollama hosts.
        api_key:     Override the API key. Falls back to provider-specific env vars.

    Returns:
        A LangChain ChatModel instance with `.bind_tools()` support.

    Raises:
        ValueError if provider is unknown or required config is missing.
        ImportError if the provider's package is not installed.
    """
    provider = (provider or os.getenv("BOB_LLM_PROVIDER", "anthropic")).lower().strip()
    model = model or os.getenv("BOB_MODEL", "") or DEFAULT_MODELS.get(provider, "")
    base_url = base_url or os.getenv("BOB_LLM_BASE_URL") or DEFAULT_BASE_URLS.get(provider)

    if not model:
        raise ValueError(f"No model specified for provider '{provider}' and no default available")

    logger.info(f"Initializing LLM: provider={provider}, model={model}")

    if provider == "anthropic":
        return _build_anthropic(model, max_tokens, temperature, base_url, api_key)
    if provider == "openai":
        return _build_openai(model, max_tokens, temperature, base_url, api_key)
    if provider == "ollama":
        return _build_ollama(model, max_tokens, temperature, base_url, api_key)

    raise ValueError(
        f"Unknown LLM provider: '{provider}'. Supported: anthropic, openai, ollama. "
        f"Set BOB_LLM_PROVIDER to one of these."
    )


# ── Provider builders ───────────────────────────────────────────────────────

def _build_anthropic(model, max_tokens, temperature, base_url, api_key):
    """Anthropic Claude via langchain-anthropic."""
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as e:
        raise ImportError(
            "langchain-anthropic not installed. "
            "Add to requirements.txt: langchain-anthropic>=0.3.0"
        ) from e

    key = api_key or os.getenv("BOB_LLM_API_KEY") or os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY (or BOB_LLM_API_KEY) is not set")

    kwargs = {
        "model": model,
        "api_key": key,
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    if base_url:
        kwargs["base_url"] = base_url

    return ChatAnthropic(**kwargs)


def _build_openai(model, max_tokens, temperature, base_url, api_key):
    """OpenAI GPT models via langchain-openai. Also works for any
    OpenAI-compatible endpoint (vLLM, LiteLLM proxy, LM Studio, etc.) by
    setting BOB_LLM_BASE_URL.
    """
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as e:
        raise ImportError(
            "langchain-openai not installed. "
            "Add to requirements.txt: langchain-openai>=0.2.0"
        ) from e

    key = api_key or os.getenv("BOB_LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    if not key:
        # vLLM / LM Studio / LiteLLM often accept any key including 'EMPTY'
        if base_url:
            key = "EMPTY"
            logger.warning(
                "No OPENAI_API_KEY set but base_url is configured — using 'EMPTY' "
                "as the API key (works with vLLM, LM Studio, LiteLLM)"
            )
        else:
            raise ValueError("OPENAI_API_KEY (or BOB_LLM_API_KEY) is not set")

    kwargs = {
        "model": model,
        "api_key": key,
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    if base_url:
        kwargs["base_url"] = base_url

    return ChatOpenAI(**kwargs)


def _build_ollama(model, max_tokens, temperature, base_url, api_key):
    """Ollama local models via langchain-ollama. Use any Ollama-compatible
    model that supports tool calling — Qwen 2.5, Llama 3.3, Mistral Nemo, etc.
    """
    try:
        from langchain_ollama import ChatOllama
    except ImportError as e:
        raise ImportError(
            "langchain-ollama not installed. "
            "Add to requirements.txt: langchain-ollama>=0.2.0"
        ) from e

    # Ollama doesn't use API keys for the standard local case
    if api_key:
        logger.info("api_key passed to Ollama provider — Ollama typically ignores this")

    kwargs = {
        "model": model,
        "num_predict": max_tokens,  # Ollama's equivalent to max_tokens
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    if base_url:
        kwargs["base_url"] = base_url

    return ChatOllama(**kwargs)


# ── Capability check ────────────────────────────────────────────────────────

def check_provider_available(provider: str) -> tuple[bool, str]:
    """Check if a provider's package is installed and importable.

    Returns (available, message). Useful for diagnostics on startup.
    """
    provider = provider.lower().strip()
    if provider == "anthropic":
        try:
            import langchain_anthropic  # noqa: F401
            return True, "langchain-anthropic installed"
        except ImportError:
            return False, "langchain-anthropic not installed"
    if provider == "openai":
        try:
            import langchain_openai  # noqa: F401
            return True, "langchain-openai installed"
        except ImportError:
            return False, "langchain-openai not installed"
    if provider == "ollama":
        try:
            import langchain_ollama  # noqa: F401
            return True, "langchain-ollama installed"
        except ImportError:
            return False, "langchain-ollama not installed"
    return False, f"unknown provider: {provider}"


def list_providers() -> dict:
    """Return a dict describing all known providers and their availability.
    Used by the /llm/status endpoint and startup diagnostics.
    """
    result = {}
    for p in ("anthropic", "openai", "ollama"):
        available, msg = check_provider_available(p)
        result[p] = {
            "available": available,
            "default_model": DEFAULT_MODELS[p],
            "default_base_url": DEFAULT_BASE_URLS[p],
            "status": msg,
        }
    return result
