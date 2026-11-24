import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from conftest import API, CLIENTE, POOL, Resp, descifrar, jwt

from mcps.kortex_mcp import server
from mcps.kortex_mcp.conocimiento import credenciales, servidor

OFICIALES = {"list_collections", "retrieve"}
CONSULTA = {"quien_soy", "equipos_y_carpetas", "documentos", "consultar", "leer_documento", "descargar_original"}
ADMIN = {"operar_kb", "catalogo_kb", "buscar_hpum", "estado_kb", "buscar_entidades", "entidad", "relaciones", "por_que", "documento_en_kb", "ambito", "contexto", "metricas", "lo_nuevo_desde",
         "marcar_revision", "ficha_html", "historial", "validar", "rechazar", "corregir_tipo", "corregir_nombre", "fusionar", "mantener_separadas",
         "decidir_en_bloque", "deshacer", "exportar_decisiones", "consolidaciones", "abrir_consolidacion", "consolidacion", "cerrar_consolidacion",
         "propuestas", "explicar_propuesta", "analizar_consolidacion", "aplicar_propuestas", "descartar_propuestas", "fuentes", "ingesta_pendiente",
         "actualizar_desde_ingesta", "quitar_o_incorporar_documentos", "estado_reanalisis", "reanalizar", "asistente_web",
         "generar_fichas_revision", "importar_respuestas_ficha", "previsualizar_correcciones_ficha", "aplicar_correcciones_ficha", "fichas_revision"}
RAIZ = Path(__file__).resolve().parents[2]


def _nombres(srv):
    return {t.name for t in asyncio.run(srv.list_tools())}


def _texto(r):
    contenido = r[0] if isinstance(r, tuple) else getattr(r, "content", r)
    return "".join(getattr(c, "text", "") for c in contenido)


# ---------------------------------------------------------------------- registro condicional en el servidor oficial
def test_sin_sesion_solo_las_oficiales_y_estado_sesion(home):
    srv = server.crear_servidor()
    assert _nombres(srv) == OFICIALES | {"estado_sesion"}
    texto = _texto(asyncio.run(srv.call_tool("estado_sesion", {})))
    assert "kortex-mcp login" in texto and "No pidas ni escribas contraseñas" in texto


def test_sin_configuracion_estado_sesion_dice_que_falta(sin_config):
    srv = server.crear_servidor()
    assert _nombres(srv) == OFICIALES | {"estado_sesion"}
    assert "KORTEX_COGNITO_POOL_ID" in _texto(asyncio.run(srv.call_tool("estado_sesion", {})))


def test_perfiles_explicitos(home):
    assert _nombres(server.crear_servidor("consulta")) == OFICIALES | CONSULTA
    assert _nombres(server.crear_servidor("admin")) == OFICIALES | CONSULTA | ADMIN
    assert len(OFICIALES | CONSULTA | ADMIN) == 54
    assert _nombres(server.mcp) == OFICIALES                         # el objeto de siempre, solo plano de datos


def test_el_perfil_sale_del_grupo_del_token_guardado(sesion, home, monkeypatch):
    monkeypatch.setattr(credenciales, "dpapi_descifrar", descifrar)
    sesion("ingesta")
    assert _nombres(server.crear_servidor()) == OFICIALES | CONSULTA
    sesion("ingesta", grupos=["kb-admin"])
    assert _nombres(server.crear_servidor()) == OFICIALES | CONSULTA | ADMIN
    estado = _texto(asyncio.run(servidor.registrar_sin_sesion(servidor.MCPServer("x")).call_tool("estado_sesion", {})))
    assert "Ya hay sesión de Kortex (perfil admin" in estado          # login hecho después de arrancar: hay que reiniciar


def test_instrucciones_segun_perfil(home):
    assert "estado_sesion" in server.crear_servidor(None).instructions
    assert "Kortex (consulta)" in server.crear_servidor("consulta").instructions
    assert "Kortex (admin)" in server.crear_servidor("admin").instructions
    assert server.crear_servidor("admin").instructions.startswith("You have access to the Kortex enterprise data plane.")


def test_prompts(home):
    assert {p.name for p in asyncio.run(servidor.crear("admin").list_prompts())} == {"revision_de_carga", "informe_de_siempre", "contrastar_kb", "contrastar_con_mi_contexto"}
    assert {p.name for p in asyncio.run(servidor.crear("consulta").list_prompts())} == {"contrastar_con_mi_contexto"}


def test_error_llega_en_espanol(home):
    from mcp.server.mcpserver.exceptions import ToolError
    with pytest.raises(ToolError, match=r"ha caducado o no existe .*kortex-mcp login"):
        asyncio.run(servidor.crear("consulta").call_tool("quien_soy", {}))


def test_falta_de_configuracion_llega_como_mensaje(sin_config):
    from mcp.server.mcpserver.exceptions import ToolError
    with pytest.raises(ToolError, match=r"Falta configuración de Kortex"):
        asyncio.run(server.crear_servidor("consulta").call_tool("documentos", {}))


def test_herramienta_con_sesion_falsa(sesion):
    s, _, _ = sesion("ingesta", rutas={("GET", "/me"): Resp(200, {"label": "equipo2@ejemplo.test", "teams": [{"team_id": "T2", "name": "Equipo 2", "roles": ["reader"]}]})})
    srv = server.crear_servidor("consulta", fabrica=lambda cuenta: s)
    texto = _texto(asyncio.run(srv.call_tool("quien_soy", {})))
    assert "Equipo 2 (T2)" in texto
    assert "MCP: kortex · herramientas de consulta (perfil consulta)" in texto
    assert "Sesión: equipo2@ejemplo.test · entorno predeterminado" in texto


# ---------------------------------------------------------------------- por stdio, como lo lanza un cliente MCP
def _sesion_dpapi(home: Path, grupos):
    """Escribe una sesión con DPAPI real (como la dejaría `kortex-mcp login`) para el proceso hijo."""
    t = {"acceso": jwt(4_000_000_000, username="u@ejemplo.test", **({"cognito:groups": grupos} if grupos else {})),
         "id": jwt(4_000_000_000, email="u@ejemplo.test"), "refresco": "R", "via": "srp", "entrada": 4_000_000_000}
    (home / "predeterminado").mkdir(parents=True, exist_ok=True)
    (home / "predeterminado" / "sesion.dpapi").write_bytes(credenciales.dpapi_cifrar(json.dumps(t).encode()))


def _por_stdio(env):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def lista():
        p = StdioServerParameters(command=sys.executable, args=["-m", "mcps.kortex_mcp.server"], cwd=str(RAIZ), env=env)
        async with stdio_client(p) as (r, w), ClientSession(r, w) as c:
            await c.initialize()
            return {t.name for t in (await c.list_tools()).tools}
    return asyncio.run(lista())


@pytest.fixture
def env_hijo(tmp_path):
    base = {k: v for k, v in os.environ.items() if not k.startswith("KORTEX_")}
    return {**base, "PYTHONPATH": str(RAIZ), "KORTEX_HOME": str(tmp_path / "k"), "KORTEX_API_KEY": "kx_live_prueba_secreto",
            "KORTEX_API_URL": API, "KORTEX_COGNITO_POOL_ID": POOL, "KORTEX_COGNITO_CLIENT_ID": CLIENTE}


def test_stdio_sin_sesion(env_hijo):
    assert _por_stdio(env_hijo) == OFICIALES | {"estado_sesion"}


@pytest.mark.skipif(sys.platform != "win32", reason="la sesión se guarda con DPAPI (Windows)")
def test_stdio_con_sesion_consulta_y_admin(env_hijo, tmp_path):
    _sesion_dpapi(tmp_path / "k", [])
    assert _por_stdio(env_hijo) == OFICIALES | CONSULTA
    _sesion_dpapi(tmp_path / "k", ["kb-admin"])
    assert _por_stdio(env_hijo) == OFICIALES | CONSULTA | ADMIN
