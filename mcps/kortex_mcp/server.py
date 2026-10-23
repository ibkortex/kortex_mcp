"""
Kortex data plane MCP server for Claude Desktop.

Exposes two tools backed by the Kortex backend data plane API:

  list_collections  — discover all collections accessible to the configured API key,
                      including their description and available version labels
  retrieve          — semantic search across accessible collections via Bedrock

Configuration (environment variables):
  KORTEX_API_URL   Base URL of the Kortex backend  (default: http://localhost:8080)
  KORTEX_API_KEY   API key in kx_live_... format    (required)

Personal keys are generated in Kortex → Integraciones → Servidor MCP and act on
behalf of the user who created them.

Claude Desktop config  (claude_desktop_config.json):
  {
    "mcpServers": {
      "kortex": {
        "command": "uvx",
        "args": [
          "--from", "https://github.com/ibkortex/kortex_mcp/archive/refs/tags/v0.1.0.zip",
          "kortex-mcp"
        ],
        "env": {
          "KORTEX_API_URL": "https://<kortex_data_plane_url>",
          "KORTEX_API_KEY": "kx_live_<id>_<secret>"
        }
      }
    }
  }
"""

import os
import sys
from importlib.metadata import PackageNotFoundError, version
from typing import Optional

import httpx
from mcp.server.mcpserver import MCPServer

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
_DEFAULT_API_URL = "http://localhost:8080"

try:
    __version__ = version("kortex-mcp")
except PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "dev"

_USER_AGENT = f"kortex-mcp/{__version__}"


def _client() -> httpx.Client:
    # Read lazily on every call so the tools always use the current environment.
    base_url = (os.environ.get("KORTEX_API_URL") or _DEFAULT_API_URL).rstrip("/")
    api_key = os.environ.get("KORTEX_API_KEY", "")
    if not api_key:
        raise RuntimeError("KORTEX_API_KEY is not set")
    return httpx.Client(
        base_url=base_url,
        headers={"x-api-key": api_key, "User-Agent": _USER_AGENT},
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


def main() -> None:
    """Console-script entry point: validate the configuration, then serve over stdio."""
    # stdout carries the MCP protocol on stdio — diagnostics must go to stderr.
    if not os.environ.get("KORTEX_API_KEY"):
        print(
            "[kortex-mcp] KORTEX_API_KEY is not set — exiting.\n"
            "[kortex-mcp] Generate a personal key in Kortex → Integraciones → Servidor MCP "
            "and pass it in the \"env\" block of your MCP client config.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not os.environ.get("KORTEX_API_URL"):
        print(
            f"[kortex-mcp] KORTEX_API_URL is not set — defaulting to {_DEFAULT_API_URL}",
            file=sys.stderr,
        )
    mcp.run()


if __name__ == "__main__":
    main()
