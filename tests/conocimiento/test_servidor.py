import asyncio
import os
import sys
from pathlib import Path

import pytest
from conftest import Resp

from kortex_mcp import servidor

CONSULTA = {"quien_soy", "equipos_y_carpetas", "documentos", "consultar", "leer_documento", "preguntar_chat_web", "descargar_original"}
ADMIN = {"operar_kb", "catalogo_kb", "buscar_hpum", "estado_kb", "buscar_entidades", "entidad", "relaciones", "por_que", "documento_en_kb", "ambito", "contexto", "metricas", "lo_nuevo_desde",
         "marcar_revision", "ficha_html", "historial", "validar", "rechazar", "corregir_tipo", "corregir_nombre", "fusionar", "mantener_separadas",
         "decidir_en_bloque", "deshacer", "exportar_decisiones", "consolidaciones", "abrir_consolidacion", "consolidacion", "cerrar_consolidacion",
         "propuestas", "explicar_propuesta", "analizar_consolidacion", "aplicar_propuestas", "descartar_propuestas", "fuentes", "ingesta_pendiente",
         "actualizar_desde_ingesta", "quitar_o_incorporar_documentos", "estado_reanalisis", "reanalizar", "asistente_web",
         "generar_fichas_revision", "importar_respuestas_ficha", "previsualizar_correcciones_ficha", "aplicar_correcciones_ficha", "fichas_revision"}


def _nombres(perfil):
    return {t.name for t in asyncio.run(servidor.crear(perfil).list_tools())}


def test_herramientas_por_perfil(home):
    assert _nombres("consulta") == CONSULTA
    assert _nombres("admin") == CONSULTA | ADMIN


def test_prompts(home):
    assert {p.name for p in asyncio.run(servidor.crear("admin").list_prompts())} == {"revision_de_carga", "informe_de_siempre", "contrastar_kb", "contrastar_con_mi_contexto"}
    assert {p.name for p in asyncio.run(servidor.crear("consulta").list_prompts())} == {"contrastar_con_mi_contexto"}


def test_error_llega_en_espanol(home):
    from mcp.server.mcpserver.exceptions import ToolError
    with pytest.raises(ToolError, match=r"ha caducado o no existe .*kortex\.py login"):
        asyncio.run(servidor.crear("consulta").call_tool("quien_soy", {}))


def test_herramienta_con_sesion_falsa(sesion):
    s, _, _ = sesion("ingesta", rutas={("GET", "/me"): Resp(200, {"label": "equipo2@ejemplo.test", "teams": [{"team_id": "T2", "name": "Equipo 2", "roles": ["reader"]}]})})
    srv = servidor.crear("consulta", fabrica=lambda cuenta: s)
    r = asyncio.run(srv.call_tool("quien_soy", {}))
    texto = r[0][0].text if isinstance(r, tuple) else r[0].text if isinstance(r, list) else str(r)
    assert "Equipo 2 (T2)" in texto
    assert "MCP: kortex · herramientas de consulta (perfil consulta)" in texto


def test_mcp_unico_elige_herramientas_por_el_login(home, monkeypatch):
    """23/11/2026: un solo MCP. Sin login de admin de la KB, solo consulta; con él, todas. El admin usa el login de ingesta del perfil
    consulta si no tiene uno propio. (Modo anterior al login único del 24/11/2026.)"""
    from conftest import cifrar
    from kortex_mcp import config as K, credenciales as C
    monkeypatch.setattr(K, "LOGIN_UNICO", False)
    assert C.perfil_efectivo() == "consulta"
    C.guardar("consulta", "ingesta", "equipo1@ejemplo.test", "x", cifrar=cifrar)
    assert C.perfil_efectivo() == "consulta" and C.perfil_de_cuenta("admin", "ingesta") == "consulta"
    C.guardar("admin", "kb", "admin", "y", cifrar=cifrar)
    assert C.perfil_efectivo() == "admin"
    assert _nombres(C.perfil_efectivo()) == CONSULTA | ADMIN
    C.guardar("admin", "ingesta", "otro@ejemplo.test", "z", cifrar=cifrar)
    assert C.perfil_de_cuenta("admin", "ingesta") == "admin" and C.perfil_de_cuenta("admin", "kb") == "admin"
    assert C.perfil_de_cuenta("consulta", "ingesta") == "consulta"


def test_registro_unico(home, capsys):
    from kortex_mcp.__main__ import main
    assert main(["registro"]) == 0
    out = capsys.readouterr().out
    assert "claude mcp add --transport http kortex http://localhost:8765/mcp" in out and "kortex-poc" not in out


def test_arranca_por_stdio_y_lista_herramientas(tmp_path):
    """Lo que hará Claude Code: lanzar el proceso y pedir la lista por el protocolo."""
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def lista(perfil):
        p = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).resolve().parents[1] / "kortex.py"), "--perfil", perfil],
                                  env={**os.environ, "KORTEX_HOME": str(tmp_path / "k")})
        async with stdio_client(p) as (r, w), ClientSession(r, w) as c:
            await c.initialize()
            return {t.name for t in (await c.list_tools()).tools}
    assert asyncio.run(lista("consulta")) == CONSULTA
    assert asyncio.run(lista("admin")) == CONSULTA | ADMIN
