"""Systems Engineer Agent (SE) — infrastructure architecture, resource modeling, deployment planning."""
import json
import os

import httpx
from datetime import datetime
from pathlib import Path




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
HOST_METRICS_URL = os.environ.get("HOST_METRICS_URL", "http://host-metrics:8111")
HOST_METRICS_TIMEOUT = 10.0


def _call_host_metrics() -> dict:
    """GET /summary from the host-metrics sidecar. Returns the parsed dict or an error envelope."""
    try:
        with httpx.Client(timeout=HOST_METRICS_TIMEOUT) as client:
            resp = client.get(f"{HOST_METRICS_URL}/summary")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"_error": f"host-metrics call failed: {e}"}


def _format_host_metrics_for_prompt(m: dict) -> str:
    """Render host metrics as a compact ground-truth block for Claude."""
    if not m or m.get("_error"):
        return f"[host-metrics: ERROR — {m.get('_error', 'no data')}]"
    lines = ["[host-metrics — don-quixote ground truth]"]

    sysm = m.get("system", {})
    if isinstance(sysm, dict) and "cpu" in sysm:
        cpu = sysm["cpu"]
        mem = sysm["memory"]
        swap = sysm["swap"]
        lines.append(f"  cpu: {cpu['percent_now']}% now, "
                     f"{cpu['cores_logical']} logical cores ({cpu['cores_physical']} physical), "
                     f"load 1m={cpu['load_avg']['1m']} 5m={cpu['load_avg']['5m']} 15m={cpu['load_avg']['15m']}, "
                     f"per-core 1m={cpu['load_per_core_1m']}")
        lines.append(f"  memory: {mem['used_gb']}/{mem['total_gb']} GB used "
                     f"({mem['percent']}%), available {mem['available_gb']} GB")
        if swap.get("total_gb", 0) > 0:
            lines.append(f"  swap: {swap['used_gb']}/{swap['total_gb']} GB used ({swap['percent']}%)")
        lines.append(f"  uptime: {sysm.get('uptime_days', '?')} days")

    disk = m.get("disk", {})
    mounts = disk.get("mounts", []) if isinstance(disk, dict) else []
    if mounts:
        lines.append("  disks:")
        for mt in mounts:
            lines.append(f"    {mt['mountpoint']:<25} {mt['used_gb']}/{mt['total_gb']} GB "
                         f"({mt['percent']}%) [{mt['fstype']}]")

    containers = m.get("containers", {})
    clist = containers.get("containers", []) if isinstance(containers, dict) else []
    cstats = m.get("container_stats", {})
    statlist = cstats.get("containers", []) if isinstance(cstats, dict) else []
    stats_by_name = {c["name"]: c for c in statlist if "name" in c and "error" not in c}

    if clist:
        lines.append(f"  containers: {len(clist)} running")
        for c in clist[:30]:
            name = c["name"]
            st = stats_by_name.get(name, {})
            if "cpu_pct" in st:
                lines.append(f"    {name:<35} {c['state']:<10} "
                             f"cpu={st['cpu_pct']}% mem={st['mem_used_mb']} MB ({st.get('mem_pct', 0)}%)")
            else:
                lines.append(f"    {name:<35} {c['state']:<10} (no stats)")
        if len(clist) > 30:
            lines.append(f"    ... and {len(clist) - 30} more")

    return "\n".join(lines)



# === Config snapshot ===
# Read-only mounts of source-of-truth config files. Set in docker-compose.yml.
CONFIG_SOURCES = [
    ("debate-arena/docker-compose.yml", Path("/configs/debate-arena/docker-compose.yml")),
    ("bob-orchestrator/docker-compose.yml", Path("/configs/bob-orchestrator/docker-compose.yml")),
    ("bob-orchestrator/Dockerfile", Path("/configs/bob-orchestrator/Dockerfile")),
    ("cloudflared/config.yml", Path("/configs/cloudflared/config.yml")),
]
MAX_CONFIG_BYTES = 30_000  # per file


def _load_config_snapshot() -> str:
    """Return a fenced text block with the contents of the configured source files.

    Each file is read at execute time so the snapshot reflects the live config,
    not what was baked into the image. Files larger than MAX_CONFIG_BYTES are
    truncated with a marker. Missing files are noted but do not raise.
    """
    parts = ["[config snapshot \u2014 source-of-truth files on don-quixote]"]
    for label, path in CONFIG_SOURCES:
        if not path.exists():
            parts.append(f"# {label}: NOT FOUND ({path})")
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            parts.append(f"# {label}: read error: {e}")
            continue
        if len(text) > MAX_CONFIG_BYTES:
            text = text[:MAX_CONFIG_BYTES] + "\n# ... truncated ...\n"
        parts.append(f"# === {label} ({len(text)} chars) ===")
        parts.append(text)
    return "\n".join(parts)


SYSTEM_PROMPT = """You are the Systems Engineer Agent (SE) for Appalachian Toys & Games.
You review infrastructure decisions, model resource trade-offs, plan deployments, and assess
operational risk for a one-person game studio running a home server (don-quixote) plus
public-facing services.

## Tools available
- **config snapshot** (also injected automatically). The actual contents of
  `~/debate-arena/docker-compose.yml`, `~/bob-orchestrator/docker-compose.yml`,
  `~/bob-orchestrator/Dockerfile`, and `~/cloudflared/config.yml` are dropped
  into your prompt as a `[config snapshot]` block. Quote them directly when
  you need to reference exact service names, port mappings, env vars, or
  cloudflared ingress rules. Don't guess about what's in compose — read it.
- **host-metrics** (called automatically before you see the task). It runs on a
  sidecar with read-only mounts of the host /proc, /sys, and /. It returns
  the actual current CPU%, memory usage, disk usage per mount, and per-container
  CPU and memory for every running container on don-quixote. The numbers appear
  in your prompt as a `[host-metrics — don-quixote ground truth]` block. Use
  these numbers — never invent CPU/memory/disk values. If host-metrics is
  unavailable, say so explicitly in `things_i_dont_know`.

## Operating reality (always relevant)
- don-quixote is a single Ubuntu home server, NOT a cluster
- Currently runs: BOB orchestrator (LangGraph + Claude), 4 debate agents, ChromaDB,
  message bus (FastAPI + SQLite), voice service (Deepgram + ElevenLabs), public website,
  Cloudflare Tunnel, Jellyfin media server
- APScheduler uses a SQLite jobstore — single-node ONLY, no horizontal scaling
- Rob is the sole operator. Anything you recommend, he has to maintain alone.
- The architecture is "BOB recommends, the human decides." Same applies to you.

## Engineering values (in priority order)
1. **Boring works.** Prefer the simplest thing that solves the problem. SQLite over Postgres
   over distributed DBs. Docker compose over k8s until you actually need k8s.
2. **Reversibility.** Decisions you can undo cheaply are better than decisions you can't.
   Flag anything that's a one-way door.
3. **Operational burden is real cost.** A "free" solution that needs 4 hours of maintenance
   per month is more expensive than a $20/month managed service.
4. **Single points of failure are acceptable** when the blast radius is small and recovery
   is fast. Call them out, don't hide them.
5. **Premature optimization is the root of all evil. Premature scaling is the root of every
   one-person studio's burnout.**

## When ANALYZING / DESIGNING infrastructure, return JSON:
{
  "title": "...",
  "recommendation": "yes | no | conditional",
  "summary": "1-2 sentence answer first, then everything else",
  "resource_impact": {
    "cpu": "...",
    "memory": "...",
    "disk": "...",
    "network": "..."
  },
  "trade_offs": [{"option": "...", "pros": [...], "cons": [...]}],
  "risks": [{"level": "low|medium|high", "description": "...", "mitigation": "..."}],
  "next_steps": ["..."],
  "rollback_plan": "...",
  "confidence": 0.0,
  "things_i_dont_know": ["..."]
}

## When CRITIQUING another agent's output, focus on:
- Is the recommendation grounded in actual server capacity, or is it hand-waving?
- Are the resource numbers real or made up?
- Is there a one-way door hidden in the plan?
- Is the operator's time accounted for?
- What would break first under load, and is the failure recoverable?
- Where is the author overconfident?

Be specific. Be honest. Push back when something is wrong. If you don't know, say so.
Never invent numbers. If you're estimating, label it as an estimate.
"""



# === Memory snapshot (auto-prepended via buslib.memory) ===
_memory_singleton = None


def _get_memory():
    global _memory_singleton
    if _memory_singleton is not None:
        return _memory_singleton
    try:
        from buslib.memory import ReadOnlyMemory
        _memory_singleton = ReadOnlyMemory("SE")
        return _memory_singleton
    except Exception as e:
        import logging
        logging.getLogger("sys-engineer").warning(f"buslib.memory init failed: {e}")
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


def execute_writing(claude_client, task: str, model: str = "claude-sonnet-4-5") -> dict:
    """Produce an infrastructure analysis / recommendation for a task."""
    metrics = _call_host_metrics()
    metrics_block = _format_host_metrics_for_prompt(metrics)
    config_block = _load_config_snapshot()
    memory_block = _load_memory_snapshot(task)
    user_message = f"{memory_block}\n\n{config_block}\n\n{metrics_block}\n\n{task}"
    response = claude_client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    text = response.content[0].text
    try:
        result = _extract_json(text)
    except json.JSONDecodeError:
        result = {
            "title": task[:100],
            "recommendation": "conditional",
            "summary": text[:300],
            "_raw": text,
            "_parse_error": True,
        }

    output_dir = Path("/agent-share/workspace/engineering")
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_ " else "" for c in task[:40]).strip().replace(" ", "_")
    path = output_dir / f"SE_analysis_{safe}_{ts}.json"
    with open(path, "w") as f:
        json.dump(result, f, indent=2)
    result["_file_path"] = str(path)
    return result


def critique_output(claude_client, output: dict, task: str,
                    model: str = "claude-sonnet-4-5") -> dict:
    """Critique another agent's infrastructure output."""
    metrics = _call_host_metrics()
    metrics_block = _format_host_metrics_for_prompt(metrics)
    config_block = _load_config_snapshot()
    memory_block = _load_memory_snapshot(task)
    prompt = (
        f"You are the Systems Engineer Agent (SE) for Appalachian Toys & Games.\n"
        f"{memory_block}\n\n"
        f"{config_block}\n\n"
        f"{metrics_block}\n\n"
        f"Another agent produced this output for: {task}\n\n"
        f"Output to critique:\n{json.dumps(output, indent=2)}\n\n"
        f"Focus on TECHNICAL CORRECTNESS, RESOURCE REALISM, RISK, and OPERATIONAL BURDEN.\n"
        f"Are the numbers grounded? Is there a hidden one-way door? What breaks first?\n"
        f"Find the WEAKEST technical point and push back specifically. Be concrete.\n\n"
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
    """Revise an analysis based on critiques."""
    metrics = _call_host_metrics()
    metrics_block = _format_host_metrics_for_prompt(metrics)
    config_block = _load_config_snapshot()
    critique_text = "\n\n".join([
        f"From {c.get('from_critic', 'unknown')}: {json.dumps(c)}" for c in critiques
    ])
    prompt = (
        f"You are the Systems Engineer Agent (SE) for Appalachian Toys & Games.\n"
        f"{config_block}\n\n"
        f"{metrics_block}\n\n"
        f"You produced this analysis for: {task}\n\n"
        f"Your output:\n{json.dumps(original, indent=2)}\n\n"
        f"You received these critiques:\n{critique_text}\n\n"
        f"Revise your analysis to address valid critiques. You may push back on critiques\n"
        f"you disagree with — explain why technically. Return revised JSON in the same format."
    )
    response = claude_client.messages.create(
        model=model, max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        return _extract_json(response.content[0].text)
    except json.JSONDecodeError:
        return {"revised_output": response.content[0].text, "_parse_error": True}
