"""Back-End Engineer Agent (BE) — APIs, services, databases, server code, integrations."""
import json
import re
import os
from datetime import datetime
from pathlib import Path


WORKSPACE = Path("/agent-share/workspace/backend")
PROPOSALS_DIR = WORKSPACE / "proposals"
DELIVERABLES_DIR = WORKSPACE / "deliverables"
# Read-only mounts of real source trees for context
BOB_SOURCE_RO = Path("/bob-src")
DEBATE_SOURCE_RO = Path("/debate-src")



def _extract_json(text: str):
    """Strip markdown code fences from a Claude response and parse as JSON.

    Handles three cases:
      1. Bare JSON                          -> parsed directly
      2. ```json ... ```  fenced            -> fences stripped, then parsed
      3. Preamble + ```json ... ``` fenced  -> preamble stripped, then fences,
         then parsed. Falls back to a first-{ / last-} slice if all else fails.
    """
    import json as _j
    s = text.strip()
    # Step 1: try a direct parse on the whole thing
    try:
        return _j.loads(s)
    except Exception:
        pass
    # Step 2: strip leading code fence (with or without language tag)
    s2 = s
    if s2.startswith("```json"):
        s2 = s2[7:].lstrip("\n")
    elif s2.startswith("```"):
        s2 = s2[3:].lstrip("\n")
    if s2.endswith("```"):
        s2 = s2[:-3].rstrip()
    try:
        return _j.loads(s2)
    except Exception:
        pass
    # Step 3: find the first { and the LAST } in the original text and parse that slice
    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        try:
            return _j.loads(s[start:end + 1])
        except Exception:
            pass
    # Last resort: re-raise so the caller's existing fallback path handles it
    return _j.loads(s2)
import os as _os_for_sandbox
import httpx as _httpx_for_sandbox

CODE_SANDBOX_URL = _os_for_sandbox.environ.get("CODE_SANDBOX_URL", "http://code-sandbox:8110")
CODE_SANDBOX_TIMEOUT = 30.0


def _sandbox_call_batch(paths: list) -> dict:
    """POST a batch of file paths to the code sandbox. Returns a dict (never raises)."""
    if not paths:
        return {"summary": {"total": 0, "ok": 0, "with_errors": 0, "total_issues": 0},
                "results": [], "_skipped": "no file paths to test"}
    try:
        with _httpx_for_sandbox.Client(timeout=CODE_SANDBOX_TIMEOUT) as client:
            resp = client.post(f"{CODE_SANDBOX_URL}/check/batch", json={"paths": paths})
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"_error": f"code-sandbox call failed: {e}",
                "summary": {"total": len(paths), "ok": 0, "with_errors": 0, "total_issues": 0},
                "results": []}


def _sandbox_has_errors(sandbox_result: dict) -> bool:
    """True if any file in the sandbox response had an error-severity issue."""
    if not isinstance(sandbox_result, dict):
        return False
    if sandbox_result.get("_error"):
        return False  # sandbox itself was unreachable; not the agent's fault
    for r in sandbox_result.get("results", []):
        if not isinstance(r, dict):
            continue
        if r.get("ok") is False:
            return True
        for issue in r.get("issues", []):
            if isinstance(issue, dict) and issue.get("severity") == "error":
                return True
    return False


def _sandbox_render_for_repair(sandbox_result: dict) -> str:
    """Render sandbox findings as a compact text block for the repair prompt."""
    if sandbox_result.get("_error"):
        return f"[code-sandbox error: {sandbox_result['_error']}]"
    lines = ["[code-sandbox findings]"]
    summary = sandbox_result.get("summary", {})
    lines.append(f"  files checked: {summary.get('total', 0)}, "
                 f"ok: {summary.get('ok', 0)}, "
                 f"with errors: {summary.get('with_errors', 0)}")
    for r in sandbox_result.get("results", []):
        src = r.get("source", "?")
        ok = "OK" if r.get("ok") else "FAIL"
        lang = r.get("language", "?")
        lines.append(f"  {ok} [{lang}] {src}")
        for issue in r.get("issues", [])[:10]:
            sev = issue.get("severity", "?")
            tool = issue.get("tool", "?")
            line = issue.get("line")
            msg = issue.get("message", "")
            loc = f"L{line} " if line else ""
            lines.append(f"      - {sev} ({tool}) {loc}{msg}")
    return "\n".join(lines)


def _written_paths(write_results: list) -> list:
    """Extract the absolute paths of files that were actually written to disk."""
    return [
        r["path"]
        for r in (write_results or [])
        if isinstance(r, dict) and r.get("status") == "written" and r.get("path")
    ]


def _self_test_loop(claude_client, model: str, task: str, original_text: str,
                     original_result: dict, write_results: list,
                     max_tokens: int) -> tuple[dict, list, dict, int]:
    """Run sandbox on written files. If errors, do ONE repair round.

    Returns (final_result_dict, final_write_results, final_sandbox_result, attempts).
    """
    paths = _written_paths(write_results)
    sandbox_result = _sandbox_call_batch(paths)

    # No errors, or sandbox itself unreachable: skip repair
    if not _sandbox_has_errors(sandbox_result):
        return original_result, write_results, sandbox_result, 1

    # One repair round
    findings_block = _sandbox_render_for_repair(sandbox_result)
    repair_msg = (
        f"Original task:\n{task}\n\n"
        f"Your previous output had errors caught by the static-analysis sandbox:\n\n"
        f"{findings_block}\n\n"
        f"Your previous JSON response was:\n{original_text[:6000]}\n\n"
        f"Produce a CORRECTED JSON response in the same schema as before. Fix every\n"
        f"error reported above. Keep the structure identical but update the file_writes\n"
        f"contents to address the issues. Return only the JSON."
    )

    try:
        repair_resp = claude_client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": repair_msg}],
        )
        repair_text = repair_resp.content[0].text
        try:
            repaired = _extract_json(repair_text)
        except Exception:
            # Repair parse failed — keep originals, mark failure
            original_result["_self_test_repair_parse_failed"] = True
            return original_result, write_results, sandbox_result, 2

        new_writes = _apply_file_writes(repaired.get("file_writes", []))
        # Merge: keep top-level fields from repaired, but preserve some metadata
        merged = dict(repaired)
        # Re-test the repaired files
        repaired_sandbox = _sandbox_call_batch(_written_paths(new_writes))
        return merged, new_writes, repaired_sandbox, 2
    except Exception as e:
        original_result["_self_test_repair_error"] = str(e)
        return original_result, write_results, sandbox_result, 2



# === Memory snapshot (auto-prepended via buslib.memory) ===
_memory_singleton = None


def _get_memory():
    global _memory_singleton
    if _memory_singleton is not None:
        return _memory_singleton
    try:
        from buslib.memory import ReadOnlyMemory
        _memory_singleton = ReadOnlyMemory("BE")
        return _memory_singleton
    except Exception as e:
        import logging
        logging.getLogger("be-engineer").warning(f"buslib.memory init failed: {e}")
        return None


def _load_memory_snapshot(task_text: str, n_per_collection: int = 2) -> str:
    """Query every allowed collection for the task text and render a compact block."""
    mem = _get_memory()
    if mem is None:
        return "[memory snapshot: unavailable]"
    try:
        snapshot = mem.query_all(task_text, n_results_per_collection=n_per_collection)
    except Exception as e:
        return f"[memory snapshot: error: {e}]"

    lines = ["[memory snapshot \u2014 BOB ChromaDB hits for this task]"]
    total = 0
    for collection, results in snapshot.items():
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
            total += 1
    if total == 0:
        lines.append("  (no relevant hits in any allowed collection)")
    return "\n".join(lines)


SYSTEM_PROMPT = """You are the Back-End Engineer Agent (BE) for Appalachian Toys & Games.
You build and modify server-side code: APIs, message handlers, database schemas,
LangGraph nodes, agent containers, integrations with external services. You ship
working code, not just suggestions.

## Operating reality
- ATG runs on don-quixote, a single Ubuntu home server. Single-node, single-operator.
- The two main back-end codebases are:
  1. BOB orchestrator (FastAPI + LangGraph + ChromaDB), READ-ONLY at /bob-src/
  2. Debate Arena agents (FastAPI services on a shared message bus), READ-ONLY at /debate-src/
- The shared message bus is a FastAPI + SQLite service at message-bus:8585.
- You write all changes to /agent-share/workspace/backend/proposals/ for human review.
  Anything in proposals/ is *staged* — Rob promotes it to live by hand. This is by design.
- You may write reference deliverables (specs, schemas, ADRs) to
  /agent-share/workspace/backend/deliverables/.
- For larger changes you may request additional repo access in your output's
  `access_requests` field. Do not assume access you have not been granted.

## Back-End engineering values (in priority order)
1. **Boring works.** SQLite over Postgres until SQLite breaks. FastAPI over heavier
   frameworks until you need them. Match tooling to the actual problem.
2. **Reversibility.** Migrations should be reversible. Schema changes should be additive
   first, breaking only after a migration window. Flag one-way doors explicitly.
3. **Observability before optimization.** Log enough to debug a 3am incident. Metrics
   beat guesses.
4. **Single points of failure are acceptable** when the blast radius is small and recovery
   is fast. Call them out, don't hide them.
5. **Consistency with the existing codebase.** Match the patterns already in BOB and the
   debate agents. Don't import a new framework when the existing one works.
6. **Operator time is the scarcest resource.** A "free" solution that needs constant
   manual attention is more expensive than a managed service.

## Self-test loop
After you write files to `proposals/`, the runtime automatically calls the
**code-sandbox** static analyzer on them (ruff for Python, html5lib for HTML,
tinycss2 for CSS, json.loads for JSON). If any file has an *error*-severity
issue, you get exactly ONE repair round: the runtime sends you the findings and
asks for a corrected response in the same JSON schema. Use this — it is your
chance to fix bugs before RE sees the deliverable. The final sandbox results
end up in `_self_test_results` for downstream critics.

Treat this as your build step. Aim to ship clean code on the first attempt;
the repair round is a safety net, not a substitute for getting it right.

## When BUILDING / IMPLEMENTING back-end work, return JSON:
{
  "title": "...",
  "summary": "1-2 sentence answer first, then everything else",
  "approach": "what you built and why this approach",
  "file_writes": [
    {"path": "proposals/<feature>/route.py",      "content": "...", "purpose": "..."},
    {"path": "proposals/<feature>/migration.sql", "content": "...", "purpose": "..."}
  ],
  "test_plan": "how to verify this works before promoting to production",
  "promotion_steps": ["concrete steps to apply proposals/<feature>/ to live code"],
  "rollback_plan": "how to undo if something breaks",
  "risks": [{"level": "low|medium|high", "description": "...", "mitigation": "..."}],
  "open_questions": ["..."],
  "access_requests": ["e.g. RW on /bob-src to apply directly, with rationale"],
  "confidence": 0.0,
  "things_i_dont_know": ["..."]
}

## file_writes path rules
- Paths MUST be relative to /agent-share/workspace/backend/
- Paths starting with `proposals/` or `deliverables/` are allowed.
- Absolute paths, `..`, or paths outside the workspace will be REJECTED by the runtime.
- You may include as many files as the work requires. Each file gets its full content.

## When CRITIQUING another agent's back-end output, focus on:
- Does the code actually run? Are imports correct? Is the API contract sane?
- Database choices — schema correctness, indexes, migration safety
- Error handling — what happens at 3am when this fails?
- Security — input validation, auth, secrets, SQL injection, command injection
- Operational burden — logs, metrics, deploy story, rollback story
- Consistency with existing BOB / debate-arena patterns
- Where is the author overconfident or hand-waving?

Be specific. Be honest. Push back when something is wrong. If you don't know, say so.
Never invent API behavior. If you're guessing about the existing code, label it as a guess.
"""


def _safe_workspace_path(rel_path: str) -> Path | None:
    if not rel_path or rel_path.startswith("/") or ".." in Path(rel_path).parts:
        return None
    target = (WORKSPACE / rel_path).resolve()
    try:
        target.relative_to(WORKSPACE.resolve())
    except ValueError:
        return None
    rel = target.relative_to(WORKSPACE.resolve())
    if rel.parts and rel.parts[0] not in ("proposals", "deliverables"):
        return None
    return target


def _apply_file_writes(file_writes: list) -> list:
    results = []
    if not isinstance(file_writes, list):
        return results
    for fw in file_writes:
        if not isinstance(fw, dict):
            results.append({"status": "rejected", "error": "not a dict"})
            continue
        rel = fw.get("path", "")
        content = fw.get("content", "")
        target = _safe_workspace_path(rel)
        if target is None:
            results.append({"path": rel, "status": "rejected",
                            "error": "path outside allowed workspace areas"})
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            results.append({"path": str(target), "status": "written",
                            "bytes": len(content.encode("utf-8"))})
        except Exception as e:
            results.append({"path": rel, "status": "error", "error": str(e)})
    return results


def execute_writing(claude_client, task: str, model: str = "claude-sonnet-4-5") -> dict:
    memory_block = _load_memory_snapshot(task)
    user_message = f"{memory_block}\n\n{task}"
    response = claude_client.messages.create(
        model=model,
        max_tokens=16384,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    text = response.content[0].text
    try:
        result = _extract_json(text)
    except json.JSONDecodeError:
        result = {
            "title": task[:100],
            "summary": text[:300],
            "_raw": text,
            "_parse_error": True,
            "file_writes": [],
        }

    write_results = _apply_file_writes(result.get("file_writes", []))

    # Self-test: run code-sandbox on what we wrote, do one repair round if errors
    result, write_results, sandbox_result, attempts = _self_test_loop(
        claude_client, model, task, text, result, write_results, max_tokens=16384,
    )
    result["_file_write_results"] = write_results
    result["_self_test_results"] = sandbox_result
    result["_self_test_attempts"] = attempts

    DELIVERABLES_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_ " else "" for c in task[:40]).strip().replace(" ", "_")
    path = DELIVERABLES_DIR / f"BE_{safe}_{ts}.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    result["_file_path"] = str(path)
    return result


def critique_output(claude_client, output: dict, task: str,
                    model: str = "claude-sonnet-4-5") -> dict:
    prompt = (
        f"You are the Back-End Engineer Agent (BE) for Appalachian Toys & Games.\n"
        f"Another agent produced this output for: {task}\n\n"
        f"Output to critique:\n{json.dumps(output, indent=2)[:8000]}\n\n"
        f"Focus on CORRECTNESS, ERROR HANDLING, SECURITY, and OPERATIONAL BURDEN.\n"
        f"Find the WEAKEST back-end point and push back specifically. Be concrete.\n\n"
        f"Respond with JSON:\n"
        f'{{"verdict": "approve|revise|reject", '
        f'"weakest_point": "...", '
        f'"specific_feedback": "...", '
        f'"missing_considerations": [...], '
        f'"confidence": 0.0}}'
    )
    response = claude_client.messages.create(
        model=model, max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        return _extract_json(response.content[0].text)
    except json.JSONDecodeError:
        return {"verdict": "revise", "weakest_point": "Parse error",
                "specific_feedback": response.content[0].text,
                "missing_considerations": [], "confidence": 0.5}


def revise_output(claude_client, original: dict, critiques: list, task: str,
                  model: str = "claude-sonnet-4-5") -> dict:
    critique_text = "\n\n".join([
        f"From {c.get('from_critic', 'unknown')}: {json.dumps(c)}" for c in critiques
    ])
    prompt = (
        f"You are the Back-End Engineer Agent (BE) for Appalachian Toys & Games.\n"
        f"You produced this output for: {task}\n\n"
        f"Your output:\n{json.dumps(original, indent=2)[:8000]}\n\n"
        f"You received these critiques:\n{critique_text}\n\n"
        f"Revise to address valid critiques. Push back on critiques you disagree with —\n"
        f"explain why technically. Return revised JSON in the same format, including\n"
        f"updated file_writes if file content needs to change."
    )
    response = claude_client.messages.create(
        model=model, max_tokens=16384,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        result = _extract_json(response.content[0].text)
    except json.JSONDecodeError:
        return {"revised_output": response.content[0].text, "_parse_error": True}

    write_results = _apply_file_writes(result.get("file_writes", []))
    result["_file_write_results"] = write_results
    return result
