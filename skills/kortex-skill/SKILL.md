---
name: kortex
description: Search and discover enterprise knowledge collections via the Kortex data plane. Use whenever the user wants to list available datasets or perform semantic search over enterprise documents. Run scripts/kortex.py via code execution — credentials are read from environment variables, never ask the user for them.
---

## Prerequisites

The following environment variables must be set before running any script:

| Variable | Description |
|---|---|
| `KORTEX_API_KEY` | API key in `kx_live_<id>_<secret>` format |
| `KORTEX_API_URL` | Base URL of the Kortex backend (default: `http://localhost:8000`) |

The script uses only Python stdlib (`urllib`, `json`, `os`, `sys`) — no pip installs needed.

---

## Step 1 — List collections

Always call this first so you know which collection IDs and version labels are available.

```bash
python scripts/kortex.py list
```

Each collection in the response has:
- `id` — use this in retrieve calls
- `nombre` / `descripcion` — human-readable name and description
- `availableVersions` — version labels you can target (e.g. `["v1", "v2"]`)

Summarise collections for the user before proceeding to search.

---

## Step 2 — Retrieve (semantic search)

Pass the request payload as a JSON string:

```bash
# Search all collections (default version)
python scripts/kortex.py retrieve '{"query": "credit risk models", "numberOfResults": 10}'

# Search a specific collection
python scripts/kortex.py retrieve '{"query": "credit risk models", "collections": ["<collection_id>"]}'

# Search a specific collection at a specific version
python scripts/kortex.py retrieve '{"query": "credit risk models", "collections": ["<collection_id>:v1"]}'
```

Payload fields:

| Field | Required | Default | Description |
|---|---|---|---|
| `query` | yes | — | Natural-language question or search phrase |
| `collections` | no | all accessible | `["<id>"]` or `["<id>:<version_label>"]` |
| `numberOfResults` | no | 10 | Max passages to return |

Each result includes `collectionId`, `versionLabel`, `content`, `score`, and `sourceUri`.
Always cite `sourceUri` and `score` when presenting results to the user.

---

## Error handling

| Exit / status | Meaning | Action |
|---|---|---|
| `ERROR: KORTEX_API_KEY is not set` | Env var missing | Tell the user to set `KORTEX_API_KEY` |
| `ERROR 403` | Key lacks access to that collection | Do not retry; inform the user |
| `ERROR 404` | Collection not found | Re-run `list` and check the ID |
| `ERROR 5xx` | Backend error | Ask the user to verify the Kortex backend is running |

---

## Example flows

**"What collections do I have access to?"**
→ Run `list`, summarise `nombre` and `descripcion`.

**"Search for documents about credit risk."**
→ Run `list` if you don't know the IDs yet, then `retrieve` with the user's question.

**"Show me v1 results only."**
→ Run `retrieve` with `"collections": ["<id>:v1"]`.

**"Search across everything."**
→ Run `retrieve` without the `collections` field.
