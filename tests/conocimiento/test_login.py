"""La línea de órdenes: login (la contraseña no se guarda ni se imprime), estado, logout, arranque y registro en el cliente."""
import json

import pytest
from conftest import CognitoFalso, cifrar, descifrar

from mcps.kortex_mcp import cli
from mcps.kortex_mcp.conocimiento import credenciales
from mcps.kortex_mcp.conocimiento import sesion as S


@pytest.fixture
def dpapi_falso(monkeypatch):
    monkeypatch.setattr(credenciales, "dpapi_cifrar", cifrar)
    monkeypatch.setattr(credenciales, "dpapi_descifrar", descifrar)


def _login(monkeypatch, capsys, respuestas, cognito):
    entradas = iter(respuestas)
    monkeypatch.setattr("builtins.input", lambda *_: next(entradas))
    monkeypatch.setattr(cli.getpass, "getpass", lambda *_: cognito.clave_buena)
    monkeypatch.setattr(S, "Cognito", lambda: cognito)
    rc = cli.main(["login"])
    return rc, capsys.readouterr().out


def test_login_guarda_solo_la_sesion_cifrada(home, dpapi_falso, monkeypatch, capsys):
    cog = CognitoFalso()
    rc, salida = _login(monkeypatch, capsys, ["ana@ejemplo.test"], cog)
    assert rc == 0 and cog.logins == [("srp", "ana@ejemplo.test")]
    assert "✓ ana@ejemplo.test entra" in salida and "las de consulta" in salida and "Clave-Buena-1" not in salida
    ficheros = [f for f in home.rglob("*") if f.is_file()]
    assert [f.name for f in ficheros] == ["sesion.dpapi"]
    assert b"Clave-Buena-1" not in ficheros[0].read_bytes() and S.perfil_actual() == "consulta"


def test_login_admin_por_grupo(home, dpapi_falso, monkeypatch, capsys):
    cog = CognitoFalso()
    cog.grupos = ["kb-admin"]
    rc, salida = _login(monkeypatch, capsys, ["ana@ejemplo.test"], cog)
    assert rc == 0 and "administración de la KB" in salida and S.perfil_actual() == "admin"


def test_login_sugiere_el_usuario_anterior(home, dpapi_falso, monkeypatch, capsys):
    _login(monkeypatch, capsys, ["ana@ejemplo.test"], CognitoFalso())
    cog = CognitoFalso()
    rc, _ = _login(monkeypatch, capsys, [""], cog)                    # Intro: el mismo usuario
    assert rc == 0 and cog.logins == [("srp", "ana@ejemplo.test")]


def test_login_sin_configuracion_no_pregunta_nada(sin_config, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("no debe preguntar"))
    assert cli.main(["login"]) == 2
    assert "KORTEX_COGNITO_POOL_ID" in capsys.readouterr().out


def test_login_con_contrasena_mala(home, dpapi_falso, monkeypatch, capsys):
    cog = CognitoFalso()
    cog.clave_buena = "otra"
    entradas = iter(["ana@ejemplo.test"])
    monkeypatch.setattr("builtins.input", lambda *_: next(entradas))
    monkeypatch.setattr(cli.getpass, "getpass", lambda *_: "mala")
    monkeypatch.setattr(S, "Cognito", lambda: cog)
    assert cli.main(["login"]) == 1
    assert "✗ Usuario o contraseña incorrectos" in capsys.readouterr().out and S.leer_tokens() is None


def test_estado_y_logout(home, dpapi_falso, monkeypatch, capsys):
    cog = CognitoFalso()
    _login(monkeypatch, capsys, ["ana@ejemplo.test"], cog)
    assert cli.main(["estado"]) == 0
    salida = capsys.readouterr().out
    assert "Entorno: predeterminado" in salida and "/knowledge/v1" in salida and "perfil consulta" in salida
    assert "acceso" not in salida and "R-1" not in salida
    assert cli.main(["logout"]) == 0 and cog.revocados == ["R-1"] and S.leer_tokens() is None


def test_entorno_por_linea_de_ordenes(sin_config, monkeypatch, capsys):
    sin_config.mkdir(parents=True, exist_ok=True)
    (sin_config / "config.json").write_text(json.dumps({"entornos": {
        "dev": {"api_url": "https://dev.ejemplo.test", "cognito_pool_id": "r-1_D", "cognito_client_id": "c"},
        "prod": {"api_url": "https://prod.ejemplo.test", "cognito_pool_id": "r-1_P", "cognito_client_id": "c"}}}), encoding="utf-8")
    assert cli.main(["estado", "--entorno", "prod"]) == 0
    assert "https://prod.ejemplo.test/kb/v1" in capsys.readouterr().out


# ---------------------------------------------------------------------- arranque
class _SrvFalso:
    def __init__(self):
        self.servido = None

    def run(self):
        self.servido = "stdio"


@pytest.fixture
def arranque(monkeypatch):
    from mcps.kortex_mcp import server
    hecho = {}

    def crear(perfil):
        hecho["perfil"], hecho["srv"] = perfil, _SrvFalso()
        return hecho["srv"]
    monkeypatch.setattr(server, "crear_servidor", crear)
    return hecho


def test_sin_clave_ni_conocimiento_sale_como_antes(sin_config, arranque, capsys):
    assert cli.main([]) == 1
    assert "KORTEX_API_KEY is not set — exiting." in capsys.readouterr().err and not arranque


def test_con_clave_sirve_por_stdio_sin_sesion(sin_config, arranque, monkeypatch, capsys):
    monkeypatch.setenv("KORTEX_API_KEY", "kx_live_prueba_x")
    assert cli.main([]) == 0
    assert arranque["perfil"] is None and arranque["srv"].servido == "stdio"
    assert "defaulting to http://localhost:8080" in capsys.readouterr().err


def test_solo_con_login_configurado_tambien_sirve(home, arranque, capsys):
    assert cli.main(["serve"]) == 0 and arranque["srv"].servido == "stdio"
    err = capsys.readouterr().err
    assert "KORTEX_API_KEY no está definida" in err and "Sin sesión de conocimiento" in err


def test_http_local_usa_el_puerto_pedido(home, arranque, monkeypatch):
    from mcps.kortex_mcp.conocimiento import http_local
    llamado = {}
    monkeypatch.setattr(http_local, "servir", lambda srv, puerto: llamado.update(srv=srv, puerto=puerto))
    assert cli.main(["serve", "--http-local", "--port", "8799"]) == 0
    assert llamado == {"srv": arranque["srv"], "puerto": 8799} and arranque["srv"].servido is None


# ---------------------------------------------------------------------- registro en el cliente (modo HTTP local)
def test_registro(sin_config, capsys):
    assert cli.main(["registro"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("claude mcp add --transport http kortex http://localhost:8765/mcp --scope user --header \"Authorization: Bearer ")


def test_registrar_escritorio_solo_toca_kortex(sin_config, tmp_path):
    f = tmp_path / ".claude.json"
    f.write_text(json.dumps({"otra": 1, "mcpServers": {"ajeno": {"url": "y"}}}), encoding="utf-8")
    assert cli._registrar_escritorio(fichero=str(f)) == 0
    d = json.loads(f.read_text(encoding="utf-8"))
    assert d["otra"] == 1 and d["mcpServers"]["ajeno"] == {"url": "y"}
    k = d["mcpServers"]["kortex"]
    assert k["type"] == "http" and k["url"] == "http://localhost:8765/mcp" and k["headers"]["Authorization"].startswith("Bearer ")
    assert (tmp_path / ".claude.json.antes-kortex").exists()
