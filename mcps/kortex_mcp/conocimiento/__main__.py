"""MCP local de Kortex. Desde el 23/11/2026 es UN SOLO MCP («kortex», 127.0.0.1:8765): con el login de la ingesta da las
herramientas de consulta; si además hay login de la KB (equipo Kortex), todas.
   python -m kortex_mcp login                     login único: usuario, contraseña y código TOTP de la ingesta; la KB solo al equipo Kortex
   python -m kortex_mcp servir                    el MCP único por HTTP local (lo lanza mcp\\arrancar.ps1)
   python -m kortex_mcp registro | probar         la orden «claude mcp add» / prueba como lo verá Claude Code
   python -m kortex_mcp estado                    qué hay guardado y hasta cuándo vale la sesión (sin secretos)
   --perfil consulta|admin                        modo antiguo (un servidor por perfil); login/logout de un perfil concreto
MFA obligatorio (23/11/2026): la contraseña no se guarda; la sesión dura 30 días desde el login y después hay que repetirlo."""
import argparse
import datetime as dt
import getpass
import sys

from . import config, credenciales
from .sesion import REFRESCO_S, ErrorKortex, Sesion, caducidad


def _pedir_codigo(u):
    return lambda: input(f"Código de 6 dígitos de tu aplicación de autenticación para {u}: ").strip()


def _login(perfil, solo_kb=False):
    if sys.platform != "win32":
        print("Aviso: fuera de Windows no hay DPAPI y la sesión no se guarda en disco: el servidor MCP no podrá usarla.")
    cuentas = [("ingesta", "Usuario de la web de ingesta (correo)", None)] if perfil == "consulta" else \
        [("kb", "Usuario de la web de la KB (correo; Intro para omitir)", "")] if solo_kb else \
        [("kb", "Usuario de la web de la KB (correo)", None), ("ingesta", "Usuario de la ingesta (opcional, Intro para omitir)", "")]
    hechas = 0
    for cuenta, texto, defecto in cuentas:
        previo = credenciales.usuario(perfil, cuenta)
        sugerido = previo or defecto
        u = input(f"{texto}{f' [{sugerido}]' if sugerido else ''}: ").strip() or (sugerido or "")
        if not u:
            print(f"  · {cuenta}: omitido")
            continue
        clave = getpass.getpass(f"Contraseña de {u} (no se muestra): ")
        if not clave:
            print(f"  · {cuenta}: sin contraseña, omitido")
            continue
        try:
            r = Sesion(perfil, cuenta).entrar(u, clave, _pedir_codigo(u))
        except ErrorKortex as e:
            print(f"  ✗ {cuenta}: {e}")
            continue
        finally:
            del clave
        credenciales.guardar(perfil, cuenta, u)                       # solo el usuario: con MFA la contraseña no se guarda
        print(f"  ✓ {cuenta}: {u} entra · sesión renovable hasta {dt.datetime.fromtimestamp(r['renovable_hasta']):%d/%m %H:%M}")
        hechas += 1
    if credenciales.olvidar_claves():
        print("  · borradas las contraseñas que guardaba la versión anterior (con MFA ya no hacen falta)")
    if hechas:
        print(f"Listo. Sesión cifrada con DPAPI en {config.carpeta()} (fuera del repositorio). Dura 30 días: después, repite el login.")
    return 0 if hechas else 1


def _es_admin() -> bool:
    """24/11/2026: la web de ingesta dice si la persona es operadora de plataforma (equipo Kortex). Si no se puede saber, no."""
    try:
        return bool(Sesion("consulta", "ingesta").pedir("GET", "me").get("platform_operator"))
    except Exception:  # noqa: BLE001 — sin respuesta clara, se trata como usuario final (la KB se puede añadir con --perfil admin)
        return False


def _login_unico() -> int:
    """23/11/2026: un solo login para el MCP único. 24/11/2026: la persona usuaria solo ve SU usuario de la ingesta; la segunda
    entrada (la web de la KB) solo se pide si la ingesta dice que es del equipo Kortex (operador de plataforma)."""
    print("Login de Kortex: ten a mano tu aplicación de autenticación.")
    n = _login("consulta")
    if n != 0:
        return n
    if config.LOGIN_UNICO:                                           # 24/11/2026: la KB entra con esta misma sesión
        if credenciales.perfil_efectivo() == "admin":
            print("Eres administrador de la KB (grupo kb-admin): verás todas las herramientas.")
    elif _es_admin():
        print("Eres administrador de Kortex: falta tu sesión de la web de la KB (su propia contraseña y su propio código en la "
              "aplicación). Intro para omitirla.")
        _login("admin", solo_kb=True)
        print(f"Herramientas que verás: {'todas (admin)' if credenciales.perfil_efectivo() == 'admin' else 'las de consulta'}.")
    print("Si el MCP ya estaba arrancado, reinícialo con mcp\\arrancar.ps1.")
    return 0


def _registrar_escritorio(puerto=None, fichero=None) -> int:
    """24/11/2026 · Claude Code de escritorio (pestaña Code de la app de Claude) sin la CLI en el PATH: escribe la MISMA entrada que
    `claude mcp add --transport http kortex … --scope user` en ~/.claude.json (mcpServers.kortex), con copia previa, y quita los
    nombres antiguos (kortex-poc, kortex-poc-consulta). Solo toca esas claves."""
    import json
    import shutil
    from pathlib import Path
    from .http_local import PUERTOS, ficha_local
    f = Path(fichero) if fichero else Path.home() / ".claude.json"
    datos = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    if f.exists():
        shutil.copy2(f, f.with_name(f.name + ".antes-kortex"))
    srv = datos.setdefault("mcpServers", {})
    for viejo in ("kortex-poc", "kortex-poc-consulta"):
        srv.pop(viejo, None)
    srv["kortex"] = {"type": "http", "url": f"http://localhost:{puerto or PUERTOS['kortex']}/mcp",
                     "headers": {"Authorization": f"Bearer {ficha_local('kortex')}"}}
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(f)
    print(f"✓ MCP «kortex» registrado para Claude Code en {f} (copia previa: {f.name}.antes-kortex)")
    return 0


def _estado(perfiles):
    credenciales.olvidar_claves()
    for p in perfiles:
        cs = credenciales.cuentas(p)
        print(f"Perfil {p}: " + (", ".join(f"{c} = {credenciales.usuario(p, c)}" for c in cs) if cs else "sin login"))
        for c in cs:
            f = config.carpeta() / f"sesion_{p}_{c}.json"
            if not f.exists():
                print(f"  · sesión {c}: no hay (haz login)")
                continue
            try:
                t = Sesion(p, c)._cargar()
            except Exception:  # noqa: BLE001
                t = None
            if not t:
                print(f"  · sesión {c}: ilegible (repite el login)")
                continue
            hasta = (t.get("entrada") or 0) + REFRESCO_S
            ahora = dt.datetime.now().timestamp()
            if t.get("via") != "srp" or (t.get("entrada") and hasta < ahora):
                print(f"  · sesión {c}: caducada (repite el login)")
            else:
                print(f"  · sesión {c}: renovable hasta {dt.datetime.fromtimestamp(hasta):%d/%m %H:%M}" if t.get("entrada")
                      else f"  · sesión {c}: token hasta {dt.datetime.fromtimestamp(caducidad(t['acceso'])):%d/%m %H:%M}")


def _probar(perfil, puerto=None) -> int:
    """Habla con el servidor local por el protocolo MCP (HTTP + ficha local), como Claude Code: lista las herramientas y llama a
    quien_soy. Sin secretos en la salida."""
    import json

    import requests

    from .http_local import PUERTOS, ficha_local
    url = f"http://127.0.0.1:{puerto or PUERTOS[perfil]}/mcp"
    h = {"Authorization": f"Bearer {ficha_local(perfil)}", "Accept": "application/json, text/event-stream", "Content-Type": "application/json"}

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
        yo, _ = rpc({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "quien_soy", "arguments": {}}}, sid)
    except requests.RequestException as e:
        print(f"✗ el servidor del perfil {perfil} no responde en {url} ({type(e).__name__}). Arráncalo con mcp\\arrancar.ps1")
        return 2
    res = (yo or {}).get("result") or {}
    texto = "".join(c.get("text", "") for c in res.get("content") or [])
    print(f"✓ {url}: {len((lista or {}).get('result', {}).get('tools') or [])} herramientas")
    print(("✗ " if res.get("isError") else "") + texto)
    return 1 if res.get("isError") else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="kortex_mcp", description="MCP local de Kortex para Claude Code")
    ap.add_argument("orden", nargs="?", default="serve",
                    choices=["serve", "servir", "login", "logout", "estado", "registro", "registrar-escritorio", "probar"])
    ap.add_argument("--perfil", choices=list(config.PERFILES), default=None)
    ap.add_argument("--puerto", type=int, default=None, help="servir: puerto local (único y admin 8765, consulta 8766)")
    a = ap.parse_args(argv)
    if a.orden == "estado":
        _estado([a.perfil] if a.perfil else list(config.PERFILES))
        return 0
    if a.orden == "login":
        return _login(a.perfil) if a.perfil else _login_unico()
    if not a.perfil and a.orden == "logout":
        ap.error("indica --perfil consulta o --perfil admin")
    if a.orden == "logout":
        print("Borrado." if credenciales.borrar(a.perfil) else "No había nada guardado para ese perfil.")
        return 0
    if a.orden == "servir":                                          # HTTP solo en 127.0.0.1 (la política admite http://localhost*)
        from .http_local import servir
        servir(a.perfil, a.puerto)
        return 0
    if a.orden == "registro":                                        # la orden para registrarlo en Claude Code (con su ficha local)
        from .http_local import PUERTOS, ficha_local
        clave = a.perfil or "kortex"
        n = "kortex-consulta" if a.perfil == "consulta" else "kortex"   # 24/11/2026: «kortex» a secas
        print(f'claude mcp add --transport http {n} http://localhost:{a.puerto or PUERTOS[clave]}/mcp --scope user '
              f'--header "Authorization: Bearer {ficha_local(clave)}"')
        return 0
    if a.orden == "registrar-escritorio":                            # 24/11/2026: Claude Code de escritorio, sin la CLI «claude»
        return _registrar_escritorio(a.puerto)
    if a.orden == "probar":                                          # 20/11/2026: el servidor local responde como lo verá Claude Code
        return _probar(a.perfil or "kortex", a.puerto)
    from .servidor import crear                                      # el SDK solo se carga al servir
    crear(a.perfil or credenciales.perfil_efectivo()).run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
