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


def execute_writing(claude_client, task: str, model: str = "claude-sonnet-4-5") -> dict:
    """Write content for a given task."""
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
    prompt = (
        f"You are the Copy Editor Agent (CE) for Appalachian Toys & Games.\n"
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
        return json.loads(response.content[0].text)
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
        return json.loads(response.content[0].text)
    except json.JSONDecodeError:
        return {"revised_output": response.content[0].text, "_parse_error": True}
