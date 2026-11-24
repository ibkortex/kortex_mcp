"""Servido por HTTP solo en 127.0.0.1 con ficha local (la política corporativa admite http://localhost*): sin ficha, 401."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kortex_mcp import http_local as H  # noqa: E402


def _llamar(app, cabeceras):
    enviados = []

    async def recibir():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def enviar(m):
        enviados.append(m)

    async def ok(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})
    asyncio.run(H._ExigeFicha(ok, "secreta")({"type": "http", "headers": cabeceras}, recibir, enviar))
    return enviados[0]["status"]


def test_without_or_with_wrong_token_is_401_and_with_token_passes():
    assert _llamar(None, []) == 401
    assert _llamar(None, [(b"authorization", b"Bearer otra")]) == 401
    assert _llamar(None, [(b"authorization", b"Bearer secreta")]) == 200


def test_local_token_is_created_once_outside_the_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("KORTEX_HOME", str(tmp_path))
    a, b = H.ficha_local("admin"), H.ficha_local("admin")
    assert a == b and len(a) >= 32 and (tmp_path / "ficha_local_admin.txt").exists()
    assert H.ficha_local("consulta") != a
