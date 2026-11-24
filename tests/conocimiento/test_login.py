"""24/11/2026: el login único solo pide la segunda entrada (web de la KB) al equipo Kortex; la persona usuaria no la ve."""
from kortex_mcp import __main__ as cli


def _simular(monkeypatch, capsys, admin, resultado_ingesta=0):
    llamadas = []
    monkeypatch.setattr(cli, "_login", lambda perfil, solo_kb=False: llamadas.append((perfil, solo_kb)) or resultado_ingesta)
    monkeypatch.setattr(cli, "_es_admin", lambda: admin)
    monkeypatch.setattr(cli.credenciales, "perfil_efectivo", lambda: "admin" if admin else "consulta")   # nunca la sesión real del equipo
    rc = cli._login_unico()
    return rc, llamadas, capsys.readouterr().out


def test_usuario_final_solo_ve_su_usuario_de_ingesta(monkeypatch, capsys):
    rc, llamadas, salida = _simular(monkeypatch, capsys, admin=False)
    assert rc == 0 and llamadas == [("consulta", False)]
    assert "KB" not in salida and "equipo Kortex" not in salida


def test_admin_tambien_entra_en_la_kb_sin_login_unico(monkeypatch, capsys):
    monkeypatch.setattr(cli.config, "LOGIN_UNICO", False)
    rc, llamadas, salida = _simular(monkeypatch, capsys, admin=True)
    assert rc == 0 and llamadas == [("consulta", False), ("admin", True)]
    assert "web de la KB" in salida


def test_login_unico_admin_por_grupo_sin_segunda_entrada(monkeypatch, capsys):
    monkeypatch.setattr(cli.config, "LOGIN_UNICO", True)
    rc, llamadas, salida = _simular(monkeypatch, capsys, admin=True)
    assert rc == 0 and llamadas == [("consulta", False)] and "kb-admin" in salida


def test_si_falla_la_ingesta_no_pregunta_nada_mas(monkeypatch, capsys):
    rc, llamadas, _ = _simular(monkeypatch, capsys, admin=True, resultado_ingesta=1)
    assert rc == 1 and llamadas == [("consulta", False)]


def test_es_admin_sin_respuesta_es_usuario_final(monkeypatch):
    class Rota:
        def __init__(self, *a, **k):
            pass

        def pedir(self, *a, **k):
            raise RuntimeError("sin red")
    monkeypatch.setattr(cli, "Sesion", Rota)
    assert cli._es_admin() is False


def test_perfil_por_grupo_y_kb_con_la_misma_sesion(home, monkeypatch):
    """Login único: el perfil sale del grupo del token de la ingesta y la sesión de la KB es el mismo fichero que la de la ingesta."""
    import base64
    import json
    from conftest import cifrar
    from kortex_mcp import config, credenciales
    from kortex_mcp.sesion import Sesion
    monkeypatch.setattr(config, "LOGIN_UNICO", True)
    monkeypatch.setattr(credenciales, "dpapi_descifrar", lambda b: b)

    def token(grupos):
        cuerpo = base64.urlsafe_b64encode(json.dumps({"cognito:groups": grupos, "exp": 9999999999}).encode()).decode().rstrip("=")
        return f"h.{cuerpo}.f"
    credenciales.guardar("consulta", "ingesta", "ana@ejemplo.test", cifrar=cifrar)
    f = config.carpeta() / "sesion_consulta_ingesta.json"
    f.write_bytes(json.dumps({"acceso": token([])}).encode())
    assert credenciales.perfil_efectivo() == "consulta"
    f.write_bytes(json.dumps({"acceso": token(["kb-admin"])}).encode())
    assert credenciales.perfil_efectivo() == "admin"
    assert Sesion("admin", "kb")._fichero == f
    assert Sesion("admin", "kb").cfg["pool"] == config.INGESTA["pool"]


def test_registrar_escritorio_solo_toca_kortex(home, tmp_path):
    import json
    f = tmp_path / ".claude.json"
    f.write_text(json.dumps({"otra": 1, "mcpServers": {"kortex-poc": {"url": "x"}, "ajeno": {"url": "y"}}}), encoding="utf-8")
    assert cli._registrar_escritorio(fichero=str(f)) == 0
    d = json.loads(f.read_text(encoding="utf-8"))
    assert d["otra"] == 1 and "kortex-poc" not in d["mcpServers"] and d["mcpServers"]["ajeno"] == {"url": "y"}
    k = d["mcpServers"]["kortex"]
    assert k["type"] == "http" and k["url"] == "http://localhost:8765/mcp" and k["headers"]["Authorization"].startswith("Bearer ")
    assert (tmp_path / ".claude.json.antes-kortex").exists()


def test_login_unico_ignora_logins_antiguos_del_perfil_admin(home, monkeypatch):
    from conftest import cifrar
    from kortex_mcp import config, credenciales
    from kortex_mcp.sesion import Sesion
    monkeypatch.setattr(config, "LOGIN_UNICO", True)
    credenciales.guardar("consulta", "ingesta", "ana@ejemplo.test", cifrar=cifrar)
    credenciales.guardar("admin", "ingesta", "generico@ejemplo.test", cifrar=cifrar)
    credenciales.guardar("admin", "kb", "admin", cifrar=cifrar)
    assert credenciales.perfil_de_cuenta("admin", "ingesta") == "consulta"
    assert Sesion(credenciales.perfil_de_cuenta("admin", "kb"), "kb")._fichero.name == "sesion_consulta_ingesta.json"
