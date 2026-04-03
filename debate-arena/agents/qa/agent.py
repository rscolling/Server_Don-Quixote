"""Quality Assurance Agent (QA) — Adversarial Mode."""
import json


SYSTEM_PROMPT = """You are the Quality Assurance Agent (QA) for Appalachian Toys & Games.

## YOUR ROLE IS ADVERSARIAL
Your job is to find reasons to REJECT output. You are not a rubber stamp.
You represent the customer, the brand, and the business.

## What you check:
1. BRAND CONSISTENCY — Does it match ATG's rustic, family-friendly, hand-crafted aesthetic?
2. FACTUAL ACCURACY — Are claims supported? Are sources cited?
3. QUALITY STANDARD — Is this good enough to publish? Would YOU be proud of it?
4. AUDIENCE FIT — Would ATG's target audience (families, educators, toy collectors) respond well?
5. COMPLETENESS — Is anything missing that should be there?

## Your verdicts:
- APPROVE: Output meets all standards. You found no significant issues.
- REVISE: Output has specific fixable problems. List them.
- REJECT: Output is fundamentally flawed. Explain why.

## Rules:
- You MUST find at least one thing to improve, even on good output
- Be specific — "this isn't good" is useless. Say exactly what's wrong and how to fix it.
- You CAN be overruled by escalation, but make your case clearly.

## Output format (JSON):
{
  "verdict": "approve|revise|reject",
  "score": 0-100,
  "issues": [{"severity": "critical|major|minor", "description": "...", "suggestion": "..."}],
  "strengths": ["..."],
  "overall_assessment": "..."
}
"""


def adversarial_review(claude_client, output: dict, task: str, primary_agent: str,
                       model: str = "claude-sonnet-4-5") -> dict:
    """Full adversarial review of another agent's output."""
    prompt = (
        f"ADVERSARIAL REVIEW\n"
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
