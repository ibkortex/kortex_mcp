"""list_collections y retrieve: mismo comportamiento que antes de añadir el conocimiento (clave personal, /dataplane). Sin red:
httpx con un transporte simulado."""
import json

import httpx
import pytest

from mcps.kortex_mcp import server


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("KORTEX_HOME", str(tmp_path / "kortex"))
    for v in ("KORTEX_API_URL", "KORTEX_API_KEY", "KORTEX_ENTORNO", "KORTEX_CONFIG"):
        monkeypatch.delenv(v, raising=False)
    return tmp_path / "kortex"


@pytest.fixture
def backend(monkeypatch):
    """Sustituye la red de httpx: guarda cada petición y responde lo que diga `respuesta`."""
    peticiones, estado = [], {"respuesta": httpx.Response(200, json={"ok": True})}
    real = httpx.Client

    def manejador(req):
        peticiones.append(req)
        return estado["respuesta"]
    monkeypatch.setattr(httpx, "Client", lambda **k: real(transport=httpx.MockTransport(manejador), **k))
    return peticiones, estado


def test_list_collections(entorno, backend, monkeypatch):
    peticiones, estado = backend
    monkeypatch.setenv("KORTEX_API_URL", "https://kortex.ejemplo.test/")
    monkeypatch.setenv("KORTEX_API_KEY", "kx_live_id_secreto")
    estado["respuesta"] = httpx.Response(200, json={"collections": [{"id": "c1"}], "excludedCollections": []})
    assert server.list_collections() == {"collections": [{"id": "c1"}], "excludedCollections": []}
    r = peticiones[0]
    assert (r.method, str(r.url)) == ("GET", "https://kortex.ejemplo.test/dataplane/collections")
    assert r.headers["x-api-key"] == "kx_live_id_secreto" and r.headers["user-agent"].startswith("kortex-mcp/")


def test_retrieve_cuerpo_con_y_sin_colecciones(entorno, backend, monkeypatch):
    peticiones, _ = backend
    monkeypatch.setenv("KORTEX_API_KEY", "kx_live_id_secreto")
    server.retrieve("¿qué es una OT?")
    server.retrieve("otra", collections=["c1:v2"], number_of_results=3)
    assert str(peticiones[0].url) == "http://localhost:8080/dataplane/retrieve"           # por defecto, como antes
    assert json.loads(peticiones[0].content) == {"query": "¿qué es una OT?", "numberOfResults": 10}
    assert json.loads(peticiones[1].content) == {"query": "otra", "numberOfResults": 3, "collections": ["c1:v2"]}


def test_error_del_backend_y_falta_de_clave(entorno, backend, monkeypatch):
    _, estado = backend
    with pytest.raises(RuntimeError, match="KORTEX_API_KEY is not set"):
        server.list_collections()
    monkeypatch.setenv("KORTEX_API_KEY", "kx_live_id_secreto")
    estado["respuesta"] = httpx.Response(403, json={"detail": "Collection not in scope"})
    with pytest.raises(RuntimeError, match="Kortex API 403: Collection not in scope"):
        server.retrieve("x", collections=["ajena"])


def test_api_url_de_config_json_si_no_hay_variable(entorno, backend, monkeypatch):
    peticiones, _ = backend
    entorno.mkdir(parents=True, exist_ok=True)
    (entorno / "config.json").write_text(json.dumps({"api_url": "https://desde-fichero.ejemplo.test"}), encoding="utf-8")
    monkeypatch.setenv("KORTEX_API_KEY", "kx_live_id_secreto")
    server.list_collections()
    monkeypatch.setenv("KORTEX_API_URL", "https://desde-variable.ejemplo.test")
    server.list_collections()
    assert [r.url.host for r in peticiones] == ["desde-fichero.ejemplo.test", "desde-variable.ejemplo.test"]


def test_las_herramientas_oficiales_conservan_su_firma(entorno):
    import asyncio
    srv = server.crear_servidor(None)
    tools = {t.name: t for t in asyncio.run(srv.list_tools())}
    assert set(tools["retrieve"].input_schema["properties"]) == {"query", "collections", "number_of_results"}
    assert tools["retrieve"].input_schema["required"] == ["query"] and not tools["list_collections"].input_schema.get("required")
