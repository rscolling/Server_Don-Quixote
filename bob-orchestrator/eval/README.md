# BOB Eval Harness

The 10-task benchmark protocol from `BOB-content/10_why_and_how_to_measure.md`. Run it against a live BOB instance to produce a scorecard.

The point of this harness is to **make BOB comparable to other multi-agent frameworks on the same protocol** — not to make BOB look good. Some tasks BOB will not score perfectly on. That's the point. Honest scoring beats vanity scoring.

---

## Running

### Prerequisites

- A running BOB instance (local or remote) reachable over HTTP
- Python 3.12+ with `httpx` installed (`pip install httpx`)

### Run all 10 tasks

```bash
cd bob-orchestrator
python -m eval.runner --url http://localhost:8100
```

### Run a single task

```bash
python -m eval.runner --url http://localhost:8100 --task push_back
```

### JSON output (for CI / scripting)

```bash
python -m eval.runner --url http://localhost:8100 --format json > scorecard.json
```

### Exit codes

- `0` — all 10 tasks passed
- `1` — at least one task failed
- `2` — BOB unreachable or unknown task name

---

## The 10 Tasks

| # | Task | What it tests |
|---|---|---|
| 1 | `email_triage` | Tool calling + Gmail integration |
| 2 | `memory_recall` | Vector memory + the recall tool |
| 3 | `multi_step` | Multi-step reasoning + content generation |
| 4 | `failure_recovery` | Recovery monitor + circuit breaker introspection |
| 5 | `push_back` | The personality — does BOB refuse a bad request? |
| 6 | `tool_restraint` | Doesn't call tools for trivial questions |
| 7 | `multi_turn` | Conversation memory across thread turns |
| 8 | `audit_trail` | Audit log endpoint returns logged calls |
| 9 | `cost_efficiency` | Cost tracker reports usage |
| 10 | `first_response` | Latency from message to first response |

Each task scores 0-10. Total possible: 100. Pass = 6+. The scorecard reports total, count of passes, and per-task notes.

---

## Honest Scoring Notes

A few things this harness deliberately does NOT do:

1. **It doesn't measure absolute LLM quality.** That depends on the model BOB is configured to use, not BOB itself. If you run the eval against BOB-on-Claude-Opus and BOB-on-Qwen-7B, Claude will look better — but that's a model comparison, not a framework comparison.

2. **It doesn't run failure injection automatically.** The `failure_recovery` task checks that BOB *reports* recovery state, which is a proxy for "the recovery layer exists." A real failure injection test would kill the message bus container mid-call. That's a manual test today.

3. **It doesn't compare cost across providers.** The `cost_efficiency` task confirms cost tracking works. To compare actual cost-per-task across providers, you need to run the eval multiple times with different `BOB_LLM_PROVIDER` values and compare the cost reports.

4. **It uses heuristic scoring on free-text responses.** Tasks like `push_back` look for specific phrases ("doesn't exist", "imaginary", "bad idea") to determine if BOB pushed back. A model that pushes back creatively in a way the heuristic doesn't recognize will be marked down. The fix is to expand the phrase list, not to make the test smarter — keeping the heuristic dumb makes it easier to compare across frameworks.

5. **It depends on BOB's specific endpoints.** The eval calls `/firewall/audit` and `/cost/status`, which are BOB-specific. To run this protocol against another framework (CrewAI, AutoGen, Letta), you'd need to adapt the audit_trail and cost_efficiency tasks to whatever those frameworks expose.

---

## Comparing to Other Frameworks

To produce a head-to-head comparison:

1. Stand up the other framework (CrewAI, AutoGen, Letta, etc.) with an equivalent toolkit
2. Adapt the runner's `audit_trail` and `cost_efficiency` tasks to that framework's APIs
3. Run the same 10 tasks against both
4. Publish both scorecards

This is exactly what the ROADMAP.md says about Tier 2 ("eval harness + 1 public benchmark run"). The harness exists. The public benchmark run is the next step.

---

## Adding a New Task

1. Add an `async def task_<name>(client, bob_url) -> TaskResult` function in `runner.py`
2. Add it to the `TASKS` dict at the bottom
3. Document it in this README's table
4. Update the methodology doc at `BOB-content/10_why_and_how_to_measure.md` Part 5

Each task should be:
- **Deterministic enough** to score reliably across runs
- **Cheap enough** to run frequently (not 50,000 tokens per task)
- **Specific enough** to catch a real capability or absence
- **Generic enough** to run against another framework with minor adaptation

---

## Known Limitations

- The harness does not run inside a CI loop yet. Manual invocation only.
- It doesn't track regressions across runs. A future enhancement is a small SQLite DB that stores each run's scorecard so you can see "BOB scored 78/100 on 2026-04-07 and 81/100 on 2026-04-14."
- It doesn't run the full failure-injection suite. Manual testing covers that today.
- It assumes BOB is reachable on a single URL. Multi-region or load-balanced deployments would need a different runner.

---

*Yes Boss. Run the eval. Be honest about the score. — BOB*
