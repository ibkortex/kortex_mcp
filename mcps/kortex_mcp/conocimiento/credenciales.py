"""Cifrado DPAPI de Windows para la sesión del MCP (ligado a la cuenta de Windows de quien hace el login: otro usuario u otra
máquina no lo descifra). No se guarda NUNCA la contraseña: con MFA no serviría para volver a entrar sola. Lo único que se guarda,
cifrado, son los tokens de Cognito (sesion.py), en una carpeta por entorno dentro de %USERPROFILE%\\.kortex.
Fuera de Windows no hay DPAPI: la sesión no se guarda en disco (las herramientas de conocimiento necesitan Windows)."""
import ctypes
import sys


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
