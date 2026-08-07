"""
Kortex data plane MCP server for Claude Desktop.

Exposes two tools backed by the Kortex backend data plane API:

  list_collections  — discover all collections accessible to the configured API key,
                      including their description and available version labels
  retrieve          — semantic search across accessible collections via Bedrock

Configuration (environment variables):
  KORTEX_API_URL   Base URL of the Kortex backend  (default: http://localhost:8000)
  KORTEX_API_KEY   API key in kx_live_... format    (required)

Claude Desktop config  (~/.config/Claude/claude_desktop_config.json):
  {
    "mcpServers": {
      "kortex": {
        "command": "uv",
        "args": ["run", "--project", "/abs/path/to/kortex_mcp", "python", "-m", "mcps.kortex_mcp.server"],
        "env": {
          "KORTEX_API_URL": "http://localhost:8000",
          "KORTEX_API_KEY": "kx_live_<id>_<secret>"
        }
      }
    }
  }
"""

import os
import sys
from typing import Optional

import httpx
from mcp.server.mcpserver import MCPServer

# ── configuration ─────────────────────────────────────────────────────────────

_BASE_URL = os.environ.get("KORTEX_API_URL", "http://localhost:8000").rstrip("/")
_API_KEY = os.environ.get("KORTEX_API_KEY", "")

if not _API_KEY:
    print("[kortex-mcp] KORTEX_API_KEY is not set — exiting", file=sys.stderr)
    sys.exit(1)

# ── MCP server ────────────────────────────────────────────────────────────────

mcp = MCPServer(
    "Kortex",
    instructions=(
        "You have access to the Kortex enterprise data plane. "
        "Call list_collections first to discover what collections are available and which "
        "version labels you can query. Use retrieve to perform semantic search — it queries "
        "Amazon Bedrock Knowledge Bases and returns the most relevant passages from the "
        "collections in scope."
    ),
)

# ── HTTP helpers ──────────────────────────────────────────────────────────────

_TIMEOUT = 30.0


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=_BASE_URL,
        headers={"x-api-key": _API_KEY},
        timeout=_TIMEOUT,
    )


def _check(resp: httpx.Response) -> None:
    if resp.is_error:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise RuntimeError(f"Kortex API {resp.status_code}: {detail}")


# ── tools ─────────────────────────────────────────────────────────────────────


@mcp.tool()
def list_collections() -> dict:
    """
    List all collections accessible to this API key.

    Returns a list of collections, each containing:
    - id: unique collection identifier (use this in retrieve)
    - nombre / descripcion: human-readable name and description — read these to
      understand what a collection contains before deciding whether to query it
    - availableVersions: logical version labels you can query (e.g. ["v1", "v2"])

    Call this before retrieve to know which collection IDs and version labels are available.
    """
    with _client() as c:
        resp = c.get("/dataplane/collections")
        _check(resp)
        return resp.json()


@mcp.tool()
def retrieve(
    query: str,
    collections: Optional[list[str]] = None,
    number_of_results: int = 10,
) -> dict:
    """
    Semantic search across accessible collections using Amazon Bedrock Knowledge Bases.

    Args:
        query: Natural-language question or search phrase.
        collections: Which collections (and optionally which version) to search.
            Each entry is either:
              - "collection_id"           → search that collection at its default version
              - "collection_id:label"     → search that collection at the given version label
            Omit (or pass null) to search across all collections accessible to the API key,
            each at its default version. Use list_collections to discover IDs and labels.
        number_of_results: Maximum number of passages to return (default 10).

    Returns a list of results, each with:
    - collectionId / versionLabel: which collection and version the passage came from
    - content: the retrieved text passage
    - score: relevance score (higher is more relevant)
    - sourceUri: original document URI when available
    """
    payload: dict = {"query": query, "numberOfResults": number_of_results}
    if collections is not None:
        payload["collections"] = collections

    with _client() as c:
        resp = c.post("/dataplane/retrieve", json=payload)
        _check(resp)
        return resp.json()


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
