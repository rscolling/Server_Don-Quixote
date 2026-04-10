# LLM Providers

BOB is model-agnostic. You can run him on **Anthropic Claude**, **OpenAI GPT**, or **any Ollama-compatible local model** (Qwen, Llama, DeepSeek, Mistral) without changing a line of code. Pick one with an env var.

This document covers what works, what doesn't, the honest tradeoffs, and how to add a new provider.

---

## TL;DR

| Provider | Default model | Tool calling | Cost | Privacy | Recommended for |
|---|---|---|---|---|---|
| `anthropic` | `claude-opus-4-6` | Best | $$$ | Cloud | Production. The reference implementation. |
| `openai` | `gpt-4o` | Very good | $$ | Cloud | Production fallback, lower cost |
| `ollama` | `qwen2.5:14b` | Good (model-dependent) | Free (compute only) | Local | Privacy-sensitive, air-gapped, dev/test |

**Default is Anthropic.** Change with one env var:

```bash
BOB_LLM_PROVIDER=openai     # or 'anthropic' or 'ollama'
BOB_MODEL=gpt-4o            # optional override
```

---

## How It Works

BOB's LLM is built by `app/llm.py:get_llm()`. It returns a LangChain `BaseChatModel` instance. LangGraph's `create_react_agent` doesn't care which provider is underneath as long as it implements `bind_tools()` — and all three supported providers do.

The graph builder calls `get_llm()` once at startup. Swapping providers requires a restart but no code change.

```text
.env (BOB_LLM_PROVIDER=...)
        │
        ▼
get_llm()  ──> ChatAnthropic / ChatOpenAI / ChatOllama
        │
        ▼
create_react_agent(model=..., tools=ALL_TOOLS)
        │
        ▼
LangGraph agent (BOB)
```

The provider only affects the LLM call. Everything else — the firewall, the audit log, the recovery layer, the MCP integration, the message bus, the memory layer — is provider-agnostic.

---

## Provider 1 — Anthropic Claude (Default)

**What it is:** Anthropic's Claude family via `langchain-anthropic`.

**Why it's the default:** Best tool-calling reliability of any model BOB has been tested against. Claude was trained with explicit tool-calling support and rarely hallucinates tool names or generates malformed arguments. The 1M context window in Opus 4.6 is comfortable for an orchestrator that maintains a lot of state.

**Config:**

```bash
BOB_LLM_PROVIDER=anthropic
BOB_MODEL=claude-opus-4-6              # default; cheaper: claude-sonnet-4-5
ANTHROPIC_API_KEY=sk-ant-api03-...
BOB_LLM_MAX_TOKENS=8192                # optional
BOB_LLM_TEMPERATURE=0.7                # optional, leave empty for default
```

**Recommended models:**

| Model | Use case | Tool-calling | Cost (relative) |
|---|---|---|---|
| `claude-opus-4-6` | Production orchestrator, default | Excellent | High |
| `claude-sonnet-4-5` | Cost-conscious production | Excellent | Medium |
| `claude-haiku-4-5` | Fast specialist agents (researcher, classifier) | Good | Low |

**Honest cost expectation:** $50–150/month for an active solo founder running BOB hard. Claude Opus tokens are not cheap. If you're delegating heavily to specialist agents, use Haiku or Sonnet for the specialists and reserve Opus for the orchestrator.

---

## Provider 2 — OpenAI GPT

**What it is:** OpenAI's GPT models (and any OpenAI-compatible endpoint) via `langchain-openai`.

**Why use it:** Wider availability, often lower per-token cost than Claude, and OpenAI-compatible endpoints (vLLM, LiteLLM proxy, LM Studio, OpenRouter) let you point BOB at hundreds of other models with a single env var.

**Config:**

```bash
BOB_LLM_PROVIDER=openai
BOB_MODEL=gpt-4o                       # default; alternatives: gpt-4-turbo, gpt-4o-mini
OPENAI_API_KEY=sk-proj-...
BOB_LLM_MAX_TOKENS=8192                # optional
```

**Custom OpenAI-compatible endpoint** (vLLM, LiteLLM, LM Studio, etc.):

```bash
BOB_LLM_PROVIDER=openai
BOB_MODEL=Qwen/Qwen2.5-72B-Instruct    # whatever your endpoint serves
BOB_LLM_BASE_URL=http://vllm:8000/v1
OPENAI_API_KEY=EMPTY                   # most local endpoints accept any value
```

**Recommended models:**

| Model | Use case | Tool-calling | Cost (relative) |
|---|---|---|---|
| `gpt-4o` | Default, balanced | Very good | Medium |
| `gpt-4-turbo` | Higher quality | Very good | High |
| `gpt-4o-mini` | Cost-conscious | Good | Low |

**Honest tool-calling note:** GPT-4o handles BOB's 35 tools reliably in testing. GPT-3.5 and earlier do not — they hallucinate tool names and skip parameters. If you must use a smaller OpenAI model, expect to disable some tools or add validation.

---

## Provider 3 — Ollama (Local Models)

**What it is:** Any model runnable via [Ollama](https://ollama.com/) — Qwen, Llama, DeepSeek, Mistral, Phi, Granite, etc. via `langchain-ollama`.

**Why use it:** Total privacy, no API costs, no network dependency, runs on your hardware. Air-gapped deployments, sensitive data, and compliance scenarios where data cannot leave your machine.

**Config:**

```bash
BOB_LLM_PROVIDER=ollama
BOB_MODEL=qwen2.5:14b                  # default; needs ~10GB VRAM
BOB_LLM_BASE_URL=http://localhost:11434  # default Ollama endpoint
BOB_LLM_TEMPERATURE=0.7                # optional
```

**Setup:** Install Ollama on the host (or run as a sibling container), pull a model that supports tool calling:

```bash
ollama pull qwen2.5:14b
ollama pull llama3.3:70b   # if you have the VRAM
ollama pull mistral-nemo:12b
```

If running BOB in Docker on a Linux host, set `BOB_LLM_BASE_URL=http://host.docker.internal:11434` and add `extra_hosts: ["host.docker.internal:host-gateway"]` to BOB's docker-compose service definition.

**Recommended models:**

| Model | Size | Use case | Tool-calling reliability |
|---|---|---|---|
| `qwen2.5:14b` | ~10GB | Default for local | Good |
| `qwen2.5:32b` | ~20GB | Better reasoning, needs more VRAM | Very good |
| `qwen2.5:72b` | ~45GB | Best open model for tool calling | Very good |
| `llama3.3:70b` | ~40GB | Strong general capability | Good |
| `mistral-nemo:12b` | ~7GB | Lightweight, fast | Moderate |
| `deepseek-coder-v2` | varies | Specialized code agent | Very good (code) |

**Honest tool-calling note:** Open models still trail Claude and GPT-4 on tool calling. Expect occasional issues:

- Hallucinated tool names (BOB's firewall catches these and returns an error to the LLM, which usually self-corrects on the next turn)
- Missing required parameters (LangChain validation catches these)
- Unwanted tool calls when a plain answer would suffice

The smaller the model, the worse it gets. Below 14B parameters, tool calling becomes unreliable enough that BOB's debate arena pattern starts to break down. Stick to 14B+ for orchestration. For specialist agents, smaller models are fine since they have one job.

**No API key needed.** Ollama is local and doesn't authenticate.

---

## Switching Providers

It's a one-line change. Edit `.env`:

```bash
# Was:
BOB_LLM_PROVIDER=anthropic

# Now:
BOB_LLM_PROVIDER=openai
```

Restart BOB:

```bash
docker compose restart bob
```

Verify the swap:

```bash
curl http://localhost:8100/llm/status | jq
```

You'll see something like:

```json
{
  "active": {
    "provider": "openai",
    "model": "gpt-4o",
    "max_tokens": 8192,
    "base_url": "(provider default)"
  },
  "providers": {
    "anthropic": {"available": true, "default_model": "claude-opus-4-6", "default_base_url": null, "status": "langchain-anthropic installed"},
    "openai": {"available": true, "default_model": "gpt-4o", "default_base_url": null, "status": "langchain-openai installed"},
    "ollama": {"available": true, "default_model": "qwen2.5:14b", "default_base_url": "http://localhost:11434", "status": "langchain-ollama installed"}
  }
}
```

The `active` block tells you what BOB is currently using. The `providers` block shows which adapters are installed.

---

## Mixing Providers (Different Models for Different Roles)

The current adapter is global — BOB and all his native tools use the same model. The specialist agents in the quickstart (researcher, coder) each have their own model env var, so you can mix freely:

```bash
# .env
BOB_LLM_PROVIDER=anthropic
BOB_MODEL=claude-opus-4-6        # The orchestrator gets the strongest model
RESEARCHER_MODEL=claude-haiku-4-5  # Cheap fast research
CODER_MODEL=gpt-4o               # OpenAI for code (different config in coder/)
```

A future enhancement (Tier 2 on the roadmap) is per-role provider config so the orchestrator can use Anthropic while the message classifier uses Ollama, etc. Today that requires running specialist agents with their own provider config (which they already do via their own env vars).

---

## Cost-Aware Defaults

If you're cost-conscious, the cheapest way to run BOB at reasonable quality:

```bash
BOB_LLM_PROVIDER=anthropic
BOB_MODEL=claude-haiku-4-5
BOB_LLM_MAX_TOKENS=2048
```

Or fully local (free after hardware):

```bash
BOB_LLM_PROVIDER=ollama
BOB_MODEL=qwen2.5:14b
BOB_LLM_TEMPERATURE=0.3
```

The tradeoff is tool-calling reliability. Cheaper Claude models (Haiku) are still excellent at tool calling. Local Qwen 14B is good but not great. If BOB seems to be calling tools incorrectly or getting confused, the first thing to try is a larger or more capable model.

---

## OpenAI-Compatible Backends (vLLM, LiteLLM, OpenRouter, LM Studio)

Any OpenAI-compatible endpoint works via the `openai` provider with `BOB_LLM_BASE_URL` set:

| Backend | Use case | Config |
|---|---|---|
| **vLLM** | Self-hosted high-throughput open models | `BOB_LLM_BASE_URL=http://vllm:8000/v1` |
| **LiteLLM proxy** | Unified gateway for many providers | `BOB_LLM_BASE_URL=http://litellm:4000` |
| **LM Studio** | Desktop GUI for local models | `BOB_LLM_BASE_URL=http://host.docker.internal:1234/v1` |
| **OpenRouter** | Hosted gateway with hundreds of models | `BOB_LLM_BASE_URL=https://openrouter.ai/api/v1` + real API key |

The model name (`BOB_MODEL`) must match what the endpoint serves. Check the endpoint's `/v1/models` to see options.

---

## Adding a New Provider

If you want to add Cohere, AI21, Mistral API, or any other LangChain-supported provider:

1. **Add the package** to `requirements.txt` (e.g., `langchain-cohere>=0.3.0`).
2. **Add a `_build_<provider>` function** in `app/llm.py` modeled on `_build_openai`. It should:
   - Lazy-import the LangChain package
   - Pull the API key from `BOB_LLM_API_KEY` or a provider-specific env var
   - Return a configured `ChatModel` instance
3. **Add a branch in `get_llm()`** for the new provider.
4. **Add an entry in `DEFAULT_MODELS`** with a sensible default.
5. **Add an entry in `check_provider_available()`** so `/llm/status` reports it.
6. **Add an entry in `validate_config()` in `config.py`** to check the required keys at startup.
7. **Update this doc** with the new provider's table row, recommended models, and honest tradeoffs.
8. **Test the quickstart against the new provider.** If tool calling breaks, document the limitations rather than shipping a broken integration.

The pattern is intentionally simple. Each provider is ~30 lines of code in `llm.py`.

---

## Honest Tradeoffs Summary

**Anthropic Claude:**
- ✅ Best tool calling
- ✅ Best reasoning for orchestration
- ❌ Most expensive
- ❌ Vendor lock-in unless you also configure a fallback

**OpenAI GPT:**
- ✅ Good tool calling
- ✅ Wide model selection
- ✅ Compatible with vLLM / LiteLLM / LM Studio for self-hosted
- ❌ Closed-source models
- ❌ Cost per token similar to Claude for top-tier models

**Ollama (local):**
- ✅ Free after hardware
- ✅ Total privacy
- ✅ No network dependency
- ❌ Tool calling is good, not great
- ❌ Requires real GPU for usable speed
- ❌ Smaller models (<14B) struggle with BOB's 35-tool toolkit

**The honest recommendation:** Start with Anthropic. Get BOB working end-to-end. Then experiment with other providers if cost or privacy matters more than tool-calling reliability.

---

*Yes Boss. Pick a provider. They all work. Some better than others. — BOB*
