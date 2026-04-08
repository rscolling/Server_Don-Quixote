"""Copy Editor Agent (CE) — content writing, editing, brand voice."""
import json
from datetime import datetime
from pathlib import Path


SYSTEM_PROMPT = """You are the Copy Editor Agent (CE) for Appalachian Toys & Games.
You write, edit, and critique content for a family-friendly wooden toy company.

## Brand Voice
- Warm, authentic, slightly rustic
- Family-oriented, wholesome, adventurous
- Conversational but professional
- Evokes craftsmanship, nature, imagination

## When WRITING content, return JSON:
{
  "title": "...",
  "content": "...",
  "word_count": 0,
  "tone": "...",
  "target_audience": "...",
  "cta": "call to action if applicable"
}

## When CRITIQUING, focus on:
- Clarity and readability
- Grammar and style
- Brand voice consistency
- Audience appropriateness
- Persuasiveness and engagement
"""



# === Memory snapshot (auto-prepended via buslib.memory) ===
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


_memory_singleton = None


def _get_memory():
    global _memory_singleton
    if _memory_singleton is not None:
        return _memory_singleton
    try:
        from buslib.memory import ReadOnlyMemory
        _memory_singleton = ReadOnlyMemory("CE")
        return _memory_singleton
    except Exception as e:
        import logging
        logging.getLogger("copy-editor").warning(f"buslib.memory init failed: {e}")
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
    """Write content for a given task."""
    memory_block = _load_memory_snapshot(task)
    user_message = f"{memory_block}\n\n{task}"
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
            "content": text,
            "word_count": len(text.split()),
            "tone": "unknown",
            "target_audience": "general",
        }

    output_dir = Path("/agent-share/workspace/content")
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_ " else "" for c in task[:40]).strip().replace(" ", "_")
    path = output_dir / f"CE_content_{safe}_{ts}.json"
    with open(path, "w") as f:
        json.dump(result, f, indent=2)
    result["_file_path"] = str(path)
    return result


def critique_output(claude_client, output: dict, task: str,
                    model: str = "claude-sonnet-4-5") -> dict:
    """Critique another agent's output for clarity, grammar, tone, brand voice."""
    memory_block = _load_memory_snapshot(task)
    prompt = (
        f"You are the Copy Editor Agent (CE) for Appalachian Toys & Games.\n"
        f"{memory_block}\n\n"
        f"Another agent produced this output for: {task}\n\n"
        f"Output to critique:\n{json.dumps(output, indent=2)}\n\n"
        f"Focus on CLARITY, GRAMMAR, TONE, and BRAND VOICE.\n"
        f"Is the writing clear and engaging?\n"
        f"Does it match ATG's warm, family-friendly, rustic brand?\n"
        f"Find the WEAKEST part and push back specifically.\n\n"
        f"Respond with JSON:\n"
        f'{{"verdict": "approve|revise|reject", '
        f'"weakest_point": "...", '
        f'"specific_feedback": "...", '
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
                "specific_feedback": response.content[0].text, "confidence": 0.5}


def revise_output(claude_client, original: dict, critiques: list, task: str,
                  model: str = "claude-sonnet-4-5") -> dict:
    """Revise content based on critiques."""
    critique_text = "\n\n".join([
        f"From {c.get('from_critic', 'unknown')}: {json.dumps(c)}" for c in critiques
    ])
    prompt = (
        f"You are the Copy Editor Agent (CE) for Appalachian Toys & Games.\n"
        f"You produced this content for: {task}\n\n"
        f"Your output:\n{json.dumps(original, indent=2)}\n\n"
        f"You received these critiques:\n{critique_text}\n\n"
        f"Revise your output to address the valid critiques.\n"
        f"You may push back on critiques you disagree with — explain why.\n"
        f"Return the revised output as JSON in the same format."
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
