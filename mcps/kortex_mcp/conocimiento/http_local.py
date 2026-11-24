"""Servir el MCP por HTTP SOLO en este equipo (127.0.0.1), para Claude Code.

Por qué: la política corporativa de Claude Code (allowedMcpServers) no deja registrar servidores MCP locales por stdio con un nombre
propio, pero sí admite expresamente los que se sirven en «http://localhost*». Esto no esquiva nada: es la vía que la política permite.

Protección: escucha solo en 127.0.0.1 (nunca en la red) y exige una ficha local (Authorization: Bearer …) que se genera al primer
arranque en %USERPROFILE%\\.kortex\\ficha_local_<perfil>.txt y que se pasa a Claude Code al registrarlo (claude mcp add … --header).
Sin la ficha, 401. La ficha solo protege el acceso desde otros programas del propio equipo; las credenciales de Kortex siguen cifradas
con DPAPI como en stdio.
"""
from __future__ import annotations

import hmac
import secrets

from . import config

PUERTOS = {"admin": 8765, "consulta": 8766, "kortex": 8765}   # «kortex»: el MCP único (23/11/2026)


def ficha_local(perfil: str) -> str:
    f = config.carpeta() / f"ficha_local_{perfil}.txt"
    if not f.exists():
        f.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    return f.read_text(encoding="utf-8").strip()


class _ExigeFicha:
    """Middleware ASGI: 401 si la petición HTTP no trae «Authorization: Bearer <ficha local>»."""

    def __init__(self, app, ficha: str):
        self.app, self.ficha = app, ficha.encode()

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            cab = dict(scope.get("headers") or [])
            dada = cab.get(b"authorization", b"")
            if not hmac.compare_digest(dada, b"Bearer " + self.ficha):
                await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
                await send({"type": "http.response.body", "body": "Falta la ficha local del MCP de Kortex".encode()})
                return
        await self.app(scope, receive, send)


def servir(perfil: str | None = None, puerto: int | None = None) -> None:
    """Sin perfil: el MCP único «kortex» (puerto 8765, ficha local «kortex»); sus herramientas las decide el login (perfil_efectivo)."""
    import uvicorn

    from . import credenciales
    from .servidor import crear
    clave = perfil or "kortex"
    puerto = puerto or PUERTOS[clave]
    credenciales.olvidar_claves()                                    # 23/11/2026: con MFA ya no se guardan contraseñas
    app = crear(perfil or credenciales.perfil_efectivo()).streamable_http_app(host="127.0.0.1")
    uvicorn.run(_ExigeFicha(app, ficha_local(clave)), host="127.0.0.1", port=puerto, log_level="warning")
