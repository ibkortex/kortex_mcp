"""Línea de órdenes del MCP de Kortex (`kortex-mcp`).

   kortex-mcp                              servir por stdio (lo que lanzan uvx y los clientes MCP; como hasta ahora)
   kortex-mcp serve [--http-local] [--port 8765]
                                           stdio, o HTTP solo en 127.0.0.1 con ficha local (para políticas que no admiten stdio)
   kortex-mcp login | logout | estado      sesión de conocimiento: usuario, contraseña y código TOTP; la contraseña no se guarda
   kortex-mcp registro [--port 8765]       la orden «claude mcp add» para el modo HTTP local (con su ficha)
   kortex-mcp registrar-escritorio         la misma entrada escrita en ~/.claude.json (Claude de escritorio sin la CLI «claude»)
   kortex-mcp probar [--port 8765]         habla con el servidor HTTP local como lo hará el cliente (sin secretos en la salida)
   --entorno <nombre>                      entorno de %USERPROFILE%\\.kortex\\config.json (dev, prod…); también KORTEX_ENTORNO

stdout es del protocolo MCP cuando se sirve por stdio: los avisos van a stderr."""
import argparse
import datetime as dt
import getpass
import json
import os
import sys

ORDENES = ["serve", "login", "logout", "estado", "registro", "registrar-escritorio", "probar"]


def _aviso(texto):
    print(f"[kortex-mcp] {texto}", file=sys.stderr)


def _pedir_codigo(u):
    return lambda: input(f"Código de 6 dígitos de tu aplicación de autenticación para {u}: ").strip()


# ---------------------------------------------------------------------- sesión
def _login() -> int:
    from .conocimiento import config, sesion
    from .conocimiento.sesion import ErrorKortex, Sesion
    try:
        cfg = config.cargar().exigir()
    except config.ConfigIncompleta as e:
        print(f"✗ {e}")
        return 2
    if sys.platform != "win32":
        print("Aviso: fuera de Windows no hay DPAPI y la sesión no se guarda en disco: el servidor MCP no podrá usarla.")
    print(f"Login de Kortex (entorno «{cfg.entorno}»): ten a mano tu aplicación de autenticación.")
    previo = sesion.usuario_de(sesion.leer_tokens())
    u = input(f"Usuario (correo){f' [{previo}]' if previo else ''}: ").strip() or (previo or "")
    if not u:
        print("Sin usuario: no se hace nada.")
        return 1
    clave = getpass.getpass(f"Contraseña de {u} (no se muestra): ")
    if not clave:
        print("Sin contraseña: no se hace nada.")
        return 1
    try:
        r = Sesion("ingesta", cfg=cfg).entrar(u, clave, _pedir_codigo(u))
    except ErrorKortex as e:
        print(f"✗ {e}")
        return 1
    finally:
        del clave
    admin = bool(set(r["grupos"]) & set(cfg.grupos_admin))
    print(f"✓ {r['usuario']} entra · sesión renovable hasta {dt.datetime.fromtimestamp(r['renovable_hasta']):%d/%m %H:%M}")
    print("Herramientas que verás: " + ("las de consulta y las de administración de la KB (grupo de administración de la KB)." if admin
                                       else "las de consulta."))
    print(f"Sesión cifrada con DPAPI en {config.carpeta()} (la contraseña no se guarda). Dura 30 días: después, repite el login.")
    print("Si el servidor MCP ya estaba arrancado, reinícialo para que aparezcan las herramientas.")
    return 0


def _logout() -> int:
    from .conocimiento import sesion
    print("Sesión cerrada y borrada de este equipo." if sesion.borrar_sesion() else "No había sesión guardada en este entorno.")
    return 0


def _estado() -> int:
    from .conocimiento import config, sesion
    try:
        cfg = config.cargar()
    except config.ConfigIncompleta as e:
        print(f"✗ {e}")
        return 2
    print(f"Entorno: {cfg.entorno} · configuración: {config.fichero_config() if config.fichero_config().exists() else 'solo variables de entorno'}")
    print(f"API: {cfg.api_url or '— (falta KORTEX_API_URL)'}")
    if cfg.api_url:
        print(f"  conocimiento: {cfg.knowledge_url} · KB: {cfg.kb_url}")
    print("Clave personal (list_collections, retrieve): " + ("definida" if os.environ.get("KORTEX_API_KEY") else "no definida (KORTEX_API_KEY)"))
    if cfg.faltan():
        print(f"Login: no configurado (falta {', '.join(cfg.faltan())})")
        return 0
    t = sesion.leer_tokens()
    if not t:
        print("Sesión: no hay (kortex-mcp login)")
        return 0
    perfil = sesion.perfil_actual()
    hasta = dt.datetime.fromtimestamp(sesion.renovable_hasta(t))
    print(f"Sesión: {sesion.usuario_de(t) or '—'} · " + (f"perfil {perfil} · renovable hasta {hasta:%d/%m %H:%M}" if perfil
                                                       else "caducada (repite kortex-mcp login)"))
    return 0


# ---------------------------------------------------------------------- servir
def _servir(http_local: bool, puerto) -> int:
    from .conocimiento import config, sesion
    from .server import _DEFAULT_API_URL, crear_servidor
    perfil = sesion.perfil_actual()
    try:
        conocimiento_configurado = not config.cargar().faltan()
    except config.ConfigIncompleta as e:
        _aviso(str(e))
        conocimiento_configurado = False
    if not os.environ.get("KORTEX_API_KEY"):
        if not conocimiento_configurado:
            _aviso("KORTEX_API_KEY is not set — exiting.")
            _aviso("Generate a personal key in Kortex → Integraciones → Servidor MCP and pass it in the \"env\" block of your MCP "
                   "client config, or configure the knowledge login (see the README) and run «kortex-mcp login».")
            return 1
        _aviso("KORTEX_API_KEY no está definida: list_collections y retrieve fallarán (las de conocimiento usan el login).")
    if not config.api_url_configurada():
        _aviso(f"KORTEX_API_URL is not set — defaulting to {_DEFAULT_API_URL}")
    if conocimiento_configurado and perfil is None:
        _aviso("Sin sesión de conocimiento: solo list_collections, retrieve y estado_sesion. Haz «kortex-mcp login» y reinicia.")
    srv = crear_servidor(perfil)
    if http_local:
        from .conocimiento.http_local import PUERTO, servir
        _aviso(f"Sirviendo en http://127.0.0.1:{puerto or PUERTO}/mcp (solo este equipo; ficha local obligatoria)")
        servir(srv, puerto)
    else:
        srv.run()
    return 0


# ---------------------------------------------------------------------- registro en el cliente (modo HTTP local)
def _url(puerto) -> str:
    from .conocimiento.http_local import PUERTO
    return f"http://localhost:{puerto or PUERTO}/mcp"


def _registro(puerto) -> int:
    from .conocimiento.http_local import ficha_local
    print(f'claude mcp add --transport http kortex {_url(puerto)} --scope user --header "Authorization: Bearer {ficha_local()}"')
    return 0


def _registrar_escritorio(puerto=None, fichero=None) -> int:
    """Claude de escritorio (pestaña Code) sin la CLI en el PATH: escribe la MISMA entrada que `claude mcp add --transport http kortex …
    --scope user` en ~/.claude.json (mcpServers.kortex), con copia previa. Solo toca esa clave."""
    import shutil
    from pathlib import Path

    from .conocimiento.http_local import ficha_local
    f = Path(fichero) if fichero else Path.home() / ".claude.json"
    datos = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    if f.exists():
        shutil.copy2(f, f.with_name(f.name + ".antes-kortex"))
    datos.setdefault("mcpServers", {})["kortex"] = {"type": "http", "url": _url(puerto),
                                                   "headers": {"Authorization": f"Bearer {ficha_local()}"}}
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(f)
    print(f"✓ MCP «kortex» registrado en {f} (copia previa: {f.name}.antes-kortex)")
    return 0


def _probar(puerto=None) -> int:
    """Habla con el servidor local por el protocolo MCP (HTTP + ficha local), como el cliente: lista las herramientas y llama a
    quien_soy (o a estado_sesion si no hay sesión). Sin secretos en la salida."""
    import requests

    from .conocimiento.http_local import PUERTO, ficha_local
    url = f"http://127.0.0.1:{puerto or PUERTO}/mcp"
    h = {"Authorization": f"Bearer {ficha_local()}", "Accept": "application/json, text/event-stream", "Content-Type": "application/json"}

    def rpc(cuerpo, sid=None):
        r = requests.post(url, headers={**h, **({"mcp-session-id": sid} if sid else {})}, json=cuerpo, timeout=120)
        r.encoding = "utf-8"
        r.raise_for_status()
        t = r.text
        if "text/event-stream" in r.headers.get("content-type", ""):
            t = ([x[5:].strip() for x in t.splitlines() if x.startswith("data:")] or [""])[-1]
        return (json.loads(t) if t else None), r.headers.get("mcp-session-id", sid)

    try:
        _, sid = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "kortex-probar", "version": "1"}}})
        rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
        lista, _ = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, sid)
        nombres = {t.get("name") for t in (lista or {}).get("result", {}).get("tools") or []}
        herramienta = "quien_soy" if "quien_soy" in nombres else "estado_sesion"
        yo, _ = rpc({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": herramienta, "arguments": {}}}, sid)
    except requests.RequestException as e:
        print(f"✗ el servidor no responde en {url} ({type(e).__name__}). Arráncalo con «kortex-mcp serve --http-local» o arrancar.ps1")
        return 2
    res = (yo or {}).get("result") or {}
    texto = "".join(c.get("text", "") for c in res.get("content") or [])
    print(f"✓ {url}: {len(nombres)} herramientas")
    print(("✗ " if res.get("isError") else "") + texto)
    return 1 if res.get("isError") else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="kortex-mcp", description="Servidor MCP de Kortex (plano de datos y conocimiento)")
    ap.add_argument("orden", nargs="?", default="serve", choices=ORDENES)
    ap.add_argument("--http-local", action="store_true", help="serve: HTTP solo en 127.0.0.1 con ficha local, en vez de stdio")
    ap.add_argument("--port", "--puerto", dest="puerto", type=int, default=None, help="puerto local del modo HTTP (8765)")
    ap.add_argument("--entorno", default=None, help="entorno de config.json (dev, prod…)")
    a = ap.parse_args(argv)
    if a.entorno:
        os.environ["KORTEX_ENTORNO"] = a.entorno                  # también lo heredan los procesos hijos
    if a.orden == "login":
        return _login()
    if a.orden == "logout":
        return _logout()
    if a.orden == "estado":
        return _estado()
    if a.orden == "registro":
        return _registro(a.puerto)
    if a.orden == "registrar-escritorio":
        return _registrar_escritorio(a.puerto)
    if a.orden == "probar":
        return _probar(a.puerto)
    return _servir(a.http_local, a.puerto)


if __name__ == "__main__":
    sys.exit(main())
