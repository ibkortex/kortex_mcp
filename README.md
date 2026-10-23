# kortex-mcp

MCP server that exposes the Kortex data plane to MCP clients (Claude Desktop, Claude Code, Cursor, VS Code).
Wraps the two data plane endpoints so Claude can discover and search enterprise datasets without leaving the conversation.

## Prerequisites

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) (recommended) or pip
- A running Kortex backend data plane
- A Kortex personal API key (see below) whose owner has access to at least one collection

### Personal API keys

Personal keys are generated in **Kortex → Integraciones → Servidor MCP**. A personal key acts on behalf of the user who created it: the MCP server sees exactly the collections that user has been granted, and nothing else. The secret is shown only once — copy it straight into your client config, never commit that file, and revoke the key from the same page if it leaks.





## Claude Desktop setup

In Claude Desktop go to:
Customize > Developer > Edit Config
and edit the `claude_desktop_config.json` config file.

Choose **one** of the two options below, then restart Claude Desktop. The Kortex tools will appear in the tool picker (hammer icon).

### Option A — Directly from GitHub

Use this to always run the given tagged release without maintaining a local clone. `uvx` downloads, caches, and runs the package in one step.

```json
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
```

### Option B — Local clone for active development

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
        "KORTEX_API_URL": "http://localhost:8080",
        "KORTEX_API_KEY": "kx_live_<id>_<secret>"
      }
    }
  }
}
```

Replace `/absolute/path/to/kortex/src/kortex_mcp` with the actual path on your machine.

### Installing uv

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
winget install --id=astral-sh.uv -e
```

## Claude Code setup

```bash
claude mcp add kortex \
  --env KORTEX_API_URL=https://<kortex_data_plane_url> \
  --env KORTEX_API_KEY=kx_live_<id>_<secret> \
  -- uvx --from https://github.com/ibkortex/kortex_mcp/archive/refs/tags/v0.1.0.zip kortex-mcp
```

Add `--scope user` to make the server available in every project (the default scope is the current project only). Check it with `claude mcp list` or `/mcp` inside a session.

## Cursor setup

Create `.cursor/mcp.json` in your project (or `~/.cursor/mcp.json` for all projects):

```json
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
```

## VS Code setup

Create `.vscode/mcp.json` in your workspace (note the top-level key is `servers` and each entry needs `"type": "stdio"`):

```json
{
  "servers": {
    "kortex": {
      "type": "stdio",
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
```

If the workspace is shared or versioned, keep the key out of the file with an `inputs` entry (`"type": "promptString", "password": true`) and reference it as `"${input:<id>}"`.


## Tools

### `list_collections`

Lists all collections the API key has access to.

Returns each collection with:
- `id` — use this in `retrieve`
- `nombre` / `descripcion` — human-readable name and description
- `availableVersions` — logical version labels you can query (e.g. `["v1", "v2"]`)

Call this first to discover which collection IDs and version labels are available.

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


## Testing with MCP Inspector

[MCP Inspector](https://github.com/modelcontextprotocol/inspector) wraps the server process and opens a local web UI where you can call tools interactively — no Claude Desktop needed.

**Local clone:**

```bash
npx @modelcontextprotocol/inspector \
  -e KORTEX_API_KEY=kx_live_<token>  \
  -e KORTEX_API_URL=http://localhost:8080 \
  uvx --from ~/kortex/src/kortex_mcp kortex-mcp
```
**From GitHub:**

```bash
npx @modelcontextprotocol/inspector \
  -e KORTEX_API_KEY=kx_live_<token>  \
  -e KORTEX_API_URL=https://<kortex_data_plane_url> \
  uvx --from https://github.com/ibkortex/kortex_mcp/archive/refs/tags/v0.1.0.zip kortex-mcp
```

# SKILL

* enable skill in claude
- Configure env vars
