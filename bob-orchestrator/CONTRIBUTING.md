# Contributing to BOB

Yes Boss. You want to help. Here's the deal.

BOB is a sardonic, self-hosted multi-agent AI orchestrator built for solo founders. The goal is **production-grade for one person**, not enterprise. Keep that in mind for every contribution.

---

## What to Contribute

**Highest-leverage contributions** (please open an issue first to coordinate):

1. **Model adapters.** BOB runs Claude Opus by default. Adapters for other tool-calling models (GPT-4 class, Llama 3.3, Qwen 2.5, DeepSeek) are top priority. The agent should be model-agnostic by mid-launch.
2. **MCP integrations.** New MCP servers, MCP tool examples, or MCP transport improvements. See [`MCP_INTEGRATION.md`](MCP_INTEGRATION.md).
3. **Eval harness.** A simple "agent task pass/fail" suite with public baselines so people can compare BOB to other frameworks honestly.
4. **Specialist agent templates.** Drop-in agent implementations for common roles (engineer, marketer, researcher, etc.) that BOB can delegate to.
5. **K8s helm chart.** For people running BOB beyond a single-host home server.
6. **Docs.** Especially the "first 30 minutes" experience.

**Lower-leverage but welcome:**

- Bug fixes (with a test where applicable)
- Tool additions to the orchestrator (must include risk-level registration in `firewall.py`)
- Logging improvements
- New ChromaDB collection schemas
- Additional voice provider adapters

**Please don't send PRs for:**

- Removing the personality. The sardonic tone is load-bearing. If you want a neutral assistant, use Claude directly.
- Adding telemetry that phones home. BOB is self-hosted by design.
- Renaming things to be "more enterprise." This isn't an enterprise product.
- Replacing LangGraph with a different framework. The state graph model is intentional.
- Removing the firewall layer or relaxing the risk gates without a security review.
- Switching the license away from MIT.

---

## Setup for Local Development

Prerequisites:
- Docker + Docker Compose
- An Anthropic API key (or alternative once adapters land)
- Python 3.12+ (for running tests outside Docker)

```bash
git clone https://github.com/[username]/bob.git
cd bob

# Quickstart (recommended for first-time contributors)
cd quickstart
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
docker compose up --build

# Full stack (more services, more realistic)
cd ..
cp .env.example .env
docker compose up --build
```

The quickstart brings up BOB plus two example specialist agents (researcher + coder) so you can see the orchestration pattern in 10 minutes. The full stack adds the message bus, the debate arena, the voice interface, and the monitoring services.

Once it's running, hit `http://localhost:8100/health` to confirm BOB is alive. Then `POST /chat` with a message and watch what he does.

---

## Code Style

- **Python:** PEP 8 with 100-character line limit. Use `flake8` (not `black` — the codebase has intentional formatting choices that black would fight). Imports sorted by source: stdlib → third-party → local.
- **Async-first.** New tools should be `async def` unless they have a specific reason to be sync. The graph is async; sync tools work but they block the event loop briefly.
- **Type hints.** Required on public functions. Optional on private helpers.
- **Docstrings.** Required on every public tool. The docstring becomes the LLM-facing description, so write it for the model, not just the human reader.
- **No global mutable state** outside of the existing module-level singletons (`_graph`, `_pending_tasks`, etc.). Add to those if you must, but prefer dependency injection.
- **Errors.** Raise on programmer errors. Return structured error dicts on user errors (`{"error": "...", "detail": "..."}`).

---

## Testing

There's no formal test suite yet (this is one of the things contributors can help with). For now:

- **Manual smoke test.** Bring up the quickstart, send a chat message, watch the output.
- **Linting.** Run `flake8 app/ --max-line-length 120 --ignore=E501,W503,E402,F401` and make sure it's clean.
- **Compile check.** `python -m py_compile app/*.py` should succeed for every modified file.
- **No regressions in `/health`, `/status`, `/mcp/status`.** All three endpoints should return 200 with valid JSON after your change.

If you're adding a tool, the bare minimum is:
1. The tool function with a clear docstring
2. An entry in `firewall.py:TOOL_REGISTRY` with the appropriate risk level
3. The tool added to `_TOOLS` in `tools.py`
4. A manual test that the tool actually does what its docstring claims

If you're adding a security-relevant change (firewall, auth, rate limiting), please also write a brief threat-model note in the PR description: what attack does this prevent, what's the blast radius if it fails, and how does the existing audit log capture it?

---

## Pull Request Process

1. **Open an issue first** for anything non-trivial. Describe what you want to do and why. This avoids the heartbreak of building something nobody will merge.
2. **Branch from `main`.** Use a descriptive branch name (`feat/llama-adapter`, `fix/firewall-injection-edge-case`).
3. **Keep PRs small.** One feature or one bug per PR. Big PRs are hard to review and harder to revert.
4. **Write a real PR description.** What's the change, why does it matter, what's the test plan, what could break.
5. **Update docs.** If your change affects how BOB is used or configured, update the README, `MCP_INTEGRATION.md`, or relevant doc.
6. **Don't change the personality.** Seriously.
7. **No co-author tags from AI assistants.** It's fine to use Claude / GPT / whatever to help you write code. Just don't put `Co-authored-by: Claude` in the commit. The AI didn't write the PR — you did.

PRs are reviewed when I (Rob) have time. BOB is a side project on top of running a one-person game studio. Patience appreciated.

---

## Reporting Bugs

1. **Search existing issues first.** Don't file a duplicate.
2. **Provide a minimal reproduction.** "BOB doesn't work" is not actionable. "BOB crashes when I send a message containing a code block with a Python comment that has a `#!` shebang line" is actionable.
3. **Include version info.** Output of `git rev-parse HEAD`, `docker --version`, `python --version`, and the relevant section of `requirements.txt`.
4. **Logs.** BOB writes structured JSON logs. Pipe through `jq` and grab the relevant entries.
5. **What you expected vs. what happened.** Both, explicitly.

---

## Reporting Security Issues

**Do not open a public issue for security vulnerabilities.** See [`SECURITY.md`](SECURITY.md) for the disclosure process.

---

## Code of Conduct

Don't be a jerk. Disagree with the design decisions, push back on the architecture, suggest improvements — all welcome. Personal attacks, harassment, or bad-faith engagement will get you blocked from the repo.

The maintainer (Rob) is one human. He has bad days. If a response feels short or terse, assume it's because he's solo and tired, not because he's mad at you.

---

## Recognition

Contributors get listed in the README. If your PR materially improves BOB, you're in. No quotas, no tiers, no contributor agreements. Just do good work and credit gets given.

---

*Thanks for helping. BOB will be sardonic about your pull request, but he'll appreciate it. — Rob*
