"""Code Sandbox — static lint/parse checks for FE/BE deliverables.

A small sidecar service that exposes static-analysis endpoints to other agents
on the agent-net network. NO CODE EXECUTION in v1 — only parse and lint.
This is intentional: code execution adds real security work and isn't needed
to catch the bugs FE/BE actually produce.

Endpoints:
  GET  /health
  POST /check/python   {"content": "..."} or {"path": "/agent-share/..."}
  POST /check/html     {"content": "..."} or {"path": "/agent-share/..."}
  POST /check/css      {"content": "..."} or {"path": "/agent-share/..."}
  POST /check/json     {"content": "..."} or {"path": "/agent-share/..."}
  POST /check/file     {"path": "/agent-share/..."}    — dispatches by extension
  POST /check/batch    {"paths": ["...", "..."]}        — runs /check/file on each

Path safety:
- All paths must resolve under /agent-share/ (the only mount).
- `..`, absolute paths outside the mount, and missing files are rejected.
- Files larger than 5 MB are rejected (sandbox is for source code, not binaries).
"""
import json
import logging
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level="INFO", format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
log = logging.getLogger("code-sandbox")

WORKSPACE_ROOT = Path("/agent-share")
MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB

app = FastAPI(title="Code Sandbox")


class CheckRequest(BaseModel):
    content: str | None = None
    path: str | None = None


class BatchRequest(BaseModel):
    paths: list[str]


def _safe_path(p: str) -> Path:
    """Resolve a path against WORKSPACE_ROOT, raising 400 on escape."""
    if not p:
        raise HTTPException(400, "empty path")
    candidate = Path(p)
    if not candidate.is_absolute():
        candidate = WORKSPACE_ROOT / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(WORKSPACE_ROOT.resolve())
    except (ValueError, OSError):
        raise HTTPException(400, f"path outside workspace: {p}")
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(404, f"file not found: {p}")
    if resolved.stat().st_size > MAX_FILE_BYTES:
        raise HTTPException(413, f"file too large: {resolved.stat().st_size} bytes")
    return resolved


def _resolve_content(req: CheckRequest) -> tuple[str, str | None]:
    """Returns (content, source_path_or_None)."""
    if req.content is not None:
        return req.content, None
    if req.path:
        target = _safe_path(req.path)
        return target.read_text(encoding="utf-8", errors="replace"), str(target)
    raise HTTPException(400, "must provide either content or path")


def _check_python(content: str, source: str | None) -> dict:
    """Syntax check via py_compile + lint via ruff."""
    issues: list[dict] = []
    # Syntax check
    try:
        compile(content, source or "<string>", "exec")
    except SyntaxError as e:
        issues.append({
            "tool": "py_compile",
            "severity": "error",
            "line": e.lineno,
            "col": e.offset,
            "message": str(e.msg),
        })
        return {"language": "python", "issues": issues, "ok": False, "source": source}

    # Ruff lint
    try:
        proc = subprocess.run(
            ["ruff", "check", "--output-format=json", "--no-fix", "-"],
            input=content,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.stdout.strip():
            try:
                ruff_out = json.loads(proc.stdout)
                for item in ruff_out:
                    issues.append({
                        "tool": "ruff",
                        "severity": "warning",
                        "line": item.get("location", {}).get("row"),
                        "col": item.get("location", {}).get("column"),
                        "code": item.get("code"),
                        "message": item.get("message"),
                    })
            except json.JSONDecodeError:
                pass
    except subprocess.TimeoutExpired:
        issues.append({"tool": "ruff", "severity": "error", "message": "ruff timed out"})
    except FileNotFoundError:
        log.warning("ruff not installed — skipping lint")

    return {
        "language": "python",
        "issues": issues,
        "ok": not any(i.get("severity") == "error" for i in issues),
        "source": source,
    }


def _check_html(content: str, source: str | None) -> dict:
    """HTML parse via html5lib (strict mode logs syntax issues)."""
    import html5lib
    issues: list[dict] = []
    try:
        parser = html5lib.HTMLParser(strict=False)
        parser.parse(content)
        for err in parser.errors:
            # html5lib errors are tuples: ((line, col), code, datavars)
            try:
                pos, code, _data = err
                line, col = pos
            except (ValueError, TypeError):
                line, col, code = None, None, str(err)
            issues.append({
                "tool": "html5lib",
                "severity": "warning",
                "line": line,
                "col": col,
                "code": str(code),
                "message": str(code),
            })
    except Exception as e:
        issues.append({"tool": "html5lib", "severity": "error", "message": str(e)})
        return {"language": "html", "issues": issues, "ok": False, "source": source}
    return {
        "language": "html",
        "issues": issues,
        "ok": not any(i.get("severity") == "error" for i in issues),
        "source": source,
    }


def _check_css(content: str, source: str | None) -> dict:
    """CSS parse via tinycss2."""
    import tinycss2
    issues: list[dict] = []
    try:
        rules = tinycss2.parse_stylesheet(content, skip_whitespace=True, skip_comments=True)
        for rule in rules:
            if rule.type == "error":
                issues.append({
                    "tool": "tinycss2",
                    "severity": "error",
                    "line": getattr(rule, "source_line", None),
                    "col": getattr(rule, "source_column", None),
                    "message": rule.message,
                })
    except Exception as e:
        issues.append({"tool": "tinycss2", "severity": "error", "message": str(e)})
        return {"language": "css", "issues": issues, "ok": False, "source": source}
    return {
        "language": "css",
        "issues": issues,
        "ok": not any(i.get("severity") == "error" for i in issues),
        "source": source,
    }


def _check_json(content: str, source: str | None) -> dict:
    """JSON parse via json.loads."""
    issues: list[dict] = []
    try:
        json.loads(content)
    except json.JSONDecodeError as e:
        issues.append({
            "tool": "json",
            "severity": "error",
            "line": e.lineno,
            "col": e.colno,
            "message": e.msg,
        })
    return {
        "language": "json",
        "issues": issues,
        "ok": not issues,
        "source": source,
    }


def _check_by_ext(target: Path) -> dict:
    """Dispatch a file to the right checker by extension."""
    ext = target.suffix.lower()
    content = target.read_text(encoding="utf-8", errors="replace")
    if ext == ".py":
        return _check_python(content, str(target))
    if ext in (".html", ".htm"):
        return _check_html(content, str(target))
    if ext == ".css":
        return _check_css(content, str(target))
    if ext == ".json":
        return _check_json(content, str(target))
    return {
        "language": "unknown",
        "issues": [],
        "ok": True,
        "source": str(target),
        "skipped": f"no checker for extension {ext}",
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "code-sandbox"}


@app.post("/check/python")
def check_python_endpoint(req: CheckRequest):
    content, source = _resolve_content(req)
    return _check_python(content, source)


@app.post("/check/html")
def check_html_endpoint(req: CheckRequest):
    content, source = _resolve_content(req)
    return _check_html(content, source)


@app.post("/check/css")
def check_css_endpoint(req: CheckRequest):
    content, source = _resolve_content(req)
    return _check_css(content, source)


@app.post("/check/json")
def check_json_endpoint(req: CheckRequest):
    content, source = _resolve_content(req)
    return _check_json(content, source)


@app.post("/check/file")
def check_file_endpoint(req: CheckRequest):
    if not req.path:
        raise HTTPException(400, "path is required")
    target = _safe_path(req.path)
    return _check_by_ext(target)


@app.post("/check/batch")
def check_batch_endpoint(req: BatchRequest):
    results = []
    for p in req.paths:
        try:
            target = _safe_path(p)
            results.append(_check_by_ext(target))
        except HTTPException as e:
            results.append({"source": p, "ok": False, "issues": [
                {"tool": "sandbox", "severity": "error", "message": e.detail},
            ]})
    summary = {
        "total": len(results),
        "ok": sum(1 for r in results if r.get("ok")),
        "with_errors": sum(1 for r in results if not r.get("ok")),
        "total_issues": sum(len(r.get("issues", [])) for r in results),
    }
    return {"summary": summary, "results": results}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8110)
