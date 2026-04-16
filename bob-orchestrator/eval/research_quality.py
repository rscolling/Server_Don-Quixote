"""Research-quality eval task.

Runs a held-out Q&A set through BOB's /chat endpoint and scores answers
against expected facts. The point is NOT to score absolute LLM quality —
it's to produce a regression-tracked delta every time we change retrieval
(reranking, hybrid search, agentic decomposition, GBrain swap-in).

Scoring is intentionally dumb and deterministic: fact coverage via
substring match, with a small bonus for invoking a memory tool. Keeping
the rubric dumb makes run-to-run deltas meaningful.

Methodology:
- Load qa_set.jsonl (one question per line)
- For each, POST to /chat with a fresh thread_id
- Score: fraction of expected_facts present in response (case-insensitive
  substring match). Penalize if any forbidden_phrases appear.
- Aggregate per-question scores (0-1) into a task score (0-10)
- Append one run record to history.jsonl for regression tracking

To add/remove questions, edit qa_set.jsonl — no code change needed.
"""

import json
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx


EVAL_DIR = Path(__file__).parent
QA_SET_PATH = EVAL_DIR / "qa_set.jsonl"
HISTORY_PATH = EVAL_DIR / "history.jsonl"


@dataclass
class QAPair:
    id: str
    category: str
    question: str
    expected_facts: list[str]
    forbidden_phrases: list[str]


@dataclass
class QAResult:
    id: str
    category: str
    coverage: float  # 0.0 - 1.0
    forbidden_hit: bool
    recall_tool_called: bool
    score: float  # 0.0 - 1.0 after penalties/bonus
    duration_ms: int
    facts_matched: list[str]
    facts_missing: list[str]


def load_qa_set(path: Path = QA_SET_PATH) -> list[QAPair]:
    pairs: list[QAPair] = []
    with path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"qa_set.jsonl line {line_num}: {e}") from e
            pairs.append(QAPair(
                id=row["id"],
                category=row.get("category", "uncategorized"),
                question=row["question"],
                expected_facts=row.get("expected_facts", []),
                forbidden_phrases=row.get("forbidden_phrases", []),
            ))
    return pairs


def _score_answer(answer: str, qa: QAPair, recall_tool_called: bool) -> tuple[float, float, bool, list[str], list[str]]:
    """Return (final_score, coverage, forbidden_hit, matched, missing). Scores are 0.0-1.0."""
    answer_lc = (answer or "").lower()
    matched = [f for f in qa.expected_facts if f.lower() in answer_lc]
    missing = [f for f in qa.expected_facts if f.lower() not in answer_lc]
    coverage = len(matched) / len(qa.expected_facts) if qa.expected_facts else 0.0

    forbidden_hit = any(p.lower() in answer_lc for p in qa.forbidden_phrases)

    score = coverage
    if forbidden_hit:
        score *= 0.5
    if recall_tool_called and coverage > 0:
        score = min(1.0, score + 0.05)

    return score, coverage, forbidden_hit, matched, missing


async def _ask(client: httpx.AsyncClient, bob_url: str, question: str, thread_id: str) -> dict:
    resp = await client.post(
        f"{bob_url}/chat",
        json={"message": question, "thread_id": thread_id},
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()


def _recall_tool_invoked(chat_response: dict) -> bool:
    for tc in chat_response.get("tool_calls") or []:
        name = (tc.get("name") or "").lower()
        if "recall" in name or "memory" in name or "search" in name:
            return True
    return False


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=2,
            cwd=EVAL_DIR.parent,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _append_history(entry: dict, path: Path = HISTORY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


async def run_research_quality(client: httpx.AsyncClient, bob_url: str) -> dict:
    """Run the whole Q&A set. Returns a dict suitable for TaskResult plus history logging."""
    qa_set = load_qa_set()
    if not qa_set:
        return {
            "score_10": 0,
            "passed": False,
            "notes": "qa_set.jsonl is empty",
            "per_question": [],
            "duration_ms": 0,
            "tool_calls": 0,
        }

    started = time.time()
    per_question: list[QAResult] = []
    total_tool_calls = 0
    run_id = f"eval-rq-{int(started)}"

    for qa in qa_set:
        q_start = time.time()
        try:
            resp = await _ask(client, bob_url, qa.question, f"{run_id}-{qa.id}")
            recall_called = _recall_tool_invoked(resp)
            total_tool_calls += len(resp.get("tool_calls") or [])
            answer = resp.get("response", "") or ""
        except Exception as e:
            per_question.append(QAResult(
                id=qa.id, category=qa.category, coverage=0.0, forbidden_hit=False,
                recall_tool_called=False, score=0.0,
                duration_ms=int((time.time() - q_start) * 1000),
                facts_matched=[], facts_missing=list(qa.expected_facts),
            ))
            continue

        score, coverage, forbidden_hit, matched, missing = _score_answer(answer, qa, recall_called)
        per_question.append(QAResult(
            id=qa.id,
            category=qa.category,
            coverage=coverage,
            forbidden_hit=forbidden_hit,
            recall_tool_called=recall_called,
            score=score,
            duration_ms=int((time.time() - q_start) * 1000),
            facts_matched=matched,
            facts_missing=missing,
        ))

    duration_ms = int((time.time() - started) * 1000)
    mean_score = sum(q.score for q in per_question) / len(per_question)
    score_10 = round(mean_score * 10)
    passed = score_10 >= 6

    by_category: dict[str, list[float]] = {}
    for q in per_question:
        by_category.setdefault(q.category, []).append(q.score)
    category_means = {
        c: round(sum(v) / len(v), 3) for c, v in by_category.items()
    }

    forbidden_hits = sum(1 for q in per_question if q.forbidden_hit)
    recall_rate = sum(1 for q in per_question if q.recall_tool_called) / len(per_question)

    notes = (
        f"{len(qa_set)} questions, mean coverage={round(mean_score, 2)}, "
        f"recall-tool rate={round(recall_rate, 2)}, forbidden hits={forbidden_hits}"
    )

    history_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "bob_url": bob_url,
        "task": "research_quality",
        "score_10": score_10,
        "mean_score": round(mean_score, 3),
        "question_count": len(qa_set),
        "category_means": category_means,
        "forbidden_hits": forbidden_hits,
        "recall_tool_rate": round(recall_rate, 3),
        "duration_ms": duration_ms,
        "per_question": [
            {
                "id": q.id,
                "category": q.category,
                "score": round(q.score, 3),
                "coverage": round(q.coverage, 3),
                "forbidden_hit": q.forbidden_hit,
                "recall_tool_called": q.recall_tool_called,
                "facts_missing": q.facts_missing,
                "duration_ms": q.duration_ms,
            }
            for q in per_question
        ],
    }
    _append_history(history_entry)

    return {
        "score_10": score_10,
        "passed": passed,
        "notes": notes,
        "per_question": history_entry["per_question"],
        "duration_ms": duration_ms,
        "tool_calls": total_tool_calls,
        "category_means": category_means,
    }
