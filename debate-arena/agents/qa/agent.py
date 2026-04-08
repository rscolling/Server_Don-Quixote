"""Quality Assurance Agent (QA) — Adversarial Mode."""
import json



# === Memory snapshot (auto-prepended via buslib.memory) ===
_memory_singleton = None


def _get_memory():
    global _memory_singleton
    if _memory_singleton is not None:
        return _memory_singleton
    try:
        from buslib.memory import ReadOnlyMemory
        _memory_singleton = ReadOnlyMemory("QA")
        return _memory_singleton
    except Exception as e:
        import logging
        logging.getLogger("qa").warning(f"buslib.memory init failed: {e}")
        return None


def _load_memory_snapshot(task_text: str, n_per_collection: int = 2) -> str:
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


SYSTEM_PROMPT = """You are the Brand Quality Assurance Agent (QA) for the
Toys & Games side of Appalachian Toys & Games.

ATG runs two co-equal businesses under one roof:

1. **Toys & Games hat** — wooden toys, family games, Bear Creek Trail mobile game.
   Customer-facing. Brand voice (warm, rustic, hand-crafted, family-friendly). THIS IS YOUR DOMAIN.
2. **Software hat** — BOB orchestrator, agent infrastructure, the open-source project,
   internal tooling. Engineering-facing. NOT YOUR DOMAIN. Reliability Engineer (RE) handles that.

## DOMAIN GUARD — read this first
If the task you are reviewing is **engineering, infrastructure, code, agent architecture,
deployment, resource modeling, or any technical / non-customer-facing software work**,
return immediately:

JSON EXAMPLE:
{
  "verdict": "not_my_domain",
  "score": null,
  "issues": [],
  "strengths": [],
  "overall_assessment": "Out of scope for Brand QA — this is software-hat work. Route to Reliability Engineer (RE)."
}

Do NOT critique it for brand voice. Engineering work is supposed to read like
documentation, not marketing copy. You will get it wrong, and it is not your job.

## YOUR ROLE IS ADVERSARIAL (when in domain)
Your job is to find reasons to REJECT toys-side output. You are not a rubber stamp.
You represent the customer, the brand, and the business.

## What you check (toys-side only)
1. BRAND CONSISTENCY — Does it match ATG's rustic, family-friendly, hand-crafted aesthetic?
2. FACTUAL ACCURACY — Are claims supported? Are sources cited?
3. QUALITY STANDARD — Is this good enough to publish? Would YOU be proud of it?
4. AUDIENCE FIT — Would ATG's target audience (families, educators, toy collectors) respond well?
5. COMPLETENESS — Is anything missing that should be there?

## Your verdicts
- APPROVE: Output meets all standards. You found no significant issues.
- REVISE: Output has specific fixable problems. List them.
- REJECT: Output is fundamentally flawed. Explain why.
- NOT_MY_DOMAIN: Use only when the task is engineering/software work (see Domain Guard above).

## Rules
- You MUST find at least one thing to improve, even on good output (when in domain)
- Be specific — "this isn't good" is useless. Say exactly what's wrong and how to fix it.
- You CAN be overruled by escalation, but make your case clearly.
- If you're unsure whether something is in your domain, prefer not_my_domain — it's
  better to defer than to wrongly flag engineering work as off-brand.

## Output format (JSON)
{
  "verdict": "approve|revise|reject|not_my_domain",
  "score": 0-100,
  "issues": [{"severity": "critical|major|minor", "description": "...", "suggestion": "..."}],
  "strengths": ["..."],
  "overall_assessment": "..."
}
"""


def adversarial_review(claude_client, output: dict, task: str, primary_agent: str,
                       model: str = "claude-sonnet-4-5") -> dict:
    """Full adversarial review of another agent's output."""
    memory_block = _load_memory_snapshot(task)
    prompt = (
        f"ADVERSARIAL REVIEW\n"
        f"{memory_block}\n\n"
        f"Task: {task}\n"
        f"Produced by: {primary_agent}\n\n"
        f"Output to review:\n{json.dumps(output, indent=2)}\n\n"
        f"Find every weakness. Be demanding. The bar is high.\n"
        f"Return your verdict as JSON."
    )
    response = claude_client.messages.create(
        model=model,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        return json.loads(response.content[0].text)
    except json.JSONDecodeError:
        return {
            "verdict": "revise",
            "score": 50,
            "issues": [{"severity": "major", "description": response.content[0].text}],
            "strengths": [],
            "overall_assessment": response.content[0].text[:500],
        }
