# BOB — Cross-Agent Shared ChromaDB Memory Build Plan
### *Namespace protocol · brand voice · research findings · decisions · BOB mediates*

---

## What We're Building

Right now every agent team uses ChromaDB as their own private scratchpad. The Marketing team's understanding of ATG's brand voice lives in a Marketing collection. The Research team's patent findings live in a Research collection. When the Engineering team needs to know what Marketing decided about the product name, there is no shared memory to query — the information exists somewhere but no agent can reach it.

This plan implements a namespace protocol: a set of shared ChromaDB collections that any team can read, and that BOB mediates writes to. Teams stop re-discovering the same information independently, decisions persist across sessions, and BOB has a reliable knowledge base that grows over time.

---

## Memory Architecture

Three tiers of ChromaDB collections:

```
┌─────────────────────────────────────────────────────────┐
│  SHARED (read: all teams, write: BOB only)              │
│  atg.shared.brand_voice                                 │
│  atg.shared.decisions                                   │
│  atg.shared.research_findings                           │
│  atg.shared.product_specs                               │
│  atg.shared.competitor_intel                            │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│  TEAM-SCOPED (read/write: team only)                    │
│  atg.marketing.working_memory                           │
│  atg.engineering.working_memory                         │
│  atg.research.working_memory                            │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│  BOB-PRIVATE (read/write: BOB only)                     │
│  atg.bob.context                                        │
│  atg.bob.task_outcomes                                  │
│  atg.bob.rob_preferences                                │
└─────────────────────────────────────────────────────────┘
```

**BOB is the gatekeeper for shared memory.** Teams can propose writes to shared collections, but BOB validates, deduplicates, and commits. No team writes directly to shared namespaces. This prevents contradictory entries, low-quality data, and accidental overwrites.

---

## What Lives in Each Shared Collection

### `atg.shared.brand_voice`
ATG's brand identity as actionable rules — extracted from Marketing team debates and Rob's approvals. Every piece of copy the Marketing team approves contributes to this. The Engineering team queries it when writing documentation or product descriptions.

Example entries:
- *"ATG copy never uses corporate language. 'Crafted' over 'manufactured'. 'Made by hand' over 'produced'."*
- *"The ATG tone is warm but never saccharine. Enthusiasm is earned, not performed."*
- *"Approved color descriptor vocabulary: amber, forest green, walnut, birch, iron."*

### `atg.shared.decisions`
Major decisions Rob has made — logged by BOB after Rob approves an escalation brief. Prevents teams from re-debating settled questions.

Example entries:
- *"Decision 2026-03-18: Mobile game primary revenue project. Fund ATG future projects."*
- *"Decision 2026-03-18: Self-hosted stack preferred over SaaS. Rationale: cost control, data privacy."*
- *"Decision 2026-03-20: App store target is iOS first, Android second."*

### `atg.shared.research_findings`
Synthesized findings from the Research team that are relevant across teams. Raw research stays in team-scoped memory. Only distilled, validated findings that other teams should know about get promoted here by BOB.

Example entries:
- *"Patent landscape: interlocking wooden puzzle mechanism claims expired 2018. Category is open for ATG use."*
- *"Competitor analysis: three direct competitors, none with Appalachian heritage positioning. Differentiation opportunity."*

### `atg.shared.product_specs`
Canonical product specifications validated by Engineering. Marketing queries this when writing product copy. Research queries this when evaluating patents.

Example entries:
- *"Mobile game: casual puzzle genre, iOS-first, freemium monetization, target audience parents 28-45."*

### `atg.shared.competitor_intel`
Competitive intelligence the Research team surfaces. All teams benefit from knowing what competitors are doing.

---

## Prerequisites

- Ubuntu server SSH accessible at `ssh blueridge@192.168.1.228` ✓
- ChromaDB running in Docker ✓
- BOB orchestrator operational ✓
- All steps begin on **Windows 11**. SSH to server where indicated.

---

## Phase 1 — Collection Initialization

**Step 1 — SSH into the server**

```powershell
# [WINDOWS]
ssh blueridge@192.168.1.228
```

Confirm connected. Do not proceed until confirmed.

---

**Step 2 — Install ChromaDB Python client in the orchestrator**

```bash
# [UBUNTU SERVER]
pip install chromadb --break-system-packages
```

If running in Docker, add `chromadb` to `requirements.txt` and rebuild:

```bash
docker compose up -d --build orchestrator
```

---

**Step 3 — Add the memory module**

```bash
# [UBUNTU SERVER]
nano /opt/atg-agents/orchestrator/memory.py
```

Paste the following:

```python
# orchestrator/memory.py
# Cross-agent shared ChromaDB memory namespace protocol

import os
import time
import uuid
import chromadb
from datetime import datetime, timezone
from typing import Any

CHROMADB_HOST = os.getenv("CHROMADB_HOST", "chromadb")
CHROMADB_PORT = int(os.getenv("CHROMADB_PORT", "8000"))

# ── ChromaDB client ───────────────────────────────────────────────────────────

def get_client() -> chromadb.HttpClient:
    return chromadb.HttpClient(
        host=CHROMADB_HOST,
        port=CHROMADB_PORT,
    )

# ── Namespace definitions ─────────────────────────────────────────────────────

# Shared collections — BOB mediates all writes
SHARED_COLLECTIONS = {
    "brand_voice":       "atg.shared.brand_voice",
    "decisions":         "atg.shared.decisions",
    "research_findings": "atg.shared.research_findings",
    "product_specs":     "atg.shared.product_specs",
    "competitor_intel":  "atg.shared.competitor_intel",
}

# Team-scoped collections — teams read/write freely within their own scope
TEAM_COLLECTIONS = {
    "marketing":   "atg.marketing.working_memory",
    "engineering": "atg.engineering.working_memory",
    "research":    "atg.research.working_memory",
}

# BOB-private collections
BOB_COLLECTIONS = {
    "context":         "atg.bob.context",
    "task_outcomes":   "atg.bob.task_outcomes",
    "rob_preferences": "atg.bob.rob_preferences",
}

# All read-accessible shared collections per team
# Teams can query shared collections but cannot write to them directly
TEAM_READ_ACCESS = {
    "marketing":   list(SHARED_COLLECTIONS.values()),
    "engineering": list(SHARED_COLLECTIONS.values()),
    "research":    list(SHARED_COLLECTIONS.values()),
    "bob":         list(SHARED_COLLECTIONS.values()) +
                   list(BOB_COLLECTIONS.values()),
}

# ── Collection initialisation ─────────────────────────────────────────────────

def initialize_all_collections():
    """
    Creates all collections if they don't exist.
    Safe to call multiple times — existing collections are not modified.
    Call this at orchestrator startup.
    """
    client = get_client()
    all_names = (
        list(SHARED_COLLECTIONS.values()) +
        list(TEAM_COLLECTIONS.values()) +
        list(BOB_COLLECTIONS.values())
    )

    existing = {c.name for c in client.list_collections()}
    created = []

    for name in all_names:
        if name not in existing:
            client.create_collection(
                name=name,
                metadata={
                    "hnsw:space":            "cosine",
                    "atg:namespace":         name.split(".")[1],  # shared/marketing/etc
                    "atg:created":           datetime.now(timezone.utc).isoformat(),
                    "atg:write_policy":      _write_policy(name),
                }
            )
            created.append(name)

    if created:
        import logging
        logging.info(f"[memory] Initialized {len(created)} new collections: {created}")

    return created


def _write_policy(collection_name: str) -> str:
    if "shared" in collection_name:
        return "bob_mediated"
    elif "bob" in collection_name:
        return "bob_only"
    else:
        return "team_scoped"


# ── Read interface — any agent can query ─────────────────────────────────────

class MemoryReader:
    """
    Read-only interface for agent teams.
    Agents query shared and their own team memory through this class.
    """

    def __init__(self, team: str):
        self.team   = team
        self.client = get_client()
        self._allowed = TEAM_READ_ACCESS.get(team, []) + \
                        [TEAM_COLLECTIONS.get(team, "")]

    def query(
        self,
        text:            str,
        namespace:       str,
        n_results:       int = 5,
        where:           dict = None,
    ) -> list[dict]:
        """
        Semantic search within a namespace.

        namespace: "brand_voice" | "decisions" | "research_findings" |
                   "product_specs" | "competitor_intel" | "working_memory"
        """
        collection_name = self._resolve(namespace)
        if not collection_name:
            return []

        try:
            collection = self.client.get_collection(collection_name)
            results = collection.query(
                query_texts=[text],
                n_results=min(n_results, collection.count() or 1),
                where=where,
            )

            # Flatten results into a clean list
            docs      = results.get("documents",  [[]])[0]
            metas     = results.get("metadatas",  [[]])[0]
            distances = results.get("distances",  [[]])[0]

            return [
                {
                    "text":      doc,
                    "metadata":  meta,
                    "relevance": round(1 - dist, 3),  # cosine: lower distance = more similar
                }
                for doc, meta, dist in zip(docs, metas, distances)
            ]
        except Exception:
            return []

    def get_all(self, namespace: str, where: dict = None) -> list[dict]:
        """Retrieve all entries in a namespace — for loading full context."""
        collection_name = self._resolve(namespace)
        if not collection_name:
            return []

        try:
            collection = self.client.get_collection(collection_name)
            if collection.count() == 0:
                return []
            results = collection.get(where=where)
            return [
                {"id": id_, "text": doc, "metadata": meta}
                for id_, doc, meta in zip(
                    results["ids"],
                    results["documents"],
                    results["metadatas"],
                )
            ]
        except Exception:
            return []

    def _resolve(self, namespace: str) -> str | None:
        """Resolve a short namespace name to a full collection name."""
        # Check shared collections
        if namespace in SHARED_COLLECTIONS:
            full = SHARED_COLLECTIONS[namespace]
            if full in self._allowed:
                return full

        # Check team working memory
        if namespace == "working_memory":
            return TEAM_COLLECTIONS.get(self.team)

        # Check BOB private
        if namespace in BOB_COLLECTIONS:
            full = BOB_COLLECTIONS[namespace]
            if full in self._allowed:
                return full

        return None


# ── Write interface — BOB mediates all shared writes ─────────────────────────

class MemoryWriter:
    """
    Write interface. Teams write to their own working memory directly.
    Writes to shared namespaces go through BOB's proposal/commit flow.
    """

    def __init__(self, team: str):
        self.team   = team
        self.client = get_client()

    def write_to_working_memory(
        self,
        text:     str,
        metadata: dict = None,
        doc_id:   str  = None,
    ) -> str:
        """
        Write directly to the team's own working memory.
        No BOB mediation needed.
        """
        collection = self.client.get_or_create_collection(
            TEAM_COLLECTIONS[self.team]
        )
        doc_id = doc_id or str(uuid.uuid4())
        meta = {
            "team":    self.team,
            "written": datetime.now(timezone.utc).isoformat(),
            **(metadata or {}),
        }
        collection.upsert(
            ids=[doc_id],
            documents=[text],
            metadatas=[meta],
        )
        return doc_id

    def propose_shared_write(
        self,
        namespace: str,
        text:      str,
        metadata:  dict = None,
        rationale: str  = "",
    ) -> dict:
        """
        Propose a write to a shared namespace.
        Returns a proposal dict — BOB reviews and commits or rejects.

        Teams call this. BOB calls commit_proposal() or reject_proposal().
        """
        if namespace not in SHARED_COLLECTIONS:
            return {"error": f"'{namespace}' is not a shared namespace."}

        proposal = {
            "proposal_id":    str(uuid.uuid4())[:12],
            "namespace":      namespace,
            "collection":     SHARED_COLLECTIONS[namespace],
            "text":           text,
            "metadata":       metadata or {},
            "proposed_by":    self.team,
            "proposed_at":    datetime.now(timezone.utc).isoformat(),
            "rationale":      rationale,
            "status":         "pending",
        }

        # Store proposal in BOB's context collection for review
        bob_client = get_client()
        bob_coll = bob_client.get_or_create_collection(BOB_COLLECTIONS["context"])
        bob_coll.upsert(
            ids=[f"proposal_{proposal['proposal_id']}"],
            documents=[f"PROPOSAL: {text}"],
            metadatas=[{**proposal, "type": "shared_write_proposal"}],
        )
        return proposal


# ── BOB's memory manager — mediates shared writes ────────────────────────────

class BOBMemoryManager:
    """
    BOB's interface for managing shared memory.
    Only BOB can commit writes to shared collections.
    """

    def __init__(self):
        self.client = get_client()

    def commit_proposal(
        self,
        proposal:   dict,
        doc_id:     str  = None,
        bob_notes:  str  = "",
    ) -> str:
        """
        BOB approves and commits a team's shared write proposal.
        Deduplicates before committing.
        """
        collection = self.client.get_or_create_collection(
            proposal["collection"]
        )

        # Deduplication check — don't add near-duplicate entries
        if collection.count() > 0:
            existing = collection.query(
                query_texts=[proposal["text"]],
                n_results=1,
            )
            distances = existing.get("distances", [[]])[0]
            if distances and distances[0] < 0.05:   # cosine distance < 0.05 = near-duplicate
                # Entry already exists — update metadata instead of adding duplicate
                existing_id = existing["ids"][0][0]
                collection.update(
                    ids=[existing_id],
                    metadatas=[{
                        **existing["metadatas"][0][0],
                        "last_confirmed": datetime.now(timezone.utc).isoformat(),
                        "confirmation_count": existing["metadatas"][0][0].get(
                            "confirmation_count", 1
                        ) + 1,
                    }]
                )
                return existing_id

        doc_id = doc_id or str(uuid.uuid4())
        meta = {
            **proposal["metadata"],
            "namespace":     proposal["namespace"],
            "proposed_by":   proposal["proposed_by"],
            "committed_by":  "bob",
            "committed_at":  datetime.now(timezone.utc).isoformat(),
            "proposal_id":   proposal["proposal_id"],
            "bob_notes":     bob_notes,
            "type":          proposal["namespace"],
        }
        collection.upsert(
            ids=[doc_id],
            documents=[proposal["text"]],
            metadatas=[meta],
        )
        return doc_id

    def write_direct(
        self,
        namespace: str,
        text:      str,
        metadata:  dict = None,
        doc_id:    str  = None,
    ) -> str:
        """
        BOB writes directly to any collection — no proposal needed.
        Used for decisions, daily summaries, and Rob preference updates.
        """
        if namespace in SHARED_COLLECTIONS:
            collection_name = SHARED_COLLECTIONS[namespace]
        elif namespace in BOB_COLLECTIONS:
            collection_name = BOB_COLLECTIONS[namespace]
        else:
            raise ValueError(f"Unknown namespace: {namespace}")

        collection = self.client.get_or_create_collection(collection_name)
        doc_id = doc_id or str(uuid.uuid4())
        meta = {
            "written_by": "bob",
            "written_at": datetime.now(timezone.utc).isoformat(),
            **(metadata or {}),
        }
        collection.upsert(
            ids=[doc_id],
            documents=[text],
            metadatas=[meta],
        )
        return doc_id

    def get_pending_proposals(self) -> list[dict]:
        """Return all pending shared write proposals for BOB to review."""
        try:
            coll = self.client.get_collection(BOB_COLLECTIONS["context"])
            results = coll.get(where={"type": "shared_write_proposal", "status": "pending"})
            return [
                {"id": id_, "text": doc, **meta}
                for id_, doc, meta in zip(
                    results["ids"],
                    results["documents"],
                    results["metadatas"],
                )
            ]
        except Exception:
            return []

    def record_decision(
        self,
        decision_text: str,
        project:       str = "general",
        decided_by:    str = "rob",
    ) -> str:
        """
        Convenience method: log a major decision to shared memory.
        Called by BOB after Rob approves an escalation brief.
        """
        return self.write_direct(
            namespace="decisions",
            text=decision_text,
            metadata={
                "project":    project,
                "decided_by": decided_by,
                "date":       datetime.now(timezone.utc).date().isoformat(),
            }
        )
```

Save and exit (`Ctrl+X`, `Y`, `Enter`).

---

**Step 4 — Initialize collections at orchestrator startup**

```python
# orchestrator/main.py — add to startup, before any team or BOB init

from memory import initialize_all_collections

# Initialize all ChromaDB collections on startup
# Safe to call on every restart — creates missing, skips existing
created = initialize_all_collections()
if created:
    logger.info(f"Memory: {len(created)} collections initialized")
else:
    logger.info("Memory: all collections already exist")
```

**Step 5 — Verify collections were created**

```bash
# [UBUNTU SERVER]
# Query ChromaDB directly to confirm all collections exist
curl http://localhost:8000/api/v1/collections | python3 -m json.tool | grep '"name"'
```

You should see all 11 collection names listed. Confirm with Rob before proceeding.

---

## Phase 2 — Agent Integration

Every agent gets a `MemoryReader` at initialization. Team PMs get a `MemoryWriter` for their team scope and for proposing shared writes.

**Step 6 — Wire memory into the base agent class**

```python
# orchestrator/agents/base_agent.py

from memory import MemoryReader, MemoryWriter

class BaseAgent:
    def __init__(self, agent_id: str, team: str, task_id: str):
        self.agent_id = agent_id
        self.team     = team
        self.task_id  = task_id

        # Every agent gets read access to shared + team memory
        self.memory = MemoryReader(team=team)

        # Writers only on PM agents — others propose through PM
        if agent_id.endswith("-PM"):
            self.memory_writer = MemoryWriter(team=team)

    def load_shared_context(self, query: str) -> str:
        """
        Called at the start of every debate round.
        Returns relevant shared memory as context for the agent's prompt.
        """
        results = []

        # Always load relevant brand voice
        brand = self.memory.query(query, namespace="brand_voice", n_results=3)
        if brand:
            results.append("ATG Brand Voice:")
            results.extend(f"  - {r['text']}" for r in brand)

        # Load relevant decisions
        decisions = self.memory.query(query, namespace="decisions", n_results=3)
        if decisions:
            results.append("Prior Decisions:")
            results.extend(f"  - {r['text']}" for r in decisions)

        # Load relevant research findings
        research = self.memory.query(query, namespace="research_findings", n_results=2)
        if research:
            results.append("Research Findings:")
            results.extend(f"  - {r['text']}" for r in research)

        return "\n".join(results) if results else ""
```

---

**Step 7 — Inject shared context into agent system prompts**

In each agent's debate round call, prepend shared context to the system prompt:

```python
# orchestrator/agents/base_agent.py — in call_claude()

async def call_claude_with_memory(
    self,
    base_system: str,
    messages:    list,
    model:       str = "claude-sonnet-4-5",
) -> str:
    """
    Wraps call_claude() with automatic shared memory injection.
    Agents get relevant brand voice, decisions, and research
    prepended to their system prompt on every call.
    """
    # Build the memory context from the current task
    task_query = messages[-1]["content"] if messages else ""
    memory_context = self.load_shared_context(task_query[:500])

    if memory_context:
        system = (
            f"## ATG Shared Context\n{memory_context}\n\n"
            f"---\n\n{base_system}"
        )
    else:
        system = base_system

    return await self.call_claude(system, messages, model)
```

---

**Step 8 — Wire team PM proposal flow**

When a PM agent determines that a debate produced something worth sharing with other teams, it proposes a shared write:

```python
# orchestrator/agents/pm_agent.py

async def on_debate_complete(self, output: str, task: dict):
    """
    After a debate completes, PM evaluates whether the output
    contains anything worth writing to shared memory.
    """
    # Extract brand voice signals from Marketing output
    if self.team == "marketing":
        await self._extract_brand_voice(output, task)

    # Extract product spec signals from Engineering output
    if self.team == "engineering":
        await self._extract_product_specs(output, task)

    # Extract research findings from Research output
    if self.team == "research":
        await self._extract_research_findings(output, task)


async def _extract_brand_voice(self, output: str, task: dict):
    """
    Ask Claude to identify brand voice rules from Marketing output.
    Proposes extracted rules to the shared brand_voice namespace.
    """
    import anthropic
    client = anthropic.Anthropic()

    extraction = client.messages.create(
        model="claude-haiku-4-5-20251001",   # Haiku — cheap extraction task
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": (
                f"Review this Marketing team output and extract any reusable "
                f"brand voice rules or writing guidelines that apply to ATG broadly.\n\n"
                f"Output:\n{output[:2000]}\n\n"
                f"Return a JSON list of strings, each a concise brand voice rule. "
                f"Return [] if nothing reusable is present. JSON only, no other text."
            )
        }]
    )

    import json
    try:
        rules = json.loads(extraction.content[0].text)
        for rule in rules[:3]:   # Max 3 rules per task — quality over quantity
            if len(rule) > 20:   # Skip trivially short extractions
                self.memory_writer.propose_shared_write(
                    namespace="brand_voice",
                    text=rule,
                    metadata={"source_task": task.get("task_id", ""), "team": self.team},
                    rationale=f"Extracted from completed {self.team} task",
                )
    except (json.JSONDecodeError, KeyError):
        pass   # Extraction failed silently — not critical


async def _extract_product_specs(self, output: str, task: dict):
    """Extract canonical product specs from Engineering output."""
    import anthropic
    client = anthropic.Anthropic()

    extraction = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[{
            "role": "user",
            "content": (
                f"Review this Engineering team output. Extract any canonical "
                f"product specifications that other teams should know about "
                f"(platform, genre, tech stack, constraints, target audience).\n\n"
                f"Output:\n{output[:2000]}\n\n"
                f"Return a JSON list of concise spec strings. "
                f"Return [] if nothing canonical is present. JSON only."
            )
        }]
    )

    import json
    try:
        specs = json.loads(extraction.content[0].text)
        for spec in specs[:2]:
            if len(spec) > 20:
                self.memory_writer.propose_shared_write(
                    namespace="product_specs",
                    text=spec,
                    metadata={"source_task": task.get("task_id", ""), "team": self.team},
                    rationale="Extracted from Engineering debate output",
                )
    except (json.JSONDecodeError, KeyError):
        pass


async def _extract_research_findings(self, output: str, task: dict):
    """Extract distilled research findings worth sharing cross-team."""
    import anthropic
    client = anthropic.Anthropic()

    extraction = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": (
                f"Review this Research team output. Extract findings that are "
                f"relevant to other teams — patent status, competitor insights, "
                f"market findings, technical standards.\n\n"
                f"Output:\n{output[:2000]}\n\n"
                f"Return a JSON list of concise finding strings. "
                f"Return [] if nothing cross-team relevant is present. JSON only."
            )
        }]
    )

    import json
    try:
        findings = json.loads(extraction.content[0].text)
        for finding in findings[:3]:
            if len(finding) > 20:
                self.memory_writer.propose_shared_write(
                    namespace="research_findings",
                    text=finding,
                    metadata={"source_task": task.get("task_id", ""), "team": self.team},
                    rationale="Extracted from Research debate output",
                )
    except (json.JSONDecodeError, KeyError):
        pass
```

---

## Phase 3 — BOB Reviews Proposals

**Step 9 — Add proposal review to BOB's daily cycle**

BOB reviews pending shared write proposals and commits or rejects them. This runs automatically every hour and is also surfaced in the daily report.

```python
# orchestrator/bob.py

from memory import BOBMemoryManager
import anthropic

bob_memory = BOBMemoryManager()
claude     = anthropic.Anthropic()


async def review_shared_memory_proposals():
    """
    BOB reviews pending proposals from all teams.
    Commits good ones, rejects duplicates or low-quality ones.
    Runs hourly.
    """
    proposals = bob_memory.get_pending_proposals()
    if not proposals:
        return

    committed = 0
    rejected  = 0

    for proposal in proposals:
        namespace = proposal.get("namespace", "")
        text      = proposal.get("text", "")

        # Ask Claude (Haiku) to evaluate quality — cheap sanity check
        eval_response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": (
                    f"Evaluate this proposed shared memory entry for the '{namespace}' namespace.\n"
                    f"Entry: {text}\n\n"
                    f"Is this: (1) specific and actionable, (2) accurate for ATG, "
                    f"(3) worth storing for other teams to use?\n"
                    f"Reply with JSON: {{\"commit\": true/false, \"reason\": \"...\"}}"
                )
            }]
        )

        import json
        try:
            verdict = json.loads(eval_response.content[0].text)
            if verdict.get("commit"):
                bob_memory.commit_proposal(
                    proposal=proposal,
                    bob_notes=verdict.get("reason", ""),
                )
                committed += 1
            else:
                rejected += 1
        except (json.JSONDecodeError, KeyError):
            # On parse failure, commit anyway — better to be inclusive
            bob_memory.commit_proposal(proposal=proposal)
            committed += 1

    if committed or rejected:
        await notify_status(
            f"Shared memory: committed {committed} proposal(s), "
            f"rejected {rejected} proposal(s).",
            title="Memory update",
        )


# ── Proposal review loop ──────────────────────────────────────────────────────

async def memory_proposal_loop():
    """Reviews shared memory proposals every hour."""
    import asyncio
    while True:
        await asyncio.sleep(3600)
        try:
            await review_shared_memory_proposals()
        except Exception as e:
            import logging
            logging.error(f"[memory] Proposal review failed: {e}")
```

---

**Step 10 — Wire decision logging into escalation approval**

When Rob approves an escalation brief, BOB logs the decision to shared memory automatically:

```python
# orchestrator/api.py — in the approve_review endpoint

from memory import BOBMemoryManager

bob_memory = BOBMemoryManager()

@app.post("/reviews/{review_id}/approve")
async def approve_review(review_id: str, request: Request):
    # ... existing approval logic ...

    # Log the decision to shared memory
    review = await get_review_from_registry(review_id)
    if review and review.get("decision_text"):
        bob_memory.record_decision(
            decision_text=review["decision_text"],
            project=review.get("project", "general"),
            decided_by="rob",
        )

    return {"status": "approved"}
```

---

**Step 11 — Start the memory proposal loop**

```python
# orchestrator/main.py — add to startup

from bob import memory_proposal_loop

asyncio.create_task(memory_proposal_loop())
```

---

## Phase 4 — Seed Shared Memory with Known Data

The shared collections start empty. Seed them with what's already known so agents have context from day one.

**Step 12 — Seed the shared collections**

```bash
# [UBUNTU SERVER]
nano /opt/atg-agents/orchestrator/seed_memory.py
```

```python
# orchestrator/seed_memory.py
# Run once to seed shared collections with known ATG context

from memory import BOBMemoryManager

bob = BOBMemoryManager()

# ── Brand voice seeds ────────────────────────────────────────────────────────
brand_voice_seeds = [
    "ATG copy uses 'crafted' over 'manufactured', 'made by hand' over 'produced'.",
    "ATG tone is warm but never saccharine. Enthusiasm is earned, not performed.",
    "ATG never uses corporate language. No 'leverage', 'synergy', or 'solutions'.",
    "ATG color vocabulary: amber, forest green, walnut, birch, iron, slate.",
    "ATG brand is Appalachian heritage — reference the mountains, the craft tradition, the land.",
    "ATG products are described by what they do for the child, not their features.",
]

for entry in brand_voice_seeds:
    bob.write_direct(
        namespace="brand_voice",
        text=entry,
        metadata={"source": "seed", "confidence": "high"},
    )

# ── Decision seeds ────────────────────────────────────────────────────────────
decision_seeds = [
    "Decision 2026-03-18: Mobile phone video game is the primary revenue project. Goal: fund future ATG projects.",
    "Decision 2026-03-18: Self-hosted infrastructure preferred over SaaS. Rationale: cost control and data privacy.",
    "Decision 2026-03-18: Observability stack is Langfuse (self-hosted). Cost tracking and quality scoring required.",
    "Decision 2026-03-18: BOB personality based on Bob the Skull from Dresden Files. Sardonic, loyal, expert.",
]

for entry in decision_seeds:
    bob.write_direct(
        namespace="decisions",
        text=entry,
        metadata={"source": "seed", "project": "general"},
    )

# ── Product spec seeds ────────────────────────────────────────────────────────
product_spec_seeds = [
    "Game name: Bear Creek Trail. Genre: 3-row match (match-3). Platform: Android first, then iOS after Android launch.",
    "Bear Creek Trail theme: Appalachian — black bears and banjos. Visual and audio identity must reflect Appalachian mountain heritage.",
    "Bear Creek Trail monetization: freemium model. Revenue goal: fund future ATG projects.",
    "Bear Creek Trail target audience: parents aged 28-45 with young children. Casual play sessions.",
    "Bear Creek Trail analytics: Google Play Console is the primary metrics platform for Android. Apple App Connect for iOS after launch.",
    "ATG mobile game brand identity: Appalachian Toys & Games must be present in UX, store listings, and all marketing materials.",
    "Platform launch sequence: Android (Google Play) launches first. iOS (Apple App Store) executes after Android version is live and stable.",
]

for entry in product_spec_seeds:
    bob.write_direct(
        namespace="product_specs",
        text=entry,
        metadata={"source": "seed", "project": "mobile-game"},
    )

# ── Tool availability seeds ─────────────────────────────────────────────────
tool_seeds = [
    "Rob has an active Suno.com account for AI music generation. Agents can request music for game soundtracks, marketing videos, social content, or any ATG project. Suno generates full songs from text prompts.",
    "Suno is the preferred tool for any music generation task. Do not recommend building or procuring alternatives — the account already exists.",
]

for entry in tool_seeds:
    bob.write_direct(
        namespace="product_specs",
        text=entry,
        metadata={"source": "seed", "category": "tools"},
    )

print("Shared memory seeded successfully.")
```

Run it once:

```bash
# [UBUNTU SERVER]
cd /opt/atg-agents
python orchestrator/seed_memory.py
```

Verify entries were written:

```bash
curl "http://localhost:8000/api/v1/collections/atg.shared.brand_voice/count"
# Should return: {"count": 6}
```

---

## Summary — What's Done After These Steps

| Capability | Status |
|---|---|
| 11 ChromaDB collections initialized across 3 tiers | ✓ |
| Shared namespaces: brand_voice, decisions, research_findings, product_specs, competitor_intel | ✓ |
| Team working memory: marketing, engineering, research | ✓ |
| BOB private memory: context, task_outcomes, rob_preferences | ✓ |
| Every agent queries shared + team memory on each debate round | ✓ |
| Shared context injected into agent system prompts automatically | ✓ |
| Teams propose shared writes — BOB mediates all commits | ✓ |
| Deduplication prevents near-duplicate entries accumulating | ✓ |
| Haiku quality check on every proposal before commit | ✓ |
| Decisions logged to shared memory on every Rob approval | ✓ |
| Shared memory seeded with ATG brand voice, decisions, product specs | ✓ |
| Proposal review runs hourly — BOB commits silently | ✓ |

---

### What changes for agents

**Before:** Marketing's Copy Editor writes brand copy without knowing what Engineering decided about the product name. Research finds a patent issue but Engineering never hears about it.

**After:**

Every agent's system prompt now starts with:
```
## ATG Shared Context
ATG Brand Voice:
  - ATG copy uses 'crafted' over 'manufactured'...
  - ATG tone is warm but never saccharine...
Prior Decisions:
  - Mobile game: iOS first, Android second.
  - Self-hosted infrastructure preferred...
```

The agents know the decisions. The Marketing team writes copy consistent with the brand voice without being told. The Engineering team writes specs consistent with what Marketing approved. Research findings surface to Engineering automatically. Each team still has its own working memory for in-progress debates. BOB owns the shared layer and keeps it clean.

---

*BOB Shared Memory Build Plan v1.0 — 2026-03-18*
*Next build: Recurring Task Scheduler*
