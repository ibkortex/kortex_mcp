"""Cuentas del MCP y cifrado DPAPI de Windows (ligado a la cuenta de Windows de quien hace el login: otro usuario u otra máquina no
lo descifra).

23/11/2026, MFA obligatorio en los dos pools: ya NO se guarda la contraseña. Aquí queda solo QUÉ usuario hizo login en cada cuenta
(ingesta / kb) de cada perfil, en %USERPROFILE%\\.kortex\\credenciales_<perfil>.json (sin secretos). La sesión (tokens, cifrados con
DPAPI) la lleva sesion.py y dura 30 días (24/11/2026); al caducar se repite el login con un código nuevo de la aplicación de autenticación.
Las contraseñas que guardaban las versiones anteriores se borran al hacer login o al arrancar el servidor (olvidar_claves)."""
import ctypes
import json
import os
import sys

from . import config


class SinCredenciales(Exception):
    pass


# ------------------------------------------------------------------ DPAPI (ctypes, sin dependencias)
class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def dpapi_cifrar(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise SinCredenciales("DPAPI solo existe en Windows")
    entrada, _keep = _blob(data)
    salida = _BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(entrada), "kortex-mcp", None, None, None, 0x01, ctypes.byref(salida)):
        raise SinCredenciales("No se pudo cifrar con DPAPI")
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(salida.pbData)


def dpapi_descifrar(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise SinCredenciales("DPAPI solo existe en Windows")
    entrada, _keep = _blob(data)
    salida = _BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(entrada), None, None, None, None, 0x01, ctypes.byref(salida)):
        raise SinCredenciales("No se pudo descifrar (¿otra cuenta de Windows u otra máquina?). Vuelve a hacer login.")
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(salida.pbData)


# ------------------------------------------------------------------ fichero por perfil y cuenta (solo el usuario)
def _fichero(perfil: str):
    return config.carpeta() / f"credenciales_{perfil}.json"


def _leer(f) -> dict:
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except ValueError:
        return {}


def _escribir(f, datos: dict):
    f.write_text(json.dumps(datos, indent=1), encoding="utf-8")
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass


def guardar(perfil: str, cuenta: str, usuario: str, clave=None, cifrar=None):
    """cuenta = «ingesta» o «kb». Guarda SOLO el usuario (con MFA la contraseña no sirve para volver a entrar sola): `clave` y
    `cifrar` se aceptan por compatibilidad y se ignoran."""
    f = _fichero(perfil)
    datos = _leer(f)
    datos[cuenta] = {"usuario": usuario}
    _escribir(f, datos)


def olvidar_claves() -> int:
    """Borra las contraseñas cifradas que guardaban las versiones anteriores al MFA. Devuelve cuántas había."""
    n = 0
    for f in config.carpeta().glob("credenciales_*.json"):
        datos = _leer(f)
        cambia = False
        for v in datos.values():
            if isinstance(v, dict) and "clave_dpapi" in v:
                del v["clave_dpapi"]
                n += 1
                cambia = True
        if cambia:
            _escribir(f, datos)
    return n


def cuentas(perfil: str) -> list:
    return sorted(c for c, v in _leer(_fichero(perfil)).items() if isinstance(v, dict) and v.get("usuario"))


def usuario(perfil: str, cuenta: str) -> str | None:
    return (_leer(_fichero(perfil)).get(cuenta) or {}).get("usuario")


def grupos_ingesta() -> set:
    """Grupos de Cognito del usuario de la sesión de la ingesta (claim «cognito:groups» del token; no hace falta que esté vigente)."""
    import base64
    f = config.carpeta() / f"sesion_{perfil_de_cuenta('admin', 'ingesta')}_ingesta.json"
    try:
        t = json.loads(dpapi_descifrar(f.read_bytes()).decode("utf-8"))
        cuerpo = (t.get("acceso") or "").split(".")[1]
        return set(json.loads(base64.urlsafe_b64decode(cuerpo + "=" * (-len(cuerpo) % 4))).get("cognito:groups") or [])
    except Exception:  # noqa: BLE001 — sin sesión, ilegible o fuera de Windows: sin grupos
        return set()


def perfil_efectivo() -> str:
    """MCP único (23/11/2026): quien es admin de la KB ve todas las herramientas; el resto, solo las de consulta. 24/11/2026, login
    único: admin = el usuario de la ingesta está en el grupo kb-admin (lo decide AWS, no la persona)."""
    if config.LOGIN_UNICO:
        return "admin" if config.GRUPO_ADMIN in grupos_ingesta() else "consulta"
    return "admin" if "kb" in cuentas("admin") else "consulta"


def perfil_de_cuenta(perfil: str, cuenta: str) -> str:
    """Perfil donde están las credenciales de esa cuenta. El admin usa el login de ingesta del perfil consulta si no tiene uno propio
    (con el login único, el usuario de ingesta se guarda una sola vez, en consulta). 24/11/2026, login único: la ingesta y la KB
    usan SIEMPRE la sesión de consulta; los logins antiguos del perfil admin (genéricos ya borrados) se ignoran."""
    if config.LOGIN_UNICO and perfil == "admin" and cuenta in ("ingesta", "kb"):
        return "consulta"
    if perfil == "admin" and cuenta == "ingesta" and "ingesta" not in cuentas("admin") and "ingesta" in cuentas("consulta"):
        return "consulta"
    return perfil


def borrar(perfil: str) -> bool:
    ok = False
    for f in (_fichero(perfil), *config.carpeta().glob(f"sesion_{perfil}_*.json")):
        if f.exists():
            f.unlink()
            ok = True
    return ok
