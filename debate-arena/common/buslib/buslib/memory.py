"""Read-only ChromaDB access for debate-arena agents.

Each agent gets a ReadOnlyMemory instance configured with a per-agent allowlist
of collections. Reads only — agents cannot mutate BOB's shared memory. All
writes still flow through BOB.

Use:
    from buslib.memory import ReadOnlyMemory
    mem = ReadOnlyMemory("RA")  # picks up the default RA allowlist
    results = mem.query("research", "wooden train pricing", n_results=5)
    for r in results:
        print(r["text"][:200], r.get("metadata", {}))
"""
import logging
import os

log = logging.getLogger("buslib.memory")

CHROMA_HOST = os.environ.get("CHROMA_HOST", "chromadb")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8000"))


# Default per-agent allowlists. Each list is the set of collections an agent
# is permitted to read. Override via the constructor if needed.
DEFAULT_ALLOWLISTS: dict[str, list[str]] = {
    # Researcher: needs the live research history + decision log
    "RA": ["research", "decisions", "project_context"],
    # Content Editor: brand voice is everything for them
    "CE": ["brand_voice", "decisions", "project_context"],
    # Brand QA: enforces brand_voice and decisions
    "QA": ["brand_voice", "decisions"],
    # Systems Engineer: decisions + project context for prior infra debates
    "SE": ["decisions", "project_context"],
    # Reliability Engineer: same as SE
    "RE": ["decisions", "project_context"],
    # Front-End Engineer: brand voice for tone, product specs for what to build
    "FE": ["brand_voice", "product_specs", "project_context"],
    # Back-End Engineer: decisions, product specs, project context
    "BE": ["decisions", "product_specs", "project_context"],
    # PM: just project context for routing decisions
    "PM": ["project_context"],
    # Graphic Artist (when reactivated)
    "GA": ["brand_voice", "product_specs"],
}


class ReadOnlyMemory:
    """Read-only ChromaDB query helper with per-agent collection allowlisting.

    Lazy client init: the chromadb client is only created on the first query.
    All exceptions are caught and converted to error dicts so the agent's main
    loop never crashes on a memory blip.
    """

    def __init__(self, agent_shorthand: str, allowlist: list[str] | None = None):
        self.agent = agent_shorthand
        self.allowlist = set(allowlist if allowlist is not None
                             else DEFAULT_ALLOWLISTS.get(agent_shorthand, []))
        self._client = None
        self._client_init_failed = False

    def _client_lazy(self):
        if self._client is not None or self._client_init_failed:
            return self._client
        try:
            import chromadb
            self._client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
            return self._client
        except Exception as e:
            log.warning(f"[{self.agent}] ChromaDB client init failed: {e}")
            self._client_init_failed = True
            return None

    def list_collections(self) -> list[str]:
        """Return the agent's allowed collections (sorted)."""
        return sorted(self.allowlist)

    def query(self, collection: str, query_text: str, n_results: int = 5) -> list[dict]:
        """Semantic-search a single collection.

        Returns a list of {text, metadata, distance} dicts. On any failure
        (collection not in allowlist, client unavailable, query error)
        returns a single {error: ...} dict so the caller can detect and
        decide what to do.
        """
        if collection not in self.allowlist:
            return [{
                "error": (
                    f"collection {collection!r} is not in {self.agent}'s allowlist. "
                    f"Allowed: {sorted(self.allowlist)}"
                ),
            }]
        client = self._client_lazy()
        if client is None:
            return [{"error": "chromadb client unavailable"}]
        try:
            coll = client.get_collection(collection)
        except Exception as e:
            return [{"error": f"get_collection({collection!r}) failed: {e}"}]
        try:
            res = coll.query(query_texts=[query_text], n_results=max(1, min(n_results, 25)))
        except Exception as e:
            return [{"error": f"query failed: {e}"}]

        out: list[dict] = []
        # ChromaDB query returns lists-of-lists (one inner list per query_text).
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        ids = (res.get("ids") or [[]])[0]
        for i, doc in enumerate(docs):
            out.append({
                "id": ids[i] if i < len(ids) else None,
                "text": doc,
                "metadata": metas[i] if i < len(metas) else {},
                "distance": dists[i] if i < len(dists) else None,
            })
        return out

    def query_all(self, query_text: str, n_results_per_collection: int = 3) -> dict:
        """Query every collection in the allowlist and return a {collection: results} dict.

        Useful for "what do we know about X across all my collections?" type prompts.
        """
        out: dict[str, list[dict]] = {}
        for coll in self.list_collections():
            out[coll] = self.query(coll, query_text, n_results=n_results_per_collection)
        return out
