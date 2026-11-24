# kortex-mcp

MCP server that exposes Kortex to MCP clients (Claude Desktop, Claude Code, Cursor, VS Code):

- **Data plane** (`list_collections`, `retrieve`): discover and search enterprise datasets with a personal API key.
- **Knowledge** (optional, after `kortex-mcp login`): query the documentation the user can read in the Kortex ingestion web
  (fragments with their document, plus the KB context) and, for members of the Cognito group `kb-admin`, administer the knowledge
  base (auditable decisions, consolidation, sources, review sheets). See [Knowledge tools](#knowledge-tools).

It is one server (`kortex`): the tools it registers depend on the API key and on the login session.

## Prerequisites

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) (recommended) or pip
- A running Kortex backend data plane
- A Kortex personal API key (see below) whose owner has access to at least one collection
- For the knowledge tools: a Kortex user (with MFA set up) and the environment configuration given by the Kortex team
  (see [Configuration](#configuration)). The login session is stored with Windows DPAPI, so these tools need Windows.

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


## Knowledge tools

The server adds the knowledge tools of `mcps/kortex_mcp/conocimiento` according to the login session stored on this machine
(read at start-up, without network):

| Session | Tools registered |
|---|---|
| none (or expired, or not configured) | `list_collections`, `retrieve` and `estado_sesion` (tells the user how to log in) |
| any user | the two above + 7 query tools |
| user in the Cognito group `kb-admin` | the two above + 7 query tools + 46 KB administration tools |

The profile only decides which tools are shown. Every call is authorized by the Kortex API with the user's own token (grants,
groups): an administration tool used without the right permissions gets a 403.

**Query tools (any logged-in user)** — `${KORTEX_API_URL}/knowledge/v1`

| Tool | What it does |
|---|---|
| `quien_soy` | Profile, user, environment, teams and roles |
| `equipos_y_carpetas` | Teams the user sees and their folder tree |
| `documentos` | Documents of a team/folder (search, state, pagination) |
| `consultar` | Retrieval without model cost: numbered fragments `[n]` with `doc_id` from the user's documentation, plus what the KB knows (cross-team knowledge, paraphrased, never quoted as a team document) |
| `leer_documento` | Document text by segments (paginated) |
| `descargar_original` | Downloads the original file (current approved version or a given one) |
| `preguntar_chat_web` | The ingestion web chat in agent mode (spends model tokens; for comparison only) |

Prompt: `contrastar_con_mi_contexto`.

**KB administration tools (group `kb-admin`)** — `${KORTEX_API_URL}/kb/v1`

- Read: `estado_kb`, `buscar_entidades`, `entidad`, `relaciones`, `por_que`, `documento_en_kb`, `ambito`, `contexto`, `metricas`,
  `lo_nuevo_desde`, `marcar_revision`, `ficha_html`, `historial`, `catalogo_kb`, `buscar_hpum`.
- Decisions (auditable, author = the logged-in user, undoable): `validar`, `rechazar`, `corregir_tipo`, `corregir_nombre`,
  `fusionar`, `mantener_separadas`, `decidir_en_bloque`, `deshacer`, `exportar_decisiones`, `operar_kb`.
- Review sheets (HTML generated locally, answered by a reviewer, imported and applied): `generar_fichas_revision`,
  `importar_respuestas_ficha`, `previsualizar_correcciones_ficha`, `aplicar_correcciones_ficha`, `fichas_revision`.
- Consolidation: `consolidaciones`, `abrir_consolidacion`, `consolidacion`, `cerrar_consolidacion`, `propuestas`,
  `explicar_propuesta`, `analizar_consolidacion`, `aplicar_propuestas`, `descartar_propuestas`.
- Sources: `fuentes`, `ingesta_pendiente`, `actualizar_desde_ingesta`, `quitar_o_incorporar_documentos`, `estado_reanalisis`,
  `reanalizar`, `asistente_web`.

Prompts: `revision_de_carga`, `informe_de_siempre`, `contrastar_kb`.

Bulk, destructive or paid operations go in **two steps**: the first call previews and returns a one-time code (valid 15 minutes,
kept in the server process); the server instructions tell the model not to confirm without the person's explicit yes.

### Login

```bash
kortex-mcp login      # user (email), password and the 6-digit code of the authenticator app
kortex-mcp estado     # environment, API, session user, profile and until when it can be renewed (no secrets)
kortex-mcp logout     # revokes the refresh token in Cognito and deletes the local session
```

The login is Cognito **SRP + TOTP** against the official Kortex user pool with the public app client `mcp-local` (no client
secret, no browser). It must be run by the person in their own terminal: the password and the code never go through the MCP
client or the chat. The password is never stored; only the Cognito tokens are, encrypted with DPAPI (bound to the Windows user)
in `%USERPROFILE%\.kortex\<environment>\sesion.dpapi`. The session lasts 30 days (refresh token of `mcp-local`); after that the
tools say so and the person logs in again. First time: log in once in the Kortex web to change the temporary password and
register the authenticator app (QR code).

After a login, restart the MCP server (or open a new client session) so that the new tools are registered. A running server
picks up a renewed session by itself.

### Configuration

No environment identifiers are hard-coded. Each value comes from its environment variable or, if unset, from
`%USERPROFILE%\.kortex\config.json` (handed out by the Kortex team; another path with `KORTEX_CONFIG`):

| Variable | `config.json` key | Use |
|---|---|---|
| `KORTEX_API_URL` | `api_url` | Base URL of the Kortex API (also used by `list_collections` and `retrieve`) |
| `KORTEX_COGNITO_REGION` | `cognito_region` | Region of the user pool (defaults to the prefix of the pool id) |
| `KORTEX_COGNITO_POOL_ID` | `cognito_pool_id` | Official user pool |
| `KORTEX_COGNITO_CLIENT_ID` | `cognito_client_id` | Public app client `mcp-local` |
| `KORTEX_KNOWLEDGE_PREFIX` | `knowledge_prefix` | Knowledge routes prefix (default `/knowledge/v1`) |
| `KORTEX_KB_PREFIX` | `kb_prefix` | KB routes prefix (default `/kb/v1`) |
| `KORTEX_KB_CAMPANA` | `kb_campana` | KB campaign (default `KORTEX`) |
| `KORTEX_GRUPO_ADMIN` | `grupo_admin` | Cognito group(s) that get the administration tools, comma-separated (default `kb-admin`) |
| `KORTEX_ENTORNO` | `entorno` | Named environment to use (also `kortex-mcp --entorno <name>`) |
| `KORTEX_HOME` | — | Local data folder (default `%USERPROFILE%\.kortex`) |
| `KORTEX_DESCARGAS` | — | Where downloads and generated HTML go (default `Downloads\kortex`) |

`config.json` can be flat or hold named environments:

```json
{
  "entorno": "prod",
  "entornos": {
    "dev":  { "api_url": "https://<kortex-dev-api>",  "cognito_pool_id": "<region>_<id>", "cognito_client_id": "<mcp-local client id>" },
    "prod": { "api_url": "https://<kortex-prod-api>", "cognito_pool_id": "<region>_<id>", "cognito_client_id": "<mcp-local client id>" }
  }
}
```

Each environment keeps its own session and cache (`%USERPROFILE%\.kortex\<environment>\`). Pool and client ids are not
secrets, but they are environment-specific: keep them in `config.json` or in the client config, not in this repository.

### Transports

- **stdio** (default, unchanged): `kortex-mcp` or `kortex-mcp serve`. This is what `uvx` and the client configs above run.
- **Local HTTP**: `kortex-mcp serve --http-local [--port 8765]`, for machines whose Claude Code policy only allows MCP servers
  served on `http://localhost`. It listens on 127.0.0.1 only and requires a local bearer token:

  ```bash
  kortex-mcp serve --http-local          # keep it running (or use distribucion/arrancar.ps1 on Windows)
  kortex-mcp registro                    # prints the «claude mcp add --transport http kortex … --header "Authorization: Bearer …"» command
  kortex-mcp probar                      # talks MCP to the local server like the client will
  ```

  `distribucion/instalar.ps1` and `distribucion/INSTALAR_CON_CLAUDE_CODE.md` automate this on Windows (virtual environment,
  `config.json`, start-up task, registration in Claude Code).

### Security

- Data plane: the personal API key acts on behalf of its owner, exactly as before.
- Knowledge: the user's own Cognito access token (`Authorization: Bearer`) against the official API; the API authorizes every call.
  The tool profile is a convenience, not a control.
- No passwords on disk. Tokens encrypted with DPAPI; never printed or returned to the client. Logout revokes the refresh token.
- Local HTTP mode: bound to 127.0.0.1; requests whose `Host` or `Origin` is not local to the port are rejected (403, DNS
  rebinding), and the same rule is passed to the MCP SDK; requests without the local bearer token get 401. The token lives in
  `%USERPROFILE%\.kortex\ficha_local.txt` and in the client config; it only protects against other programs on the same machine.
- Errors reach the model as short Spanish messages; unexpected exceptions are hidden from the client (trace on stderr).
- The KB administration tools cache the served KB and keep local review files under `%USERPROFILE%\.kortex\<environment>\`
  (plain JSON, like the KB web shows to its administrators): treat that folder as confidential.


## Development

```bash
uv sync
uv run pytest            # no network: fake HTTP, fake Cognito and fake DPAPI (real DPAPI round-trip only on Windows)
```

`tests/conocimiento/test_ficha.py` compares the generated HTML with the KB web's `ficha.js` when `node` is available, and
`tests/conocimiento/test_fichas_html_e2e.py` runs the review sheets in Chromium when Playwright is installed; both skip otherwise.
The origin of the knowledge code is documented in `mcps/kortex_mcp/conocimiento/ORIGEN.md`.

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

## Skill

`skills/kortex-skill` is a Claude skill that calls the data plane directly (`list` / `retrieve`) with the same
`KORTEX_API_URL` and `KORTEX_API_KEY`. Enable it in Claude and set those environment variables.
