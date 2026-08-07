# kortex-mcp

MCP server that exposes the Kortex data plane to Claude Desktop.
Wraps the two data plane endpoints so Claude can discover and search enterprise datasets without leaving the conversation.

## Prerequisites

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) (recommended) or pip
- A running Kortex backend (`kortex/src/back`)
- An active Kortex API key with at least one collection in scope

## Installation

```bash
cd kortex/src/kortex_mcp
uv sync          # creates .venv and installs mcp + httpx
```

Or with pip:

```bash
pip install -e .
```

## Configuration

The server reads two environment variables:

| Variable | Required | Default | Description |
|---|---|---|---|
| `KORTEX_API_KEY` | yes | — | API key in `kx_live_<id>_<secret>` format |
| `KORTEX_API_URL` | no | `http://localhost:8000` | Base URL of the Kortex backend |

## Claude Desktop setup

Edit `~/.config/Claude/claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`).

Choose **one** of the two options below, then restart Claude Desktop. The Kortex tools will appear in the tool picker (hammer icon).

### Option A — Local clone

Use this if you have cloned the repo and want to run your working copy.

```json
{
  "mcpServers": {
    "kortex": {
      "command": "uv",
      "args": [
        "run",
        "--project", "/absolute/path/to/kortex/src/kortex_mcp",
        "python", "-m", "mcps.kortex_mcp.server"
      ],
      "env": {
        "KORTEX_API_URL": "http://localhost:8000",
        "KORTEX_API_KEY": "kx_live_<id>_<secret>"
      }
    }
  }
}
```

Replace `/absolute/path/to/kortex/src/kortex_mcp` with the actual path on your machine.

### Option B — Directly from GitHub (no clone needed)

Use this to always run the `latest` tagged release without maintaining a local clone. `uvx` downloads, caches, and runs the package in one step.

```json
{
  "mcpServers": {
    "kortex": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/ibkortex/kortex_mcp@v0.0.1",
        "kortex-mcp"
      ],
      "env": {
        "KORTEX_API_URL": "http://localhost:8000",
        "KORTEX_API_KEY": "kx_live_<id>_<secret>"
      }
    }
  }
}
```

## Tools

### `list_collections`

Lists all collections the API key has access to.

Returns each collection with:
- `id` — use this in `retrieve`
- `nombre` / `descripcion` — human-readable name and description
- `availableVersions` — logical version labels you can query (e.g. `["v1", "v2"]`)

Call this first to understand what data is available before issuing a search.

---

### `retrieve(query, ...)`

Semantic search against Amazon Bedrock Knowledge Bases.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `query` | string | — | Natural-language question or search phrase |
| `collections` | `string[]` | all accessible | Collections to search. Each entry is `"collection_id"` or `"collection_id:version_label"`. Omit to search all accessible collections at their default version. |
| `number_of_results` | integer | `10` | Maximum passages to return |

Each result includes `collectionId`, `versionLabel`, `content`, `score`, and `sourceUri`.

Requesting a collection outside the API key's scope returns a 403 — Claude cannot query collections it has not been granted access to.

## Example conversation

> **User:** What collections do I have access to?

Claude calls `list_collections` and summarises the response.

> **User:** Search for documents about credit risk models in the regulatory collection.

Claude calls `retrieve` with the appropriate `collection_id` and surfaces the most relevant passages.

> **User:** Show me the v1 version only.

Claude calls `retrieve` again with `collections: ["<id>:v1"]`.

## Testing with MCP Inspector

[MCP Inspector](https://github.com/modelcontextprotocol/inspector) wraps the server process and opens a local web UI where you can call tools interactively — no Claude Desktop needed.

**Local clone:**

```bash
KORTEX_API_KEY=kx_live_... KORTEX_API_URL=http://localhost:8000 \
  npx @modelcontextprotocol/inspector \
  uv run --project /absolute/path/to/kortex/src/kortex_mcp \
  python -m mcps.kortex_mcp.server
```

**From GitHub:**

```bash
KORTEX_API_KEY=kx_live_... KORTEX_API_URL=http://localhost:8000 \
  npx @modelcontextprotocol/inspector \
  uvx --from git+https://github.com/ibkortex/kortex_mcp@v0.0.1 kortex-mcp
```

Open `http://localhost:5173` in your browser. Use the **Tools** tab to call `list_collections` and `retrieve` and inspect the raw responses.
