"""Servir el MCP por HTTP SOLO en este equipo (127.0.0.1), para clientes que no admiten (o a los que la política corporativa no deja
usar) servidores locales por stdio: `kortex-mcp serve --http-local [--port 8765]`.

Por qué: hay políticas de Claude Code (allowedMcpServers) que no dejan registrar servidores MCP locales por stdio con un nombre propio,
pero sí los que se sirven en «http://localhost*». Esto no esquiva nada: es la vía que esa política permite.

Protección (en este orden; cualquier fallo corta la petición sin llegar al MCP):
- escucha solo en 127.0.0.1, nunca en la red;
- cabeceras Host y Origin: solo 127.0.0.1/localhost en el puerto propio (contra DNS rebinding desde una web); además se pasa la
  misma regla al SDK (transport_security), por si una versión futura cambia sus valores por defecto;
- ficha local (Authorization: Bearer …), generada al primer arranque en %USERPROFILE%\\.kortex\\ficha_local.txt, que se pasa al
  cliente al registrarlo (`kortex-mcp registro`). Sin ella, 401. La ficha solo protege el acceso desde otros programas del propio
  equipo; los tokens de Kortex siguen cifrados con DPAPI como en stdio.
"""
from __future__ import annotations

import hmac
import os
import secrets

from . import config

PUERTO = 8765


def ficha_local() -> str:
    f = config.base() / "ficha_local.txt"
    if not f.exists():
        f.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        try:
            os.chmod(f, 0o600)
        except OSError:
            pass
    return f.read_text(encoding="utf-8").strip()


def anfitriones(puerto: int) -> tuple[set, set]:
    hosts = {f"127.0.0.1:{puerto}", f"localhost:{puerto}", f"[::1]:{puerto}"}
    return hosts, {f"http://{h}" for h in hosts}


def _responder(status: int, texto: str):
    async def enviar(send):
        await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
        await send({"type": "http.response.body", "body": texto.encode()})
    return enviar


class _ExigeFicha:
    """Middleware ASGI: 403 si Host u Origin no son locales del puerto; 401 si falta «Authorization: Bearer <ficha local>»."""

    def __init__(self, app, ficha: str, puerto: int = PUERTO):
        self.app, self.ficha = app, ficha.encode()
        self.hosts, self.origenes = anfitriones(puerto)

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "websocket":                      # el transporte MCP es HTTP: nada de websockets
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope.get("type") == "http":
            cab = dict(scope.get("headers") or [])
            host = cab.get(b"host", b"").decode("latin-1").lower()
            origen = cab.get(b"origin", b"").decode("latin-1").lower()
            if host not in self.hosts or (origen and origen not in self.origenes):
                await _responder(403, "Petición no local rechazada por el MCP de Kortex")(send)
                return
            if not hmac.compare_digest(cab.get(b"authorization", b""), b"Bearer " + self.ficha):
                await _responder(401, "Falta la ficha local del MCP de Kortex")(send)
                return
        await self.app(scope, receive, send)


def app_local(srv, puerto: int = PUERTO):
    """La app ASGI del servidor MCP `srv` protegida para 127.0.0.1:<puerto>."""
    from mcp.server.transport_security import TransportSecuritySettings
    hosts, origenes = anfitriones(puerto)
    seguridad = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=sorted(hosts), allowed_origins=sorted(origenes))
    app = srv.streamable_http_app(host="127.0.0.1", transport_security=seguridad)
    return _ExigeFicha(app, ficha_local(), puerto)


def servir(srv, puerto: int | None = None) -> None:
    import uvicorn
    puerto = puerto or PUERTO
    uvicorn.run(app_local(srv, puerto), host="127.0.0.1", port=puerto, log_level="warning")
