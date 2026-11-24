import pytest
from conftest import Resp

from mcps.kortex_mcp.conocimiento import ingesta as I
from mcps.kortex_mcp.conocimiento.sesion import ErrorKortex, RutaNoDisponible

CONSULTA = {
    "pregunta": "¿Cómo se certifica una OT?", "documentos_consultados": 12, "coste_usd": 0.0003,
    "fragmentos": [
        {"n": 1, "doc_id": "doc_a", "documento": "Manual SIGMA.docx", "carpeta": "Obras", "version": 2, "ubicacion": "p. 4",
         "texto": "El contratista certifica la OT en la web.", "puntuacion": 0.81, "via": "documental"},
        {"n": 2, "doc_id": "doc_b", "documento": "Guía.pdf", "carpeta": "Obras", "version": 1, "ubicacion": "p. 9",
         "texto": "Certificación parcial.", "puntuacion": 0.55, "via": "kb"}],
    "kb": {"entidades": [{"id": "B-SISTEMA-sigma", "nombre": "SIGMA", "tipo": "SISTEMA", "ambitos": ["Redes"], "procesos_hpum": ["Gestionar obras"],
                          "documentos": 4, "descripcion": "Sistema de gestión de obras de red."}],
           "relaciones": [{"origen": "Contratistas", "tipo": "UTILIZA", "destino": "Web del contratista", "confianza": "ALTA",
                           "citas": [{"cita": "Web dedicada al contratista", "documento": "Inventario.xlsx"}]}],
           "transversal": [{"clase": "pasaje", "texto": "En otros equipos la certificación se valida en dos pasos.", "uso": "parafrasear, no citable ni atribuible a un documento"},
                           {"clase": "entidad", "nombre": "OT", "procedencia": "KB", "detalle": "Orden de trabajo", "uso": "parafrasear, no citable ni atribuible a un documento"}],
           "temas_transversales": ["Certificación", "Contratistas"]},
    "avisos": ["SIN_COINCIDENCIAS_CLARAS"]}


def test_consultar_cuerpo_y_salida(sesion):
    s, http, _ = sesion("ingesta", rutas={("POST", "/consulta"): Resp(200, CONSULTA)})
    out = I.consultar(s, "¿Cómo se certifica una OT?", colecciones=["col1"], k=8)
    assert http.llamadas[-1]["json"] == {"pregunta": "¿Cómo se certifica una OT?", "colecciones": ["col1"], "k": 8}
    assert "[1] Manual SIGMA.docx [doc_a] · Obras · v2 · p. 4" in out and "vía kb" in out and "vía documental" not in out
    assert "Conocimiento transversal de la KB" in out and "SIGMA [SISTEMA]" in out and "Contratistas ─ UTILIZA ▸ Web del contratista" in out
    assert "[pasaje] En otros equipos" in out and "Uso de lo transversal: parafrasear" in out
    assert "Temas transversales: Certificación · Contratistas" in out and "SIN_COINCIDENCIAS_CLARAS" in out


def test_consultar_notas_transversales_y_sin_notas(sesion):
    uso = "Conocimiento de contexto: parafrasear, no citable ni atribuible a un documento"
    r = {"pregunta": "¿Cómo se certifica una OT?", "documentos_consultados": 2, "fragmentos": [], "coste_usd": 0.0011,
         "kb": {"entidades": [], "relaciones": [], "transversal": [], "temas_transversales": [],
                "notas_transversales": [{"nota": "En otros equipos la certificación pasa por una doble validación.", "procedencia": "Kortex KB",
                                         "uso": uso}, {"nota": "", "uso": uso}]}}
    s, http, _ = sesion("ingesta", rutas={("POST", "/consulta"): Resp(200, r)})
    out = I.consultar(s, "¿Cómo se certifica una OT?")
    assert "notas" not in http.llamadas[-1]["json"]                                      # por defecto, el servidor decide (con notas)
    assert "Conocimiento transversal de la KB" in out and "Notas de otras fuentes de Kortex" in out
    assert "- [nota] En otros equipos la certificación pasa por una doble validación." in out and out.count("[nota]") == 1
    assert f"Uso de lo transversal: {uso}" in out and "No hay nada relevante" not in out
    I.consultar(s, "¿Cómo se certifica una OT?", notas=False)
    assert http.llamadas[-1]["json"] == {"pregunta": "¿Cómo se certifica una OT?", "notas": False}


def test_consultar_sin_kb_y_panorama(sesion):
    r = {"pregunta": "¿Qué información tienes?", "documentos_consultados": 3, "fragmentos": [], "kb": {},
         "panorama": {"texto": "Tienes 3 documentos de Obras.", "documentos": [{"doc_id": "doc_a", "documento": "Manual SIGMA.docx", "carpeta": "Obras"}]}}
    s, http, _ = sesion("ingesta", rutas={("POST", "/consulta"): Resp(200, r)})
    out = I.consultar(s, "¿Qué información tienes?", kb=False)
    assert http.llamadas[-1]["json"] == {"pregunta": "¿Qué información tienes?", "kb": False}
    assert "Panorama" in out and "Manual SIGMA.docx [doc_a]" in out and "No hay nada relevante" not in out


def test_consultar_ruta_no_desplegada(sesion):
    s, _, _ = sesion("ingesta")
    with pytest.raises(RutaNoDisponible, match="/consulta|consulta"):
        I.consultar(s, "x")


def _texto(llamada):
    desde = int(llamada["params"]["desde"])
    segs = [{"i": i, "tipo": "parrafo", "ubicacion": f"p. {i // 10 + 1}", "texto": f"Segmento {i}"} for i in range(desde, min(desde + 50, 120))]
    return Resp(200, {"doc_id": "doc_a", "nombre": "Manual.docx", "carpeta": "Obras", "version": 2, "total_segmentos": 120,
                      "segmentos": segs, "siguiente": desde + 50 if desde + 50 < 120 else None, "lectura": "COMPLETA"})


def test_leer_documento_paginado(sesion):
    s, http, _ = sesion("ingesta", rutas={("GET", "/documents/doc_a/texto"): _texto})
    p1 = I.leer_documento(s, "doc_a")
    assert "segmentos 0–49 de 120" in p1 and 'desde=50' in p1
    p3 = I.leer_documento(s, "doc_a", desde=100, max=50)
    assert http.llamadas[-1]["params"] == {"desde": "100", "max": "50"}
    assert "Segmento 119" in p3 and "(fin del documento)" in p3


def test_leer_documento_rango(sesion):
    s, http, _ = sesion("ingesta")
    with pytest.raises(ErrorKortex, match="1 a 200"):
        I.leer_documento(s, "doc_a", max=500)
    assert not http.llamadas


def test_documentos_y_equipo_unico(sesion):
    s, http, _ = sesion("ingesta", rutas={("GET", "/me"): Resp(200, {"teams": [{"team_id": "T2", "name": "Equipo 2", "roles": ["reader"]}]}),
                                         ("GET", "/teams/T2/documents"): Resp(200, {"items": [{"doc_id": "d1", "name": "a.pdf", "current_version": 1}], "total": 1, "next_cursor": None})})
    out = I.documentos(s, texto="a")
    assert "1. a.pdf [d1] · v1" in out
    assert http.llamadas[-1]["params"]["q"] == "a"
