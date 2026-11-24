"""Servido por HTTP solo en 127.0.0.1 con ficha local (para políticas que solo admiten http://localhost*): sin ficha, 401;
con Host u Origin que no son locales del puerto, 403 (DNS rebinding)."""
import asyncio

from mcps.kortex_mcp.conocimiento import http_local as H

LOCAL = (b"host", b"127.0.0.1:8765")


def _llamar(cabeceras, tipo="http", puerto=8765):
    enviados = []

    async def recibir():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def enviar(m):
        enviados.append(m)

    async def ok(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})
    asyncio.run(H._ExigeFicha(ok, "secreta", puerto)({"type": tipo, "headers": cabeceras}, recibir, enviar))
    return enviados[0].get("status", enviados[0]["type"])


def test_sin_ficha_o_con_ficha_mala_401_y_con_ficha_pasa():
    assert _llamar([LOCAL]) == 401
    assert _llamar([LOCAL, (b"authorization", b"Bearer otra")]) == 401
    assert _llamar([LOCAL, (b"authorization", b"Bearer secreta")]) == 200
    assert _llamar([(b"host", b"localhost:8765"), (b"authorization", b"Bearer secreta")]) == 200


def test_host_u_origin_ajenos_403_aunque_traigan_la_ficha():
    ficha = (b"authorization", b"Bearer secreta")
    assert _llamar([(b"host", b"kortex.ejemplo.test:8765"), ficha]) == 403          # DNS rebinding: nombre ajeno → 127.0.0.1
    assert _llamar([(b"host", b"127.0.0.1:9999"), ficha]) == 403                    # otro puerto
    assert _llamar([ficha]) == 403                                                   # sin Host
    assert _llamar([LOCAL, (b"origin", b"https://web.ejemplo.test"), ficha]) == 403
    assert _llamar([LOCAL, (b"origin", b"http://localhost:8765"), ficha]) == 200


def test_sin_websockets():
    assert _llamar([LOCAL], tipo="websocket") == "websocket.close"


def test_la_ficha_local_se_crea_una_vez_fuera_del_repositorio(tmp_path, monkeypatch):
    monkeypatch.setenv("KORTEX_HOME", str(tmp_path))
    a, b = H.ficha_local(), H.ficha_local()
    assert a == b and len(a) >= 32 and (tmp_path / "ficha_local.txt").exists()


def test_app_local_tambien_configura_el_sdk(tmp_path, monkeypatch):
    monkeypatch.setenv("KORTEX_HOME", str(tmp_path))
    capturado = {}

    class Srv:
        def streamable_http_app(self, **k):
            capturado.update(k)
            return "app"
    app = H.app_local(Srv(), 8790)
    seg = capturado["transport_security"]
    assert capturado["host"] == "127.0.0.1" and seg.enable_dns_rebinding_protection
    assert set(seg.allowed_hosts) == {"127.0.0.1:8790", "localhost:8790", "[::1]:8790"}
    assert isinstance(app, H._ExigeFicha) and app.app == "app"
