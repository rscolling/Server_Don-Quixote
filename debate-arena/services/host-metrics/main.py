"""Host Metrics — read-only system + container metrics for SE.

Reads the don-quixote host's CPU/memory/disk/load via psutil (which talks to
the host's /proc and /sys mounted read-only into this container) and queries
container-level metrics through a tecnativa docker-socket-proxy that exposes
only safe READ endpoints.

NO write capability. NO shell. NO access to anything outside the explicit mounts.

Endpoints:
  GET /health      — service health check
  GET /system      — CPU, memory, swap, load avg, uptime, kernel
  GET /disk        — disk usage per mountpoint
  GET /containers  — list of running containers with image + status
  GET /container_stats  — per-container CPU and memory (via docker stats)
  GET /summary     — everything in one call (for SE's standard prompt injection)
"""
import os
import time
import logging
from datetime import datetime, timezone

import httpx
import psutil
from fastapi import FastAPI, HTTPException

logging.basicConfig(level="INFO", format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
log = logging.getLogger("host-metrics")

DOCKER_PROXY_URL = os.environ.get("DOCKER_PROXY_URL", "http://docker-proxy:2375")
PROXY_TIMEOUT = 5.0

# psutil reads from PROCFS_PATH if set — we mount the host /proc at /host/proc.
# This is set BEFORE psutil imports anything via PROCFS_PATH env var.

app = FastAPI(title="Host Metrics")


def _bytes_to_gb(b: int) -> float:
    return round(b / (1024**3), 2)


@app.get("/health")
def health():
    return {"status": "ok", "service": "host-metrics"}


@app.get("/system")
def system():
    """Read CPU, memory, swap, load, uptime from host /proc."""
    try:
        cpu_pct = psutil.cpu_percent(interval=0.3)  # short sample
        cpu_count_logical = psutil.cpu_count(logical=True)
        cpu_count_physical = psutil.cpu_count(logical=False)
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        load1, load5, load15 = psutil.getloadavg()
        boot = psutil.boot_time()
        uptime_seconds = int(time.time() - boot)
        uptime_days = round(uptime_seconds / 86400, 2)

        return {
            "cpu": {
                "percent_now": cpu_pct,
                "cores_logical": cpu_count_logical,
                "cores_physical": cpu_count_physical,
                "load_avg": {"1m": load1, "5m": load5, "15m": load15},
                "load_per_core_1m": round(load1 / max(cpu_count_logical, 1), 2),
            },
            "memory": {
                "total_gb": _bytes_to_gb(mem.total),
                "used_gb": _bytes_to_gb(mem.used),
                "available_gb": _bytes_to_gb(mem.available),
                "percent": mem.percent,
            },
            "swap": {
                "total_gb": _bytes_to_gb(swap.total),
                "used_gb": _bytes_to_gb(swap.used),
                "percent": swap.percent,
            },
            "uptime_seconds": uptime_seconds,
            "uptime_days": uptime_days,
            "boot_time_utc": datetime.fromtimestamp(boot, tz=timezone.utc).isoformat(),
            "now_utc": datetime.now(tz=timezone.utc).isoformat(),
        }
    except Exception as e:
        log.exception("system metrics failed")
        raise HTTPException(500, f"system metrics failed: {e}")


@app.get("/disk")
def disk():
    """Disk usage per mountpoint visible to this container.

    The host root is mounted read-only at /host/rootfs so we walk that tree
    instead of psutil's default partition list (which sees the container fs).
    """
    results = []
    host_root = "/host/rootfs"
    if not os.path.isdir(host_root):
        # Fallback: just psutil partitions
        for part in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(part.mountpoint)
                results.append({
                    "mountpoint": part.mountpoint,
                    "fstype": part.fstype,
                    "device": part.device,
                    "total_gb": _bytes_to_gb(u.total),
                    "used_gb": _bytes_to_gb(u.used),
                    "free_gb": _bytes_to_gb(u.free),
                    "percent": u.percent,
                })
            except (PermissionError, OSError):
                continue
        return {"mode": "container_view", "mounts": results}

    # Read host /proc/mounts to find real mountpoints
    try:
        with open("/host/proc/1/mounts", "r") as f:
            mount_lines = f.read().splitlines()
    except Exception as e:
        return {"mode": "host_view", "mounts": [], "error": f"could not read mounts: {e}"}

    seen = set()
    for line in mount_lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        device, mountpoint, fstype = parts[0], parts[1], parts[2]
        # Filter to interesting filesystems and avoid duplicates
        if fstype in ("proc", "sysfs", "tmpfs", "devpts", "cgroup", "cgroup2",
                       "overlay", "squashfs", "fuse.snapfuse", "binfmt_misc",
                       "autofs", "mqueue", "pstore", "bpf", "tracefs",
                       "debugfs", "configfs", "fusectl", "securityfs",
                       "hugetlbfs", "rpc_pipefs", "nfsd", "ramfs"):
            continue
        if mountpoint in seen:
            continue
        seen.add(mountpoint)
        # Translate to the host_root view so we can stat it
        translated = host_root if mountpoint == "/" else f"{host_root}{mountpoint}"
        try:
            u = psutil.disk_usage(translated)
            results.append({
                "mountpoint": mountpoint,
                "fstype": fstype,
                "device": device,
                "total_gb": _bytes_to_gb(u.total),
                "used_gb": _bytes_to_gb(u.used),
                "free_gb": _bytes_to_gb(u.free),
                "percent": u.percent,
            })
        except (PermissionError, OSError, FileNotFoundError):
            continue
    return {"mode": "host_view", "mounts": results}


def _docker_get(path: str, params: dict | None = None) -> list | dict:
    """GET against the docker-socket-proxy."""
    try:
        with httpx.Client(timeout=PROXY_TIMEOUT) as client:
            resp = client.get(f"{DOCKER_PROXY_URL}{path}", params=params or {})
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        log.exception(f"docker proxy GET {path} failed")
        return {"error": f"docker proxy unreachable: {e}"}


@app.get("/containers")
def containers():
    """List all running containers via docker socket proxy."""
    data = _docker_get("/containers/json", params={"all": "false"})
    if isinstance(data, dict) and "error" in data:
        return data
    out = []
    for c in data:
        out.append({
            "id": c.get("Id", "")[:12],
            "name": (c.get("Names") or ["?"])[0].lstrip("/"),
            "image": c.get("Image", ""),
            "state": c.get("State", ""),
            "status": c.get("Status", ""),
            "created_unix": c.get("Created"),
        })
    return {"count": len(out), "containers": out}


@app.get("/container_stats")
def container_stats():
    """Snapshot CPU and memory for each running container.

    Calls /containers/{id}/stats?stream=false on the docker-socket-proxy. This
    is a single sample, so CPU% reflects the moment-in-time delta from the
    container's previous reading inside the docker daemon.
    """
    listing = _docker_get("/containers/json", params={"all": "false"})
    if isinstance(listing, dict) and "error" in listing:
        return listing

    out = []
    for c in listing:
        cid = c.get("Id", "")
        name = (c.get("Names") or ["?"])[0].lstrip("/")
        if not cid:
            continue
        stats = _docker_get(f"/containers/{cid}/stats", params={"stream": "false"})
        if isinstance(stats, dict) and "error" in stats:
            out.append({"name": name, "error": stats["error"]})
            continue
        try:
            cpu = stats.get("cpu_stats", {})
            precpu = stats.get("precpu_stats", {})
            cpu_delta = cpu.get("cpu_usage", {}).get("total_usage", 0) - \
                        precpu.get("cpu_usage", {}).get("total_usage", 0)
            sys_delta = cpu.get("system_cpu_usage", 0) - precpu.get("system_cpu_usage", 0)
            online = cpu.get("online_cpus") or len(cpu.get("cpu_usage", {}).get("percpu_usage", []) or [1])
            cpu_pct = round((cpu_delta / sys_delta) * online * 100.0, 2) if sys_delta > 0 else 0.0

            mem_used = stats.get("memory_stats", {}).get("usage", 0)
            mem_limit = stats.get("memory_stats", {}).get("limit", 0)
            mem_pct = round((mem_used / mem_limit) * 100.0, 2) if mem_limit else 0.0

            out.append({
                "name": name,
                "cpu_pct": cpu_pct,
                "mem_used_mb": round(mem_used / (1024**2), 1),
                "mem_limit_mb": round(mem_limit / (1024**2), 1),
                "mem_pct": mem_pct,
            })
        except Exception as e:
            out.append({"name": name, "error": f"stats parse failed: {e}"})
    # Sort by mem_used desc so the heaviest containers float to the top
    out.sort(key=lambda x: x.get("mem_used_mb", 0), reverse=True)
    return {"count": len(out), "containers": out}


@app.get("/summary")
def summary():
    """Fast rollup for SE prompt injection. Skips per-container stats (slow).

    SE can still call /container_stats directly when it needs per-container CPU/mem.
    """
    return {
        "system": system(),
        "disk": disk(),
        "containers": containers(),
    }




@app.get("/logs")
def container_logs(name: str, tail: int = 100, since_seconds: int = 3600,
                   grep: str | None = None):
    """Read recent logs for a container via docker-socket-proxy.

    Query params:
      name           — container name (e.g. atg-bob, atg-pm)
      tail           — max lines to return after grep filtering (default 100, max 500)
      since_seconds  — how far back to read (default 1 hour)
      grep           — optional case-sensitive substring filter

    Returns plain text. Logs come back from the proxy with the docker
    multiplexed-stream framing — we strip the 8-byte headers when present
    and decode as UTF-8 with errors='replace'.
    """
    tail = max(1, min(int(tail), 500))
    params = {"stdout": "true", "stderr": "true", "tail": str(tail * 4 if grep else tail),
              "since": str(int(time.time()) - max(1, int(since_seconds)))}
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(f"{DOCKER_PROXY_URL}/containers/{name}/logs", params=params)
            if r.status_code == 404:
                raise HTTPException(404, f"container not found: {name}")
            if r.status_code >= 400:
                raise HTTPException(r.status_code, f"docker-proxy error: {r.text[:200]}")
            raw = r.content
    except HTTPException:
        raise
    except Exception as e:
        log.exception("logs proxy failed")
        raise HTTPException(500, f"logs proxy failed: {e}")

    # Strip docker stream framing if present (8-byte headers per chunk)
    text_parts: list[str] = []
    i = 0
    n = len(raw)
    while i < n:
        # Header is 8 bytes: stream_type (1) + reserved (3) + size (4 BE)
        if i + 8 <= n and raw[i] in (0, 1, 2):
            size = int.from_bytes(raw[i+1:i+4] + raw[i+4:i+8][:4], "big") if False else                    int.from_bytes(raw[i+4:i+8], "big")
            chunk = raw[i+8:i+8+size]
            text_parts.append(chunk.decode("utf-8", errors="replace"))
            i += 8 + size
        else:
            # No framing — just decode the rest
            text_parts.append(raw[i:].decode("utf-8", errors="replace"))
            break
    text = "".join(text_parts)

    if grep:
        text = "\n".join(line for line in text.splitlines() if grep in line)

    # Apply tail again post-grep
    lines = text.splitlines()
    if len(lines) > tail:
        lines = lines[-tail:]
    return {"container": name, "lines": len(lines), "text": "\n".join(lines)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8111)
