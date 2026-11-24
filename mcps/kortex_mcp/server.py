"""
Kortex MCP server (data plane + knowledge).

Always exposes the two data plane tools, backed by the Kortex backend data plane API:

  list_collections  — discover all collections accessible to the configured API key,
                      including their description and available version labels
  retrieve          — semantic search across accessible collections via Bedrock

and, depending on the knowledge login (`kortex-mcp login`: Cognito SRP + TOTP, client
mcp-local, tokens encrypted with DPAPI), the knowledge tools of mcps/kortex_mcp/conocimiento:

  no session        — estado_sesion (explains how to log in)
  any user          — 6 query tools over the user's ingested documentation (+ KB context)
  group kb-admin    — those 7 plus the KB administration tools

Configuration (environment variables, or %USERPROFILE%\\.kortex\\config.json):
  KORTEX_API_URL            Base URL of the Kortex backend  (default: http://localhost:8080)
  KORTEX_API_KEY            API key in kx_live_... format    (list_collections, retrieve)
  KORTEX_COGNITO_REGION     knowledge login: region of the official Cognito pool
  KORTEX_COGNITO_POOL_ID    knowledge login: official user pool id
  KORTEX_COGNITO_CLIENT_ID  knowledge login: public app client mcp-local (no secret)

Personal keys are generated in Kortex → Integraciones → Servidor MCP and act on
behalf of the user who created them.

Transports: stdio (default) or `kortex-mcp serve --http-local [--port 8765]` (127.0.0.1 only,
local Bearer token). See cli.py and README.md.

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

from .conocimiento import config as _config_conocimiento

# ── MCP server ────────────────────────────────────────────────────────────────

INSTRUCTIONS = (
    "You have access to the Kortex enterprise data plane. "
    "Call list_collections first to discover what collections are available and which "
    "version labels you can query. Use retrieve to perform semantic search — it queries "
    "Amazon Bedrock Knowledge Bases and returns the most relevant passages from the "
    "collections in scope."
)

# Data plane only (the two tools below), kept for compatibility. The console script serves
# crear_servidor(), which adds the knowledge tools when there is a login session.
mcp = MCPServer("Kortex", instructions=INSTRUCTIONS)

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
    base_url = (os.environ.get("KORTEX_API_URL") or _config_conocimiento.api_url_configurada() or _DEFAULT_API_URL).rstrip("/")
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


# ── server with the knowledge tools ───────────────────────────────────────────

_AUTO = object()


def crear_servidor(perfil=_AUTO, fabrica=None) -> MCPServer:
    """
    The served MCP: list_collections and retrieve always; then, by knowledge session profile
    (read from the stored token, no network): None → estado_sesion; "consulta" → query tools;
    "admin" (Cognito group kb-admin) → query + KB administration tools.
    """
    from .conocimiento import servidor as conocimiento
    from .conocimiento.sesion import perfil_actual

    if perfil is _AUTO:
        perfil = perfil_actual()
    instrucciones = INSTRUCTIONS
    if perfil is None:
        instrucciones += (" Kortex knowledge tools (the user's ingested documentation and the KB) need a login: if the user asks "
                          "for them, call estado_sesion.")
    else:
        instrucciones += " " + conocimiento.INSTRUCCIONES[perfil]
    srv = MCPServer("Kortex", instructions=instrucciones)
    srv.tool()(list_collections)
    srv.tool()(retrieve)
    if perfil is None:
        conocimiento.registrar_sin_sesion(srv)
    else:
        conocimiento.registrar(srv, perfil, fabrica)
    return srv


# ── entry point ───────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> None:
    """Console-script entry point (`kortex-mcp`). Without arguments, serve over stdio as before."""
    # stdout carries the MCP protocol on stdio — diagnostics go to stderr (see cli.py).
    from .cli import main as cli_main

    sys.exit(cli_main(argv))


if __name__ == "__main__":
    main()
