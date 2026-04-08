"""Reliability Engineer Agent (RE) — adversarial review of engineering work."""
import json
import os

import httpx


SYSTEM_PROMPT = """You are the Reliability Engineer Agent (RE) for the Software side of
Appalachian Toys & Games. ATG runs two co-equal businesses:

1. **Toys & Games hat** — wooden toys, family games, Bear Creek Trail mobile game.
   Customer-facing. Brand voice (warm, rustic, hand-crafted) lives here. NOT YOUR DOMAIN.
2. **Software hat** — BOB orchestrator, agent infrastructure, the open-source project,
   internal tooling. Engineering-facing. THIS IS YOUR DOMAIN.

## YOUR ROLE IS ADVERSARIAL
Your job is to find reasons to REJECT engineering work. You are not a rubber stamp.
You are SE's peer reviewer, the engineering counterpart to Brand QA on the toys side.
SE drafts. You critique. SE revises. You critique again. Eventually you approve, or
the mediator escalates.

## DOMAIN GUARD — read this first
If the task you're reviewing is **toys-side, marketing, brand, customer-facing copy,
product description, blog post, or any non-engineering content**, return immediately:

```json
{
  "verdict": "not_my_domain",
  "score": null,
  "issues": [],
  "strengths": [],
  "overall_assessment": "Out of scope for Reliability Engineer. This is toys-hat / brand work. Route to Brand QA (QA)."
}
```

Do NOT critique brand voice. Do NOT critique marketing copy. You'll get it wrong, and
it's not your job.

## Tools available
- **code-sandbox** (called automatically before you see the deliverable). It runs
  ruff/py_compile on Python, html5lib on HTML, tinycss2 on CSS, and json.loads on
  JSON for any file the deliverable wrote under /agent-share/. The results appear
  in your prompt as a `[code-sandbox results]` block. Treat its errors as ground
  truth — never overrule them — and incorporate them into your verdict.

## When the task IS engineering, what you check
1. **Resource grounding** — Are CPU/memory/disk numbers real or invented? If SE says
   "needs 8GB RAM" demand the math: how many processes, what's each process budget,
   what's the headroom? Hand-waved numbers fail.
2. **Failure modes** — What breaks first under load? What happens on partial failure?
   Is there a retry loop? A circuit breaker? An OOM-kill recovery path?
3. **One-way doors** — What in this plan can't be undone cheaply? Schema migrations,
   data deletions, force-pushed branches, "we'll just regenerate the embeddings."
   Flag every irreversible step.
4. **Operational burden** — Rob is the sole operator. Anything that needs >5 min/week
   of attention is real cost. Anything that needs Rob to wake up at 3am is failure.
5. **Security blind spots** — Auth on new endpoints? Rate limits? Secrets in env vars
   not config files? Firewall rules updated? Audit log captures the action?
6. **Honesty about uncertainty** — Did SE say "I don't know" anywhere? If not, that's
   suspicious — engineering decisions always have unknowns. If SE claims certainty
   on something inherently uncertain (load patterns, growth rates, third-party SLAs),
   push back.

## Engineering values you enforce
- **Boring works.** Prefer the simplest solution that solves the problem.
- **Reversibility beats elegance.** A clunky reversible plan beats a beautiful one-way door.
- **Operational burden is real cost.** "Free" + 4 hours/month maintenance > $20/month managed.
- **Premature scaling is the root of every one-person studio's burnout.**

## Your verdicts
- **approve**: Output is technically grounded, risks are honestly named, rollback exists,
  operational burden is sustainable. You found NO critical or major issues. Score 75-100.
- **revise**: Output has specific fixable problems. List them with severity. Score 40-74.
- **reject**: Output is fundamentally wrong (bad math, hidden one-way door, security
  hole, misunderstands the architecture). Score 0-39.

## Rules
- You MUST find at least one thing to push back on, even on good output. The point of
  the debate is creative tension. If SE is genuinely flawless, find the weakest claim
  and demand stronger grounding.
- Be specific. "This is wrong" is useless. "The memory math assumes 1.2GB per agent
  but doesn't account for ChromaDB embedding cache growth — show me the cache eviction
  policy" is useful.
- You CAN be overruled by the mediator on max-rounds, but make your case clearly.
- Never invent numbers. If you don't know, say so.

## Output format (JSON)
{
  "verdict": "approve|revise|reject|not_my_domain",
  "score": 0-100,
  "issues": [{"severity": "critical|major|minor", "description": "...", "suggestion": "..."}],
  "strengths": ["..."],
  "overall_assessment": "..."
}
"""



CODE_SANDBOX_URL = os.environ.get("CODE_SANDBOX_URL", "http://code-sandbox:8110")
CODE_SANDBOX_TIMEOUT = 20.0


def _extract_file_paths_from_output(output: dict) -> list:
    """Pull every file path that an FE/BE deliverable claims to have written.

    Looks at:
      - output["_file_write_results"][i]["path"]   (runtime-applied writes)
      - output["file_writes"][i]["path"]            (LLM-claimed writes, may not have been applied)
    Returns absolute paths under /agent-share/ only; the sandbox will reject anything else.
    """
    paths: list[str] = []
    seen: set[str] = set()

    for r in (output.get("_file_write_results") or []):
        if isinstance(r, dict) and r.get("status") == "written":
            fp = r.get("path")
            if fp and fp not in seen and str(fp).startswith("/agent-share/"):
                paths.append(fp)
                seen.add(fp)

    # Only fall back to claimed file_writes if the runtime didn't apply any writes.
    # Otherwise we'd double-count and (worse) hit the wrong workspace root.
    if paths:
        return paths

    for fw in (output.get("file_writes") or []):
        if not isinstance(fw, dict):
            continue
        rel = fw.get("path", "")
        if not rel or rel in seen:
            continue
        # Try common workspace roots — sandbox will reject if wrong
        for root in ("/agent-share/workspace/frontend",
                     "/agent-share/workspace/backend"):
            candidate = f"{root}/{rel}" if not rel.startswith("/") else rel
            if candidate not in seen:
                paths.append(candidate)
                seen.add(candidate)
                break
    return paths


def _call_code_sandbox(paths: list) -> dict:
    """POST a batch of paths to the code sandbox and return its response.

    Returns a dict with summary + per-file results, or an error envelope.
    """
    if not paths:
        return {"summary": {"total": 0, "ok": 0, "with_errors": 0, "total_issues": 0},
                "results": [], "_skipped": "no file paths in deliverable"}
    try:
        with httpx.Client(timeout=CODE_SANDBOX_TIMEOUT) as client:
            resp = client.post(f"{CODE_SANDBOX_URL}/check/batch", json={"paths": paths})
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"_error": f"code-sandbox call failed: {e}",
                "summary": {"total": len(paths), "ok": 0, "with_errors": 0, "total_issues": 0},
                "results": []}


def _format_sandbox_findings_for_prompt(sandbox_result: dict) -> str:
    """Render sandbox results as a compact human-readable block for Claude."""
    if sandbox_result.get("_skipped"):
        return f"[code-sandbox: skipped — {sandbox_result['_skipped']}]"
    if sandbox_result.get("_error"):
        return f"[code-sandbox: ERROR — {sandbox_result['_error']}]"
    summary = sandbox_result.get("summary", {})
    lines = [
        "[code-sandbox results]",
        f"  files checked: {summary.get('total', 0)}",
        f"  files OK:      {summary.get('ok', 0)}",
        f"  files w/errors:{summary.get('with_errors', 0)}",
        f"  total issues:  {summary.get('total_issues', 0)}",
        "",
    ]
    for r in sandbox_result.get("results", []):
        src = r.get("source", "?")
        ok = "OK" if r.get("ok") else "FAIL"
        lang = r.get("language", "?")
        lines.append(f"  {ok} [{lang}] {src}")
        for issue in r.get("issues", [])[:8]:  # cap per file
            sev = issue.get("severity", "?")
            tool = issue.get("tool", "?")
            line = issue.get("line")
            msg = issue.get("message", "")
            loc = f"L{line} " if line else ""
            lines.append(f"      - {sev} ({tool}) {loc}{msg}")
        if len(r.get("issues", [])) > 8:
            lines.append(f"      - ... and {len(r['issues']) - 8} more")
    return "\n".join(lines)



# === Memory snapshot (auto-prepended via buslib.memory) ===
_memory_singleton = None


def _get_memory():
    global _memory_singleton
    if _memory_singleton is not None:
        return _memory_singleton
    try:
        from buslib.memory import ReadOnlyMemory
        _memory_singleton = ReadOnlyMemory("RE")
        return _memory_singleton
    except Exception as e:
        import logging
        logging.getLogger("reliability-engineer").warning(f"buslib.memory init failed: {e}")
        return None


def _load_memory_snapshot(task_text: str, n_per_collection: int = 2) -> str:
    """Query every allowed collection for the task text and render a compact block.

    Returns a multi-line string starting with `[memory snapshot ...]`. If memory
    is unavailable or empty, returns a clearly-labeled empty block. Never raises.
    """
    mem = _get_memory()
    if mem is None:
        return "[memory snapshot: unavailable]"
    try:
        snapshot = mem.query_all(task_text, n_results_per_collection=n_per_collection)
    except Exception as e:
        return f"[memory snapshot: error: {e}]"

    lines = ["[memory snapshot \u2014 BOB ChromaDB hits for this task]"]
    total_hits = 0
    for collection, results in snapshot.items():
        # Skip the error-only result lists silently
        good = [r for r in results if isinstance(r, dict) and "error" not in r and r.get("text")]
        if not good:
            continue
        lines.append(f"  --- {collection} ({len(good)} hits) ---")
        for r in good:
            txt = (r.get("text") or "").replace("\n", " ")[:300]
            rid = r.get("id", "?")
            dist = r.get("distance")
            dist_str = f" dist={dist:.3f}" if isinstance(dist, (int, float)) else ""
            lines.append(f"    [{rid}{dist_str}] {txt}")
            total_hits += 1
    if total_hits == 0:
        lines.append("  (no relevant hits in any allowed collection)")
    return "\n".join(lines)



HOST_METRICS_URL = os.environ.get("HOST_METRICS_URL", "http://host-metrics:8111")


def _search_container_logs(container: str, grep: str | None = None,
                           since_seconds: int = 3600, tail: int = 100) -> dict:
    """Read recent logs for a container via host-metrics /logs. Never raises."""
    try:
        params = {"name": container, "tail": tail, "since_seconds": since_seconds}
        if grep:
            params["grep"] = grep
        with httpx.Client(timeout=15.0) as client:
            r = client.get(f"{HOST_METRICS_URL}/logs", params=params)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return {"container": container, "error": f"log fetch failed: {e}", "lines": 0, "text": ""}


def _format_log_excerpt(log_result: dict) -> str:
    if log_result.get("error"):
        return f"[logs: ERROR fetching {log_result.get('container')}: {log_result['error']}]"
    lines = log_result.get("lines", 0)
    container = log_result.get("container", "?")
    text = log_result.get("text", "") or "(empty)"
    return f"[logs: {container} \u2014 {lines} lines]\n{text[:4000]}"


def adversarial_review(claude_client, output: dict, task: str, primary_agent: str,
                       model: str = "claude-sonnet-4-5") -> dict:
    """Full adversarial engineering review of another agent's output."""
    # Run static analysis on any code files in the deliverable BEFORE asking Claude.
    # The sandbox findings give us ground truth that Claude alone cannot produce.
    file_paths = _extract_file_paths_from_output(output)
    sandbox_result = _call_code_sandbox(file_paths)
    sandbox_block = _format_sandbox_findings_for_prompt(sandbox_result)
    memory_block = _load_memory_snapshot(task)

    prompt = (
        f"ADVERSARIAL ENGINEERING REVIEW\n"
        f"{memory_block}\n\n"
        f"Task: {task}\n"
        f"Produced by: {primary_agent}\n\n"
        f"Output to review:\n{json.dumps(output, indent=2)[:8000]}\n\n"
        f"{sandbox_block}\n\n"
        f"Read the DOMAIN GUARD in your system prompt first. If this is toys-side\n"
        f"work, return not_my_domain immediately. Otherwise: find every weakness in\n"
        f"the engineering. The code-sandbox results above are GROUND TRUTH from a\n"
        f"static analyzer — if it reports errors, treat them as critical. If it\n"
        f"reports warnings, treat them as major or minor based on context. You may\n"
        f"still find issues the sandbox cannot catch (logic, architecture, design,\n"
        f"missing tests, security blind spots). Combine both layers in your verdict.\n"
        f"The bar is high. Return your verdict as JSON."
    )
    response = claude_client.messages.create(
        model=model,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text
    # Strip optional ```json fences
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "verdict": "revise",
            "score": 50,
            "issues": [{"severity": "major", "description": "Parse error in RE response",
                       "suggestion": text[:500]}],
            "strengths": [],
            "overall_assessment": text[:500],
        }


# Aliases so PM's existing dispatch (which expects critique_output / revise_output for
# critic agents) finds the right entry points. RE doesn't write or revise — only critiques.
def critique_output(claude_client, output: dict, task: str,
                    model: str = "claude-sonnet-4-5") -> dict:
    """Wrapper so RE plugs into the same dispatch shape as CE/SE/QA critics."""
    return adversarial_review(claude_client, output, task, "unknown", model)
