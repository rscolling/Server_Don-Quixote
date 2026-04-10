"""MCP client — fetch tools from external Model Context Protocol servers.

BOB connects to one or more MCP servers at startup, fetches their tool
catalog, and adds those tools to his LangGraph agent. Each fetched tool
passes through the same firewall gate as native tools.

Config: See MCP_CLIENT_CONFIG_PATH in config.py. The file is JSON listing
servers like:
[
  {"name": "github", "transport": "sse", "url": "https://mcp.example.com/github"},
  {"name": "filesystem", "transport": "stdio", "command": "npx",
   "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data"]}
]

Two transports supported:
  - "sse" / "streamable-http" — long-running HTTP servers (preferred for prod)
  - "stdio" — subprocess-based servers (common for local CLI tools)
"""

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("bob.mcp_client")

# Cached client and tools — populated at startup
_mcp_client: Any = None
_mcp_tools: list = []


def _expand_env_vars(obj: Any) -> Any:
    """Recursively expand ${VAR} references in string values."""
    if isinstance(obj, str):
        return re.sub(
            r"\$\{([^}]+)\}",
            lambda m: os.environ.get(m.group(1), m.group(0)),
            obj,
        )
    if isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_vars(v) for v in obj]
    return obj


def load_server_config(path: str) -> list[dict]:
    """Load the MCP servers config file. Returns a list of server dicts.

    String values may contain ${ENV_VAR} references which are expanded
    from the process environment (useful for API keys in URLs/headers).

    Returns an empty list if the file doesn't exist or is malformed.
    """
    if not os.path.exists(path):
        logger.info(f"No MCP client config at {path} — skipping MCP client setup")
        return []

    try:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, list):
            logger.warning(f"MCP config at {path} is not a list — ignoring")
            return []
        return _expand_env_vars(data)
    except json.JSONDecodeError as e:
        logger.error(f"MCP config at {path} is not valid JSON: {e}")
        return []
    except Exception as e:
        logger.error(f"Failed to load MCP config at {path}: {e}")
        return []


def _build_connections_dict(servers: list[dict]) -> dict[str, dict]:
    """Convert our config format into the format MultiServerMCPClient expects.

    MultiServerMCPClient takes a dict keyed by server name, with each value
    being the connection config for that server.
    """
    connections = {}
    for server in servers:
        name = server.get("name")
        if not name:
            logger.warning(f"MCP server missing 'name' field, skipping: {server}")
            continue

        transport = server.get("transport", "sse").lower()

        if transport == "stdio":
            command = server.get("command")
            if not command:
                logger.warning(f"MCP stdio server '{name}' missing 'command', skipping")
                continue
            connections[name] = {
                "transport": "stdio",
                "command": command,
                "args": server.get("args", []),
                "env": server.get("env", {}),
            }
        elif transport in ("sse", "streamable-http", "http"):
            url = server.get("url")
            if not url:
                logger.warning(f"MCP {transport} server '{name}' missing 'url', skipping")
                continue
            # langchain-mcp-adapters uses "streamable_http" or "sse"
            normalized = "streamable_http" if transport in ("streamable-http", "http") else "sse"
            conn = {
                "transport": normalized,
                "url": url,
            }
            # Optional auth headers
            if "headers" in server:
                conn["headers"] = server["headers"]
            connections[name] = conn
        else:
            logger.warning(f"MCP server '{name}' has unknown transport '{transport}', skipping")

    return connections


async def init_mcp_client(config_path: str, fetch_timeout: float = 15.0) -> list:
    """Initialize the MCP client and fetch all tools from configured servers.

    Returns a list of LangChain-compatible tools that can be added to BOB's
    agent. Returns an empty list if no servers are configured or all fail.
    """
    global _mcp_client, _mcp_tools

    servers = load_server_config(config_path)
    if not servers:
        return []

    connections = _build_connections_dict(servers)
    if not connections:
        logger.info("No valid MCP server connections in config")
        return []

    try:
        # langchain-mcp-adapters provides MultiServerMCPClient
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        logger.error(
            "langchain-mcp-adapters not installed. "
            "Add it to requirements.txt: langchain-mcp-adapters>=0.1.0"
        )
        return []

    try:
        _mcp_client = MultiServerMCPClient(connections)
    except Exception as e:
        logger.error(f"Failed to construct MCP client: {e}")
        return []

    # Fetch tools from all servers with a timeout
    try:
        _mcp_tools = await asyncio.wait_for(
            _mcp_client.get_tools(),
            timeout=fetch_timeout,
        )
    except asyncio.TimeoutError:
        logger.error(f"MCP tool fetch timed out after {fetch_timeout}s")
        return []
    except Exception as e:
        logger.error(f"Failed to fetch MCP tools: {e}")
        return []

    # Tag each tool with its source server name for the firewall
    for tool in _mcp_tools:
        # Prefix tool name with mcp_<server>_ if not already prefixed
        # so they're distinguishable from native BOB tools in the audit log
        if hasattr(tool, "name") and not tool.name.startswith("mcp_"):
            # Find which server this came from by checking metadata
            # langchain-mcp-adapters preserves the namespace
            pass  # name stays as-is; firewall handles classification

    logger.info(
        f"MCP client loaded {len(_mcp_tools)} tools from "
        f"{len(connections)} server(s): {list(connections.keys())}"
    )
    return _mcp_tools


def get_loaded_tools() -> list:
    """Return the list of MCP tools loaded at startup."""
    return _mcp_tools


def get_loaded_tool_names() -> list[str]:
    """Return just the names of MCP tools loaded at startup."""
    return [t.name for t in _mcp_tools if hasattr(t, "name")]


async def close_mcp_client():
    """Cleanup MCP client connections at shutdown."""
    global _mcp_client
    if _mcp_client is None:
        return
    try:
        # MultiServerMCPClient may have a close/aclose method depending on version
        if hasattr(_mcp_client, "aclose"):
            await _mcp_client.aclose()
        elif hasattr(_mcp_client, "close"):
            close = _mcp_client.close
            if asyncio.iscoroutinefunction(close):
                await close()
            else:
                close()
    except Exception as e:
        logger.warning(f"Error closing MCP client: {e}")
    _mcp_client = None
