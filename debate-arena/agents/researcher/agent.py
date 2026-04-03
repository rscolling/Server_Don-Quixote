"""Researcher Agent (RA) — research, analysis, fact-checking."""
import json
from datetime import datetime
from pathlib import Path


SYSTEM_PROMPT = """You are the Researcher Agent (RA) for Appalachian Toys & Games.
Your job is to gather, synthesize, and summarize information.

## Behavior
- Always cite your sources
- Summarize in plain, clear language
- Be thorough but concise
- Flag low-confidence claims explicitly

## Output Format (return as JSON)
{
  "topic": "...",
  "date": "YYYY-MM-DD",
  "key_findings": ["...", "..."],
  "sources": ["...", "..."],
  "confidence": "High|Medium|Low",
  "summary": "...",
  "caveats": ["anything you're uncertain about"]
}
"""


def execute_research(claude_client, task: str, model: str = "claude-sonnet-4-5") -> dict:
    """Run a research task and return structured results."""
    response = claude_client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": task}],
    )
    text = response.content[0].text
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        result = {
            "topic": task,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "key_findings": [text[:500]],
            "sources": [],
            "confidence": "Medium",
            "summary": text[:1000],
            "caveats": ["Response was not structured JSON"],
        }

    # Save to agent-share
    output_dir = Path("/agent-share/workspace/research")
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_ " else "" for c in task[:40]).strip().replace(" ", "_")
    path = output_dir / f"RA_research_{safe}_{ts}.json"
    with open(path, "w") as f:
        json.dump(result, f, indent=2)
    result["_file_path"] = str(path)
    return result


def critique_output(claude_client, output: dict, task: str,
                    model: str = "claude-sonnet-4-5") -> dict:
    """Critique another agent's output from RA's perspective (fact-checking)."""
    prompt = (
        f"You are the Researcher Agent (RA) for Appalachian Toys & Games.\n"
        f"Another agent produced this output for the task: {task}\n\n"
        f"Output to critique:\n{json.dumps(output, indent=2)}\n\n"
        f"Focus on FACTUAL ACCURACY and SOURCE QUALITY.\n"
        f"Are claims supported? Are sources cited and credible?\n"
        f"Are there logical gaps or unsupported assertions?\n\n"
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
        return json.loads(response.content[0].text)
    except json.JSONDecodeError:
        return {"verdict": "revise", "weakest_point": "Parse error",
                "specific_feedback": response.content[0].text, "confidence": 0.5}


def revise_output(claude_client, original: dict, critiques: list, task: str,
                  model: str = "claude-sonnet-4-5") -> dict:
    """Revise research output based on critiques."""
    critique_text = "\n\n".join([
        f"From {c.get('from_critic', 'unknown')}: {json.dumps(c)}" for c in critiques
    ])
    prompt = (
        f"You are the Researcher Agent (RA) for Appalachian Toys & Games.\n"
        f"You produced this research for: {task}\n\n"
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
        return json.loads(response.content[0].text)
    except json.JSONDecodeError:
        return {"revised_output": response.content[0].text, "_parse_error": True}
