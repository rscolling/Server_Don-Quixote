"""Researcher Agent (RA) — research, analysis, fact-checking with live web search + attachment reading."""
import base64
import json
import logging
import mimetypes
from datetime import datetime
from pathlib import Path

log = logging.getLogger("researcher")

# Files RA is allowed to read must live under this root (its only RW mount).
ATTACHMENT_ROOT = Path("/agent-share")
# Hard cap per file. Claude vision/PDF have their own limits; this is a sanity bound.
MAX_ATTACHMENT_BYTES = 30 * 1024 * 1024  # 30 MB
# Total cap across all attachments in one task.
MAX_TOTAL_ATTACHMENT_BYTES = 60 * 1024 * 1024  # 60 MB

_IMAGE_MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp",
}
_PDF_MIME = {".pdf": "application/pdf"}
_TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".yaml", ".yml", ".log", ".html", ".htm"}

# Max tool-use rounds in a single research call. Claude can issue multiple
# searches per round. This caps total LLM <-> tool round trips, not searches.
MAX_TOOL_ROUNDS = 6


SYSTEM_PROMPT = """You are the Researcher Agent (RA) for Appalachian Toys & Games.
Your job is to gather, synthesize, and summarize information from the LIVE WEB,
not just from your training data.

## Tools available
- `query_memory(collection, query, n_results)` — Search BOB's shared ChromaDB memory.
  ALWAYS try this FIRST for non-trivial research tasks. We may already have notes,
  decisions, or prior research on the topic. Allowed collections for you: `research`,
  `decisions`, `project_context`. Burning a web search when there's a cached answer
  is wasteful. If `query_memory` returns something relevant, quote it and cite it as
  an internal source.
- `search_web(query, max_results)` — DuckDuckGo live search. Use this aggressively.
  Search BEFORE making factual claims. Search AGAIN to verify uncertain claims.
  Search for COMPETITORS, PRICES, RECENT NEWS, REGULATIONS, and anything time-sensitive.
  Multiple short queries beat one long query. You can call this tool many times.
- `fetch_url(url)` — Fetch a single URL and return its main article text (cleaned of
  nav/ads/boilerplate via trafilatura). Use this AFTER search_web surfaces a promising
  result and you need the FULL article body, not just the snippet. Typical pattern:
  search → spot a high-signal result → fetch it → quote specifics. One or two fetches
  per task is normal; do not fetch every search result.

## Attachments
If the task includes attachments (images, PDFs, text files), they are loaded
into the FIRST user message of this conversation as content blocks BEFORE the
task description. **Read them carefully** before searching or making claims.
- For images: describe what you see, extract data from charts/screenshots, read
  any text visible in the image.
- For PDFs: read the full document; quote specific pages when relevant.
- For text/CSV/JSON files: parse them and reference specific rows or values.
The attachment file paths will also be listed at the top of the task description
as `Attachments: [path1, path2, ...]` so you can refer to them by name.

## Behavior
- **Search first, opine second.** Do not summarize from training data when fresh
  data exists on the web. Your training data is months out of date.
- **Cite sources with URLs.** Every key finding must have at least one URL.
- **Distinguish search results from inference.** If the web didn't answer a question,
  say so explicitly in `caveats`. Do not invent.
- **Search for the negative.** If you make a claim, do at least one search trying
  to disprove it. Note disconfirming evidence in `caveats`.
- **Plain language summaries.** No buzzwords. ATG voice: warm, direct, Appalachian.
- **Date-stamp the work.** Today's date is in the date field.

## Output Format (return as JSON, fenced or unfenced)
{
  "topic": "...",
  "date": "YYYY-MM-DD",
  "queries_run": ["the actual search queries you ran"],
  "key_findings": [
    {"finding": "...", "sources": ["https://..."], "confidence": "high|medium|low"}
  ],
  "summary": "1-3 paragraph plain-language synthesis",
  "caveats": ["anything the web didn't answer, anything still uncertain"],
  "confidence_overall": "high|medium|low",
  "next_searches_recommended": ["queries that would tighten this further"]
}

If the task is purely a critique or fact-check (no original research needed),
you can use search_web to verify the specific claims in question.
"""


SEARCH_TOOL_DEF = {
    "name": "search_web",
    "description": (
        "Search the live internet via DuckDuckGo. Use this to find current "
        "information, prices, competitors, news, regulations, or to verify facts. "
        "Returns up to max_results entries with title, URL, and snippet. "
        "Multiple short focused queries beat one long query."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query. Keep it short and focused.",
            },
            "max_results": {
                "type": "integer",
                "description": "Max results to return (default 5, cap 10)",
                "default": 5,
            },
        },
        "required": ["query"],
    },
}


def _extract_json(text: str):
    """Strip markdown code fences from a Claude response and parse as JSON.

    Handles three cases:
      1. Bare JSON                          -> parsed directly
      2. ```json ... ```  fenced            -> fences stripped, then parsed
      3. Preamble + ```json ... ``` fenced  -> preamble stripped, then fences,
         then parsed. Falls back to a first-{ / last-} slice if all else fails.
    """
    import json as _j
    s = text.strip()
    # Step 1: try a direct parse on the whole thing
    try:
        return _j.loads(s)
    except Exception:
        pass
    # Step 2: strip leading code fence (with or without language tag)
    s2 = s
    if s2.startswith("```json"):
        s2 = s2[7:].lstrip("\n")
    elif s2.startswith("```"):
        s2 = s2[3:].lstrip("\n")
    if s2.endswith("```"):
        s2 = s2[:-3].rstrip()
    try:
        return _j.loads(s2)
    except Exception:
        pass
    # Step 3: find the first { and the LAST } in the original text and parse that slice
    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        try:
            return _j.loads(s[start:end + 1])
        except Exception:
            pass
    # Last resort: re-raise so the caller's existing fallback path handles it
    return _j.loads(s2)
def _safe_attachment_path(p: str) -> Path | None:
    """Resolve an attachment path against ATTACHMENT_ROOT, rejecting escapes."""
    if not p:
        return None
    candidate = Path(p)
    if not candidate.is_absolute():
        candidate = ATTACHMENT_ROOT / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(ATTACHMENT_ROOT.resolve())
    except (ValueError, OSError):
        return None
    if not resolved.exists() or not resolved.is_file():
        return None
    return resolved


def _load_attachments(file_paths: list) -> tuple[list, list]:
    """Build Claude content blocks from a list of file paths.

    Returns (content_blocks, load_log) where load_log is a list of dicts
    describing what was loaded, skipped, or rejected — saved with the deliverable.
    """
    blocks: list = []
    load_log: list = []
    total_bytes = 0

    if not file_paths:
        return blocks, load_log

    for raw in file_paths:
        if not isinstance(raw, str):
            load_log.append({"path": str(raw), "status": "rejected", "reason": "not a string"})
            continue
        target = _safe_attachment_path(raw)
        if target is None:
            load_log.append({"path": raw, "status": "rejected",
                             "reason": "outside /agent-share or not a file"})
            continue
        size = target.stat().st_size
        if size > MAX_ATTACHMENT_BYTES:
            load_log.append({"path": str(target), "status": "skipped",
                             "reason": f"file too large ({size} bytes > {MAX_ATTACHMENT_BYTES})"})
            continue
        if total_bytes + size > MAX_TOTAL_ATTACHMENT_BYTES:
            load_log.append({"path": str(target), "status": "skipped",
                             "reason": "total attachment budget exceeded"})
            continue

        ext = target.suffix.lower()

        # Image — Claude vision content block
        if ext in _IMAGE_MIME:
            mime = _IMAGE_MIME[ext]
            data_b64 = base64.standard_b64encode(target.read_bytes()).decode("ascii")
            blocks.append({"type": "text", "text": f"[attachment: {target.name}]"})
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": mime, "data": data_b64},
            })
            total_bytes += size
            load_log.append({"path": str(target), "status": "loaded", "kind": "image", "bytes": size})
            continue

        # PDF — Claude native document block
        if ext in _PDF_MIME:
            data_b64 = base64.standard_b64encode(target.read_bytes()).decode("ascii")
            blocks.append({"type": "text", "text": f"[attachment: {target.name}]"})
            blocks.append({
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": data_b64},
            })
            total_bytes += size
            load_log.append({"path": str(target), "status": "loaded", "kind": "pdf", "bytes": size})
            continue

        # Text-ish — inline as a fenced text block (small files only)
        if ext in _TEXT_EXT:
            try:
                text = target.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                load_log.append({"path": str(target), "status": "error", "reason": str(e)})
                continue
            # Soft cap inline text at 200 KB to avoid blowing the prompt
            if len(text) > 200_000:
                text = text[:200_000] + "\n\n[... truncated ...]"
            fence_lang = ext.lstrip(".")
            blocks.append({
                "type": "text",
                "text": f"[attachment: {target.name}]\n```{fence_lang}\n{text}\n```",
            })
            total_bytes += size
            load_log.append({"path": str(target), "status": "loaded", "kind": "text", "bytes": size})
            continue

        # Unknown extension — refuse
        load_log.append({"path": str(target), "status": "rejected",
                         "reason": f"unsupported extension: {ext}"})

    return blocks, load_log



FETCH_URL_TOOL_DEF = {
    "name": "fetch_url",
    "description": (
        "Fetch a single URL and return its main article text, stripped of nav, "
        "ads, and boilerplate. Use this AFTER search_web has surfaced a promising "
        "result and you need the full article body, not just the snippet. "
        "Pass the exact URL from the search result. Returns clean text plus "
        "title and a brief metadata block. Caps content at ~50 KB. Use sparingly "
        "(one or two fetches per task is typical, not one per result)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch. Must be http:// or https://.",
            },
        },
        "required": ["url"],
    },
}

MAX_FETCH_BYTES = 50_000  # cap on extracted text per URL


def _fetch_url(url: str) -> dict:
    """Fetch a URL and return clean main-content text via trafilatura.

    Returns a dict (never raises) with: url, status, title, text, length, error?
    """
    if not isinstance(url, str) or not (url.startswith("http://") or url.startswith("https://")):
        return {"url": url, "status": "rejected", "error": "url must start with http:// or https://"}
    try:
        import httpx
        import trafilatura
    except Exception as e:
        return {"url": url, "status": "error", "error": f"missing dependency: {e}"}
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True,
                          headers={"User-Agent": "atg-research-agent/1.0"}) as client:
            r = client.get(url)
            if r.status_code >= 400:
                return {"url": url, "status": "http_error", "error": f"HTTP {r.status_code}"}
            html = r.text
    except Exception as e:
        log.warning(f"[RA] fetch_url HTTP failed for {url}: {e}")
        return {"url": url, "status": "fetch_failed", "error": str(e)}
    try:
        # trafilatura.extract returns clean main-content text or None
        text = trafilatura.extract(
            html, include_comments=False, include_tables=True,
            favor_recall=True, output_format="txt",
        ) or ""
        # Best-effort title extraction via metadata
        meta = trafilatura.extract_metadata(html)
        title = (getattr(meta, "title", None) or "")[:300] if meta else ""
        if len(text) > MAX_FETCH_BYTES:
            text = text[:MAX_FETCH_BYTES] + "\n\n[... truncated ...]"
        return {
            "url": url,
            "status": "ok",
            "title": title,
            "text": text,
            "length": len(text),
        }
    except Exception as e:
        log.warning(f"[RA] trafilatura extract failed for {url}: {e}")
        return {"url": url, "status": "extract_failed", "error": str(e)}



QUERY_MEMORY_TOOL_DEF = {
    "name": "query_memory",
    "description": (
        "Search BOB's shared ChromaDB memory for prior research, decisions, project "
        "context, or brand guidance. Use this BEFORE doing fresh web research — "
        "we may already have notes on this topic. Returns the most semantically "
        "similar entries from a single collection. Allowed collections for RA: "
        "research, decisions, project_context."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "collection": {
                "type": "string",
                "description": "Which collection to search. One of: research, decisions, project_context.",
                "enum": ["research", "decisions", "project_context"],
            },
            "query": {
                "type": "string",
                "description": "Free-form natural-language query for semantic search.",
            },
            "n_results": {
                "type": "integer",
                "description": "Max number of results (default 5, cap 10).",
                "default": 5,
            },
        },
        "required": ["collection", "query"],
    },
}


_memory_singleton = None


def _get_memory():
    """Lazy singleton ReadOnlyMemory for RA. Imported lazily so missing chromadb
    never breaks the module load — the tool just returns an error envelope."""
    global _memory_singleton
    if _memory_singleton is not None:
        return _memory_singleton
    try:
        from buslib.memory import ReadOnlyMemory
        _memory_singleton = ReadOnlyMemory("RA")
        return _memory_singleton
    except Exception as e:
        log.warning(f"[RA] buslib.memory init failed: {e}")
        return None


def _query_memory(collection: str, query: str, n_results: int = 5) -> dict:
    """Wrap ReadOnlyMemory.query for the tool dispatch. Always returns a dict."""
    mem = _get_memory()
    if mem is None:
        return {"collection": collection, "query": query,
                "error": "memory unavailable", "results": []}
    results = mem.query(collection, query, n_results=n_results)
    if results and isinstance(results[0], dict) and "error" in results[0]:
        return {"collection": collection, "query": query,
                "error": results[0]["error"], "results": []}
    return {"collection": collection, "query": query,
            "count": len(results), "results": results}


def _search_web(query: str, max_results: int = 5) -> dict:
    """Live DuckDuckGo search. Returns a dict (not a string) for the tool result."""
    max_results = max(1, min(int(max_results or 5), 10))
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results))
        cleaned = [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": (r.get("body", "") or "")[:400],
            }
            for r in (raw or [])
        ]
        return {"query": query, "results": cleaned, "count": len(cleaned)}
    except Exception as e:
        log.exception("search_web failed")
        return {"query": query, "error": str(e), "results": [], "count": 0}


def _run_with_tools(claude_client, model: str, system: str,
                    user_message: str, max_tokens: int,
                    attachment_blocks: list | None = None) -> tuple[str, list, list]:
    """Run a Claude conversation with tool use. Returns (final_text, queries, tool_results).

    If `attachment_blocks` is provided, they are prepended to the first user
    message as content blocks (images / PDFs / inlined text). The text portion
    of the user message is appended after them so the model sees attachments
    first, then the instructions.
    """
    if attachment_blocks:
        first_content = list(attachment_blocks) + [{"type": "text", "text": user_message}]
    else:
        first_content = user_message
    messages = [{"role": "user", "content": first_content}]
    queries: list[str] = []
    tool_results: list[dict] = []

    for round_idx in range(MAX_TOOL_ROUNDS):
        resp = claude_client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            tools=[SEARCH_TOOL_DEF, FETCH_URL_TOOL_DEF, QUERY_MEMORY_TOOL_DEF],
            messages=messages,
        )

        # Append the assistant turn verbatim (preserves tool_use blocks)
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            # Final answer — pull out the text content
            final_text = ""
            for block in resp.content:
                if getattr(block, "type", None) == "text":
                    final_text += block.text
            return final_text, queries, tool_results

        # Execute every tool_use block in this turn and build tool_result content
        tool_result_blocks = []
        for block in resp.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            args = block.input or {}
            if block.name == "search_web":
                q = args.get("query", "")
                n = args.get("max_results", 5)
                log.info(f"[RA] search_web: {q!r} (max={n})")
                result = _search_web(q, n)
                queries.append(q)
                tool_results.append(result)
                is_err = "error" in result
            elif block.name == "fetch_url":
                url = args.get("url", "")
                log.info(f"[RA] fetch_url: {url}")
                result = _fetch_url(url)
                tool_results.append({"_fetch": result})
                is_err = result.get("status") not in ("ok",)
            elif block.name == "query_memory":
                coll = args.get("collection", "")
                q = args.get("query", "")
                n = args.get("n_results", 5)
                log.info(f"[RA] query_memory: {coll}/{q!r} (n={n})")
                result = _query_memory(coll, q, n)
                tool_results.append({"_memory": result})
                is_err = "error" in result
            else:
                result = {"error": f"unknown tool: {block.name}"}
                is_err = True
            tool_result_blocks.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result),
                "is_error": is_err,
            })
        messages.append({"role": "user", "content": tool_result_blocks})

    # Hit the round cap — ask for a final answer with no tools
    log.warning(f"[RA] Hit MAX_TOOL_ROUNDS ({MAX_TOOL_ROUNDS}); forcing final answer")
    messages.append({
        "role": "user",
        "content": "You have hit the maximum search budget. Stop searching and "
                   "return your final research JSON now based on what you have.",
    })
    final = claude_client.messages.create(
        model=model, max_tokens=max_tokens, system=system, messages=messages,
    )
    final_text = ""
    for block in final.content:
        if getattr(block, "type", None) == "text":
            final_text += block.text
    return final_text, queries, tool_results


def execute_research(claude_client, task: str, model: str = "claude-sonnet-4-5",
                     file_paths: list | None = None) -> dict:
    """Run a research task with live web search, attachment reading, and structured output.

    `file_paths` is an optional list of paths under /agent-share/ to load as
    attachments (images, PDFs, text). They are presented to Claude before the
    task description, so the model reads them first.
    """
    attachment_blocks, attachment_log = _load_attachments(file_paths or [])

    attachments_header = ""
    if attachment_log:
        loaded_paths = [a["path"] for a in attachment_log if a.get("status") == "loaded"]
        if loaded_paths:
            attachments_header = "Attachments: " + ", ".join(loaded_paths) + "\n\n"

    user_msg = (
        f"{attachments_header}Research task:\n{task}\n\n"
        f"Return the JSON output described in the system prompt."
    )
    text, queries, tool_results = _run_with_tools(
        claude_client, model, SYSTEM_PROMPT, user_msg, max_tokens=8192,
        attachment_blocks=attachment_blocks,
    )

    try:
        result = _extract_json(text)
    except json.JSONDecodeError:
        result = {
            "topic": task[:200],
            "date": datetime.now().strftime("%Y-%m-%d"),
            "queries_run": queries,
            "key_findings": [],
            "summary": text[:2000],
            "caveats": ["Response was not parseable JSON"],
            "confidence_overall": "low",
            "_raw": text,
            "_parse_error": True,
        }

    # Always attach the actual queries we ran (the agent's self-report can drift)
    result["_queries_executed"] = queries
    result["_tool_call_count"] = len(tool_results)
    result["_total_results_seen"] = sum(t.get("count", 0) for t in tool_results)
    result["_attachments_loaded"] = attachment_log

    output_dir = Path("/agent-share/workspace/research")
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_ " else "" for c in task[:40]).strip().replace(" ", "_")
    path = output_dir / f"RA_research_{safe}_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    result["_file_path"] = str(path)
    return result


def critique_output(claude_client, output: dict, task: str,
                    model: str = "claude-sonnet-4-5") -> dict:
    """Critique another agent's output from RA's perspective (fact-checking with live search)."""
    user_msg = (
        f"Another agent produced this output for the task: {task}\n\n"
        f"Output to critique:\n{json.dumps(output, indent=2)[:8000]}\n\n"
        f"Use search_web to verify any factual claims. Focus on FACTUAL ACCURACY,\n"
        f"SOURCE QUALITY, and whether the claims hold up under live search.\n"
        f"Find the WEAKEST factual point and push back specifically.\n\n"
        f"Respond with JSON:\n"
        f'{{"verdict": "approve|revise|reject", '
        f'"weakest_point": "...", '
        f'"specific_feedback": "...", '
        f'"contradicting_sources": ["url", ...], '
        f'"confidence": 0.0}}'
    )
    text, _queries, _results = _run_with_tools(
        claude_client, model, SYSTEM_PROMPT, user_msg, max_tokens=2048,
    )
    try:
        return _extract_json(text)
    except json.JSONDecodeError:
        return {"verdict": "revise", "weakest_point": "Parse error",
                "specific_feedback": text[:1000],
                "contradicting_sources": [], "confidence": 0.5}


def revise_output(claude_client, original: dict, critiques: list, task: str,
                  model: str = "claude-sonnet-4-5") -> dict:
    """Revise research output based on critiques, with new live searches if needed."""
    critique_text = "\n\n".join([
        f"From {c.get('from_critic', 'unknown')}: {json.dumps(c)}" for c in critiques
    ])
    user_msg = (
        f"You produced this research for: {task}\n\n"
        f"Your output:\n{json.dumps(original, indent=2)[:8000]}\n\n"
        f"You received these critiques:\n{critique_text}\n\n"
        f"Use search_web to address valid critiques. You may push back on critiques\n"
        f"you disagree with — but back the pushback with sources. Return revised JSON\n"
        f"in the same format as the original."
    )
    text, queries, tool_results = _run_with_tools(
        claude_client, model, SYSTEM_PROMPT, user_msg, max_tokens=8192,
    )
    try:
        result = _extract_json(text)
    except json.JSONDecodeError:
        return {"revised_output": text[:2000], "_parse_error": True,
                "_queries_executed": queries}
    result["_queries_executed"] = queries
    result["_tool_call_count"] = len(tool_results)
    return result


# Backwards-compat alias — main.py imports execute_writing for non-research agents,
# but historically RA used execute_research. Keep both names valid.
execute_writing = execute_research
