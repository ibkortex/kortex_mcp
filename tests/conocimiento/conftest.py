"""Dobles de prueba: HTTP falso (registra cada petición), Cognito falso y un «DPAPI» simulado reversible. Nada toca la red."""
import base64
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))          # raíz del repositorio (paquete mcps)

API = "https://api.ejemplo.test"                                       # entorno ficticio de las pruebas
POOL = "xx-region-1_PRUEBA"
CLIENTE = "cliente-prueba"


def jwt(exp, **claims):
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{b({'alg': 'none'})}.{b({'exp': int(exp), **claims})}.firma"


def cifrar(b: bytes) -> bytes:
    return b"FAKE-DPAPI:" + bytes(x ^ 0x5A for x in b)


def descifrar(b: bytes) -> bytes:
    assert b.startswith(b"FAKE-DPAPI:")
    return bytes(x ^ 0x5A for x in b[len(b"FAKE-DPAPI:"):])


class Resp:
    def __init__(self, status=200, body=None, headers=None, content=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.content = content if content is not None else (b"" if body is None else json.dumps(body).encode())
        self.text = self.content.decode("utf-8", "replace")

    def json(self):
        if self._body is None:
            raise ValueError("sin json")
        return self._body

    def iter_content(self, n):
        yield self.content

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class HTTP:
    """requests.Session falso: rutas → lista de respuestas (o callable). Guarda todas las llamadas."""

    def __init__(self, rutas=None):
        self.rutas = rutas or {}
        self.llamadas = []

    def request(self, metodo, url, json=None, params=None, headers=None, timeout=None):
        self.llamadas.append({"metodo": metodo, "url": url, "json": json, "params": params, "headers": headers})
        for (m, sufijo), r in self.rutas.items():
            if m == metodo and url.split("?")[0].endswith(sufijo):
                if callable(r):
                    return r(self.llamadas[-1])
                if isinstance(r, list):
                    return r.pop(0) if len(r) > 1 else r[0]
                return r
        return Resp(404, {"message": "Not Found"})

    def get(self, url, **k):
        return self.request("GET", url, **{x: k.get(x) for x in ("json", "params", "headers", "timeout")})

    def post(self, url, data=None, **k):
        self.llamadas.append({"metodo": "POST", "url": url, "data": data})
        return self.request("POST", url, headers=k.get("headers"))


class CognitoFalso:
    def __init__(self, reloj=time.time):
        self.reloj = reloj
        self.logins, self.refrescos = [], []
        self.refresco_falla = False
        self.clave_buena = "Clave-Buena-1"
        self.grupos = []
        self.revocados = []

    def _t(self, via, usuario="equipo2@ejemplo.test"):
        g = {"cognito:groups": self.grupos} if self.grupos else {}
        return {"acceso": jwt(self.reloj() + 3600, username=usuario, **g), "id": jwt(self.reloj() + 3600, email=usuario),
                "refresco": "R-" + str(len(self.logins)), "via": via}

    def srp(self, usuario, clave, cfg, pedir_codigo=None):
        from mcps.kortex_mcp.conocimiento.sesion import ErrorKortex
        self.logins.append(("srp", usuario))
        if clave != self.clave_buena:
            raise ErrorKortex("Usuario o contraseña incorrectos.")
        return self._t("srp", usuario)

    def refrescar_srp(self, refresco, cfg):
        from mcps.kortex_mcp.conocimiento.sesion import SesionCaducada
        self.refrescos.append(refresco)
        if self.refresco_falla:
            raise SesionCaducada("caducado")
        return {**self._t("srp"), "refresco": refresco}

    def revocar(self, refresco, cfg):
        self.revocados.append(refresco)


VARIABLES = ("KORTEX_API_URL", "KORTEX_API_KEY", "KORTEX_COGNITO_REGION", "KORTEX_COGNITO_POOL_ID", "KORTEX_COGNITO_CLIENT_ID",
             "KORTEX_ENTORNO", "KORTEX_CONFIG", "KORTEX_KNOWLEDGE_PREFIX", "KORTEX_KB_PREFIX", "KORTEX_KB_CAMPANA", "KORTEX_GRUPO_ADMIN")


@pytest.fixture
def sin_config(tmp_path, monkeypatch):
    """Carpeta de Kortex vacía y ninguna variable KORTEX_* del puesto: nada de la configuración real se cuela."""
    monkeypatch.setenv("KORTEX_HOME", str(tmp_path / "kortex"))
    monkeypatch.setenv("KORTEX_DESCARGAS", str(tmp_path / "descargas"))
    for v in VARIABLES:
        monkeypatch.delenv(v, raising=False)
    return tmp_path / "kortex"


@pytest.fixture
def home(sin_config, monkeypatch):
    """Entorno ficticio configurado por variables (sin config.json): datos en <home>/predeterminado."""
    monkeypatch.setenv("KORTEX_API_URL", API)
    monkeypatch.setenv("KORTEX_COGNITO_POOL_ID", POOL)
    monkeypatch.setenv("KORTEX_COGNITO_CLIENT_ID", CLIENTE)
    return sin_config


class Reloj:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def reloj():
    return Reloj()


@pytest.fixture
def sesion(home, reloj):
    """Fábrica de sesiones con HTTP y Cognito falsos, ya con login hecho."""
    from mcps.kortex_mcp.conocimiento.sesion import Sesion

    def hacer(cuenta="ingesta", rutas=None, login=True, grupos=()):
        http, cog = HTTP(rutas), CognitoFalso(reloj)
        cog.grupos = list(grupos)
        s = Sesion(cuenta, http=http, cognito=cog, cifrar=cifrar, descifrar=descifrar, reloj=reloj, dormir=lambda x: None)
        if login:
            s.entrar("equipo2@ejemplo.test" if cuenta == "ingesta" else "admin", cog.clave_buena)
        return s, http, cog
    return hacer
