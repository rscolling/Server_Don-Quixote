"""ChromaDB shared memory — BOB mediates all writes."""

import chromadb
from app.config import CHROMADB_URL

_client = None

COLLECTIONS = {
    "brand_voice": "ATG brand guidelines, tone, color palette, messaging rules",
    "decisions": "Major decisions made by Rob, logged with date and context",
    "research": "Research findings from agents — market data, competitor analysis",
    "product_specs": "Product specifications, game design docs, feature lists",
    "project_context": "Active project briefs, status updates, blockers",
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
