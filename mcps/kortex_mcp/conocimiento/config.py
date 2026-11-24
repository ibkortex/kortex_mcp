"""Endpoints y perfiles. Los valores son públicos (los mismos config.json que sirven las dos webs); se pueden sobrescribir con variables
de entorno KORTEX_* para otro entorno."""
import os
from pathlib import Path

REGION = os.environ.get("KORTEX_REGION", "eu-west-1")

# Web de ingesta (consulta): mismo pool y cliente que la web (<web de ingesta>/config.json)
INGESTA = {
    "api": os.environ.get("KORTEX_INGESTA_API", "https://<api-de-ingesta>/poc/v3"),
    "pool": os.environ.get("KORTEX_INGESTA_POOL", "<pool-de-ingesta>"),
    # 24/11/2026: cliente PROPIO del MCP (iac/identity.tf «mcp»): su sesión dura 30 días (el de la web, <cliente-web>, 8 h)
    "cliente": os.environ.get("KORTEX_INGESTA_CLIENTE", "<cliente-mcp>"),
}
# 24/11/2026 · LOGIN ÚNICO: la KB usa el pool y la sesión de la ingesta (un usuario, un TOTP); es admin quien está en el grupo
# kb-admin. KORTEX_LOGIN_UNICO=0 vuelve al login propio de la KB (pool antiguo, que se conserva).
LOGIN_UNICO = os.environ.get("KORTEX_LOGIN_UNICO", "1") != "0"
GRUPO_ADMIN = os.environ.get("KORTEX_GRUPO_ADMIN", "kb-admin")
# Web de la KB (administración): <web de la KB>/config.json («api»: "/api" en el mismo origen)
KB = {
    "api": os.environ.get("KORTEX_KB_API", "https://<web-de-la-kb>/api"),
    "pool": os.environ.get("KORTEX_KB_POOL", INGESTA["pool"] if LOGIN_UNICO else "<pool-de-la-kb>"),
    "cliente": os.environ.get("KORTEX_KB_CLIENTE", INGESTA["cliente"] if LOGIN_UNICO else "<cliente-kb>"),
    "campana": os.environ.get("KORTEX_KB_CAMPANA", "KORTEX"),
    # 23/11/2026: se entra por SRP + TOTP como en la ingesta (la API de la KB acepta también ese ámbito, kbweb/iac/api.tf)
}

# Perfil → cuentas que usa. «consulta»: un usuario de la ingesta. «admin»: un usuario de la KB y, opcional, uno de la ingesta.
PERFILES = {"consulta": ("ingesta",), "admin": ("kb", "ingesta")}


def carpeta() -> Path:
    """%USERPROFILE%\\.kortex (fuera del repositorio): credenciales cifradas, sesiones y fotos para «lo nuevo desde»."""
    p = Path(os.environ.get("KORTEX_HOME") or (Path.home() / ".kortex"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def descargas() -> Path:
    p = Path(os.environ.get("KORTEX_DESCARGAS") or (Path.home() / "Downloads" / "kortex"))
    p.mkdir(parents=True, exist_ok=True)
    return p
