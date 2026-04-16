"""ChromaDB shared memory — BOB mediates all writes."""

import json
import logging
from datetime import datetime, timezone

import chromadb
from app.config import CHROMADB_URL

logger = logging.getLogger("bob.memory")

_client = None

COLLECTIONS = {
    "brand_voice": "ATG brand guidelines, tone, color palette, messaging rules",
    "decisions": "Major decisions made by Rob, logged with date and context",
    "research": "Research findings from agents — market data, competitor analysis",
    "product_specs": "Product specifications, game design docs, feature lists",
    "project_context": "Active project briefs, status updates, blockers",
    "personal_research": "Rob's off-business deep-research findings (populated via /deep)",
}


def get_client() -> chromadb.HttpClient:
    global _client
    if _client is None:
        _client = chromadb.HttpClient(host=CHROMADB_URL.replace("http://", "").split(":")[0],
                                      port=int(CHROMADB_URL.split(":")[-1]))
    return _client


def init_collections():
    """Create all standard collections if they don't exist."""
    client = get_client()
    for name, description in COLLECTIONS.items():
        client.get_or_create_collection(
            name=name,
            metadata={"description": description}
        )


def store(collection: str, doc_id: str, text: str, metadata: dict | None = None):
    """Store a document in a collection. BOB mediates all writes."""
    client = get_client()
    col = client.get_collection(collection)
    col.upsert(
        ids=[doc_id],
        documents=[text],
        metadatas=[metadata or {}]
    )


def query(collection: str, query_text: str, n_results: int = 5) -> list[dict]:
    """Query a collection for similar documents."""
    client = get_client()
    col = client.get_collection(collection)
    results = col.query(query_texts=[query_text], n_results=n_results)
    docs = []
    for i, doc in enumerate(results["documents"][0]):
        docs.append({
            "id": results["ids"][0][i],
            "text": doc,
            "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
            "distance": results["distances"][0][i] if results["distances"] else None,
        })
    return docs


def get_all(collection: str) -> list[dict]:
    """Get all documents from a collection."""
    client = get_client()
    col = client.get_collection(collection)
    results = col.get()
    docs = []
    for i, doc in enumerate(results["documents"]):
        docs.append({
            "id": results["ids"][i],
            "text": doc,
            "metadata": results["metadatas"][i] if results["metadatas"] else {},
        })
    return docs


# ── Export / Import (memory portability) ────────────────────────────────────

EXPORT_FORMAT_VERSION = "1.0"


def export_all(include_collections: list[str] | None = None) -> dict:
    """Export all (or specified) collections as a portable dict.

    Returns a JSON-serializable structure that can be saved to a file and
    later imported into another BOB instance via import_all().

    The output format is intentionally simple — no embeddings, just the
    text and metadata that BOB or any other vector store can re-embed on
    import. This makes the export portable across vector DB implementations.
    """
    client = get_client()
    target_collections = include_collections or list(COLLECTIONS.keys())

    export = {
        "format_version": EXPORT_FORMAT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source": "BOB",
        "collections": {},
    }

    for name in target_collections:
        try:
            col = client.get_collection(name)
            results = col.get()
            entries = []
            for i, doc in enumerate(results["documents"]):
                entries.append({
                    "id": results["ids"][i],
                    "text": doc,
                    "metadata": results["metadatas"][i] if results["metadatas"] else {},
                })
            export["collections"][name] = {
                "description": COLLECTIONS.get(name, ""),
                "count": len(entries),
                "entries": entries,
            }
            logger.info(f"Exported {len(entries)} entries from '{name}'")
        except Exception as e:
            logger.warning(f"Failed to export collection '{name}': {e}")
            export["collections"][name] = {"error": str(e)}

    export["total_entries"] = sum(
        c.get("count", 0) for c in export["collections"].values()
        if isinstance(c, dict)
    )
    return export


def export_to_file(path: str, include_collections: list[str] | None = None) -> dict:
    """Export memory to a JSON file. Returns a summary dict."""
    data = export_all(include_collections)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str, ensure_ascii=False)
        logger.info(f"Memory exported to {path} ({data.get('total_entries', 0)} entries)")
        return {
            "status": "exported",
            "path": path,
            "total_entries": data.get("total_entries", 0),
            "collections": list(data["collections"].keys()),
        }
    except Exception as e:
        logger.error(f"Failed to write export to {path}: {e}")
        return {"status": "error", "path": path, "error": str(e)}


def import_all(data: dict, mode: str = "merge") -> dict:
    """Import memory from a previously-exported dict.

    Args:
        data: The dict produced by export_all() — must have format_version
              and collections keys.
        mode: 'merge' (default) — upsert each entry alongside existing
                                  data. Doc IDs collide → import overwrites.
              'replace' — delete each target collection's contents first,
                          then import. Destructive. Use with care.

    Returns a summary with counts of imported entries per collection.
    """
    if not isinstance(data, dict):
        return {"status": "error", "error": "data is not a dict"}

    fmt = data.get("format_version")
    if fmt != EXPORT_FORMAT_VERSION:
        logger.warning(f"Import format version mismatch: got {fmt}, expected {EXPORT_FORMAT_VERSION}")

    collections = data.get("collections", {})
    if not collections:
        return {"status": "error", "error": "no collections in import data"}

    client = get_client()
    summary = {"status": "imported", "mode": mode, "imported": {}, "errors": []}

    for name, payload in collections.items():
        if "error" in payload:
            summary["errors"].append({"collection": name, "error": payload["error"]})
            continue

        entries = payload.get("entries", [])
        if not entries:
            summary["imported"][name] = 0
            continue

        try:
            # Make sure the collection exists
            col = client.get_or_create_collection(
                name=name,
                metadata={"description": payload.get("description", COLLECTIONS.get(name, ""))},
            )

            if mode == "replace":
                # Wipe existing entries
                existing = col.get()
                if existing["ids"]:
                    col.delete(ids=existing["ids"])
                    logger.info(f"Cleared {len(existing['ids'])} existing entries from '{name}'")

            ids = [e["id"] for e in entries]
            documents = [e["text"] for e in entries]
            metadatas = [e.get("metadata", {}) for e in entries]
            col.upsert(ids=ids, documents=documents, metadatas=metadatas)
            summary["imported"][name] = len(entries)
            logger.info(f"Imported {len(entries)} entries into '{name}' (mode={mode})")
        except Exception as e:
            logger.error(f"Failed to import into '{name}': {e}")
            summary["errors"].append({"collection": name, "error": str(e)})

    summary["total_imported"] = sum(summary["imported"].values())
    return summary


def import_from_file(path: str, mode: str = "merge") -> dict:
    """Import memory from a previously-exported JSON file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"status": "error", "error": f"file not found: {path}"}
    except json.JSONDecodeError as e:
        return {"status": "error", "error": f"invalid JSON: {e}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

    return import_all(data, mode=mode)


# ── Seed data ───────────────────────────────────────────────────────────────

SEED_DATA = {
    "brand_voice": [
        {
            "id": "brand_identity",
            "text": "ATG (Appalachian Toys & Games) is a handcrafted, Appalachian heritage brand. The brand is rustic, authentic, warm, and grounded. We make things that feel like they came from the mountains — because they did. No corporate polish. No Silicon Valley slickness. Real craftsmanship, real stories, real Appalachian roots.",
            "metadata": {"type": "identity", "source": "Rob"},
        },
        {
            "id": "brand_colors",
            "text": "ATG color palette: Primary green and amber. These evoke the Appalachian forest and warm mountain light. Use these consistently across all materials — website, app store, marketing, packaging.",
            "metadata": {"type": "visual", "source": "Rob"},
        },
        {
            "id": "brand_tone",
            "text": "ATG brand voice is warm, direct, and unpretentious. We say what we mean. We don't use corporate buzzwords or marketing fluff. We talk like neighbors, not advertisers. Humor is welcome — cleverness over snark. The feeling should be: you're talking to someone who made this thing with their hands and is proud of it.",
            "metadata": {"type": "tone", "source": "Rob"},
        },
        {
            "id": "brand_donts",
            "text": "ATG brand anti-patterns: Never use 'disrupt', 'synergy', 'leverage', 'pivot', or startup jargon. Never sound corporate. Never apologize for being small — it's a feature. Never copy big-studio marketing language. Never lose the Appalachian identity to appeal to a broader audience.",
            "metadata": {"type": "constraints", "source": "Rob"},
        },
    ],
    "decisions": [
        {
            "id": "decision_mobile_game_primary",
            "text": "2026-03-18: Mobile game designated as primary revenue project. Bear Creek Trail — 3-row match game, Appalachian theme, black bears and banjos. Android first, iOS after Android launch. Revenue is the success metric, not downloads.",
            "metadata": {"date": "2026-03-18", "made_by": "Rob"},
        },
        {
            "id": "decision_platform_sequence",
            "text": "2026-03-18: Android launches first via Google Play. iOS follows only after Android is live and revenue-generating. Do not start iOS until Android validates the concept.",
            "metadata": {"date": "2026-03-18", "made_by": "Rob"},
        },
        {
            "id": "decision_suno_music",
            "text": "2026-03-18: Suno.com account active for AI music generation. Available for agents to use on game soundtrack and marketing audio.",
            "metadata": {"date": "2026-03-18", "made_by": "Rob"},
        },
    ],
    "product_specs": [
        {
            "id": "bear_creek_trail_overview",
            "text": "Bear Creek Trail: Mobile match-3 game. 3-row play area. Appalachian theme — black bears, banjos, mason jars, mountain wildflowers, fireflies. Target: casual mobile gamers. Monetization: in-app purchases + ads. Built in Unity.",
            "metadata": {"project": "PROJECT-01", "type": "overview"},
        },
    ],
    "project_context": [
        {
            "id": "project01_status",
            "text": "PROJECT-01 Bear Creek Trail: Active development. Primary revenue project. Game production, app store deployment, and marketing campaign all in scope. Engineering and Marketing teams run in parallel. Home server resources are finite — this project gets priority above all others.",
            "metadata": {"project": "PROJECT-01", "status": "active"},
        },
        {
            "id": "project02_status",
            "text": "PROJECT-02 ATG Website: Ongoing maintenance. www.appalachiantoysgames.com. Static HTML/CSS/JS on Nginx. Minor changes auto-publish after QA. Major changes go to staging for Rob review.",
            "metadata": {"project": "PROJECT-02", "status": "maintenance"},
        },
    ],
}


def seed_collections():
    """Seed collections with baseline ATG data. Only adds docs that don't already exist."""
    client = get_client()
    seeded = 0
    for collection_name, docs in SEED_DATA.items():
        col = client.get_collection(collection_name)
        existing = col.get()
        existing_ids = set(existing["ids"]) if existing["ids"] else set()

        for doc in docs:
            if doc["id"] not in existing_ids:
                col.upsert(
                    ids=[doc["id"]],
                    documents=[doc["text"]],
                    metadatas=[doc["metadata"]],
                )
                seeded += 1

    return seeded
