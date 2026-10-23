"""
Kortex data plane CLI — called by Claude via code execution.

Commands:
  list                          list all accessible collections
  retrieve '<json payload>'     semantic search

Required env vars:
  KORTEX_API_KEY   kx_live_<id>_<secret>
  KORTEX_API_URL   base URL of the Kortex backend (default: http://localhost:8000)
"""

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("KORTEX_API_URL", "http://localhost:8000").rstrip("/")
KEY = os.environ.get("KORTEX_API_KEY", "")

if not KEY:
    print("ERROR: KORTEX_API_KEY is not set", file=sys.stderr)
    sys.exit(1)

HEADERS = {"x-api-key": KEY, "Content-Type": "application/json"}


def _request(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except Exception:
            pass
        print(f"ERROR {e.code}: {detail}", file=sys.stderr)
        sys.exit(1)


cmd = sys.argv[1] if len(sys.argv) > 1 else "list"

if cmd == "list":
    result = _request("GET", "/dataplane/collections")
    print(json.dumps(result, indent=2, ensure_ascii=False))

elif cmd == "retrieve":
    if len(sys.argv) < 3:
        print("Usage: kortex.py retrieve '<json>'", file=sys.stderr)
        sys.exit(1)
    payload = json.loads(sys.argv[2])
    result = _request("POST", "/dataplane/retrieve", payload)
    print(json.dumps(result, indent=2, ensure_ascii=False))

else:
    print(f"Unknown command: {cmd}. Use 'list' or 'retrieve'.", file=sys.stderr)
    sys.exit(1)
