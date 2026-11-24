import json

import pytest
from conftest import Resp

from kortex_mcp.kb import KB
from kortex_mcp.sesion import ErrorKortex

SERVIDA = {
    "campana_id": "KORTEX", "estado": "PROCESADA", "fecha": "2026-11-19T11:00:00Z",
    "entidades": [{"entidad_id": "E1", "nombre": "SIGMA", "tipo_id": "SISTEMA", "familia": "TECNO", "alias": ["Sistema de obras"], "documentos": ["D1"],
                   "menciones": [{"doc_id": "D1", "evidencia": {"cita": "SIGMA gestiona las obras"}}]},
                  {"entidad_id": "E2", "nombre": "Contratista", "tipo_id": "PROVEEDOR", "familia": "EXT", "documentos": ["D1"]}],
    "relaciones": [{"relacion_id": "REL-1", "origen": "E2", "destino": "E1", "tipo_id": "UTILIZA", "documentos": ["D1"], "confianza": "ALTA",
                    "evidencias": [{"cita": "El contratista usa SIGMA", "doc_id": "D1", "fuente": "CONTENIDO"}]}],
    "documentos": [{"doc_id": "D1", "nombre": "Manual.docx", "estado": "LEIDO"}],
    "grafo": {"nodos": [{"id": "E1", "clase": "ENTIDAD", "etiqueta": "SIGMA", "grupo": "APLICACION_SISTEMA", "tipo_id": "SISTEMA"},
                        {"id": "E2", "clase": "ENTIDAD", "etiqueta": "Contratista", "grupo": "OTRA", "tipo_id": "PROVEEDOR"},
                        {"id": "A1", "clase": "AMBITO", "etiqueta": "Redes"}, {"id": "D1", "clase": "DOCUMENTO", "etiqueta": "Manual.docx"}],
              "aristas": [{"id": "REL-1", "relacion_id": "REL-1", "clase": "RELACION_KB", "origen": "E2", "destino": "E1", "tipo_id": "UTILIZA", "documentos": ["D1"]},
                          {"id": "x1", "clase": "AMBITO_ENTIDAD", "origen": "E1", "destino": "A1"},
                          {"id": "x2", "clase": "MENCION", "origen": "D1", "destino": "E1"}]}}


def rutas_kb(huella="h1", servida=SERVIDA, extra=None):
    r = {("GET", "/campanas/KORTEX/servida"): Resp(200, {"url": "https://s3.example/servida.json", "huella": huella, "servida": {"huella": huella}}),
         ("GET", "servida.json"): Resp(200, servida),
         ("GET", "/campanas/KORTEX/estado"): Resp(200, {"estado": {"E1": {"estado": "APROBADA", "autor": "admin", "en": "2026-11-19T10:00:00Z"}}, "huella": huella, "resumen": {}}),
         ("GET", "/campanas/KORTEX/decisiones"): Resp(200, {"decisiones": []})}
    r.update(extra or {})
    return r


@pytest.fixture
def kb(sesion, reloj):
    def hacer(extra=None, huella="h1"):
        s, http, _ = sesion("kb", perfil="admin", rutas=rutas_kb(huella, extra=extra))
        return KB(s, http=http, reloj=reloj), http
    return hacer


def posts(http, sufijo):
    return [c for c in http.llamadas if c["metodo"] == "POST" and c["url"].endswith(sufijo)]


# ---------------------------------------------------------------------- decisiones: cuerpo exacto
def test_validar_un_id_guarda_directo_con_el_cuerpo_de_la_web(kb):
    k, http = kb({("POST", "/campanas/KORTEX/decisiones"): Resp(201, {"decision": {"sk": "2026-11-19T10:00:00Z#dec_0123456789ab", "accion": "APROBAR", "n_objetos": 1, "autor": "admin"}})})
    out = k.decidir("APROBAR", ["E1"], {}, "")
    assert posts(http, "/decisiones")[0]["json"] == {"accion": "APROBAR", "bloque": {"criterio": "ids", "valor": ["E1"]}, "parametros": {}, "motivo": ""}
    assert "dec_0123456789ab" in out and not posts(http, "/previsualizar")


def test_corregir_nombre_parametros_y_motivo(kb):
    k, http = kb({("POST", "/campanas/KORTEX/decisiones"): Resp(201, {"decision": {"sk": "s", "n_objetos": 1}})})
    with pytest.raises(ErrorKortex, match="motivo"):
        k.decidir("CORREGIR_NOMBRE", ["E1"], {"nombre": "SIGMA 2"}, "")
    k.decidir("CORREGIR_NOMBRE", ["E1"], {"nombre": "SIGMA 2"}, "nombre oficial")
    assert posts(http, "/decisiones")[0]["json"] == {"accion": "CORREGIR_NOMBRE", "bloque": {"criterio": "ids", "valor": ["E1"]},
                                                     "parametros": {"nombre": "SIGMA 2"}, "motivo": "nombre oficial"}


def test_accion_no_admitida(kb):
    k, _ = kb()
    with pytest.raises(ErrorKortex, match="operar_kb"):
        k.decidir("CREAR_RELACION", ["E1"], {}, "x")


# ---------------------------------------------------------------------- masivo en dos pasos
def test_bloque_en_dos_pasos(kb):
    pv = {"total": 2, "cambian": 2, "ya_estaban": 0, "por_clase": {"ENT": 2}, "muestra": ["SIGMA", "Contratista"], "accion": "RECHAZAR"}
    k, http = kb({("POST", "/campanas/KORTEX/previsualizar"): Resp(200, pv),
                  ("POST", "/campanas/KORTEX/decisiones"): Resp(201, {"decision": {"sk": "s1", "n_objetos": 2}})})
    out = k.decidir("RECHAZAR", ["E1", "E2"], {}, "no son de este ámbito")
    assert "No se ha cambiado nada" in out and not posts(http, "/decisiones")
    cuerpo = {"accion": "RECHAZAR", "bloque": {"criterio": "ids", "valor": ["E1", "E2"]}, "parametros": {}, "motivo": "no son de este ámbito"}
    assert posts(http, "/previsualizar")[0]["json"] == cuerpo
    codigo = out.split('confirmar="')[1].split('"')[0]
    k.decidir("APROBAR", ["OTRO"], {}, "", confirmar=codigo)                 # lo que vale es lo previsualizado, no los argumentos nuevos
    assert posts(http, "/decisiones")[0]["json"] == cuerpo
    with pytest.raises(ErrorKortex, match="no existe o ha caducado"):
        k.decidir("RECHAZAR", ["E1", "E2"], {}, "x", confirmar=codigo)       # un código sirve una vez


def test_codigo_caduca_y_es_de_su_operacion(kb, reloj):
    pv = {"total": 2, "cambian": 1, "ya_estaban": 1, "por_clase": {}, "muestra": []}
    k, _ = kb({("POST", "/campanas/KORTEX/previsualizar"): Resp(200, pv)})
    cod = k.decidir("APROBAR", ["E1", "E2"], {}, "").split('confirmar="')[1].split('"')[0]
    with pytest.raises(ErrorKortex, match="otra operación"):
        k.aplicar_propuestas([], confirmar=cod)
    cod = k.decidir("APROBAR", ["E1", "E2"], {}, "").split('confirmar="')[1].split('"')[0]
    reloj.t += 16 * 60
    with pytest.raises(ErrorKortex, match="caducado"):
        k.decidir("APROBAR", ["E1", "E2"], {}, "", confirmar=cod)


def test_bloque_que_no_cambia_nada_no_pide_confirmar(kb):
    k, _ = kb({("POST", "/campanas/KORTEX/previsualizar"): Resp(200, {"total": 1, "cambian": 0, "ya_estaban": 1, "por_clase": {}, "muestra": []})})
    assert "no hace falta confirmar" in k.decidir("APROBAR", None, {}, "", criterio="tipo", valor="SISTEMA")


def test_aplicar_propuestas_dos_pasos(kb):
    props = {"propuestas": [{"id": "P1", "caso": "DUPLICADOS", "accion": "FUSIONAR", "objetos": ["DUP|E1|E3"], "titulo": "Unir SIGMA", "confianza": 80}], "huella": "h1"}
    k, http = kb({("GET", "/campanas/KORTEX/consolidacion"): Resp(200, props),
                  ("POST", "/consolidacion/aplicar"): Resp(200, {"hechas": 1, "omitidas": [], "huella": "h2"})})
    out = k.aplicar_propuestas(["P1"])
    assert "Unir SIGMA" in out and not posts(http, "/aplicar")
    k.aplicar_propuestas(None, confirmar=out.split('confirmar="')[1].split('"')[0])
    assert posts(http, "/aplicar")[0]["json"] == {"propuestas": ["P1"], "seleccion": {}}


def test_quitar_documentos_es_destructivo_en_dos_pasos(kb):
    k, http = kb({("POST", "/ingesta/documentos"): Resp(202, {"en_curso": True})})
    out = k.documentos_kb(quitar=["D1"])
    assert "QUITARÍAN" in out and "Manual.docx" in out and not posts(http, "/ingesta/documentos")
    k.documentos_kb(confirmar=out.split('confirmar="')[1].split('"')[0])
    assert posts(http, "/ingesta/documentos")[0]["json"] == {"quitar": ["D1"], "incorporar": []}


# ---------------------------------------------------------------------- lectura
def test_servida_se_descarga_una_vez_por_huella(kb, home):
    k, http = kb()
    k.buscar_entidades("sigma")
    k.entidad("E1")
    assert sum(1 for c in http.llamadas if c["url"].endswith("servida.json")) == 1
    assert (home / "cache" / "servida_KORTEX_h1.json").exists()
    k2 = KB(k.s, http=http)                                             # otro proceso: tira de la caché en disco
    k2.servida()
    assert sum(1 for c in http.llamadas if c["url"].endswith("servida.json")) == 1


def test_buscar_y_entidad(kb):
    k, _ = kb()
    out = k.buscar_entidades("sistema de obras")
    assert "SIGMA [SISTEMA] (E1)" in out and "aprobada" in out and "Redes" in out
    e = k.entidad("E1")
    assert "Contratista ─ UTILIZA ▸ SIGMA [REL-1]" in e and "SIGMA gestiona las obras" in e


def test_por_que_relacion(kb):
    k, _ = kb()
    out = k.por_que("REL-1")
    assert "El contratista usa SIGMA" in out and "Manual.docx" in out


def test_lo_nuevo_desde_compara_fotos(sesion, reloj, home):
    nueva = json.loads(json.dumps(SERVIDA))
    nueva["entidades"].append({"entidad_id": "E9", "nombre": "Nueva", "tipo_id": "SISTEMA"})
    s, http, _ = sesion("kb", perfil="admin", rutas=rutas_kb("h1"))
    k = KB(s, http=http, reloj=reloj)
    k.servida()
    k.marcar_revision()
    http.rutas.update(rutas_kb("h2", servida=nueva))
    out = k.lo_nuevo_desde()
    assert "entidades: +1 / −0" in out and "Nueva (E9)" in out


def test_ficha_html_se_guarda(kb, tmp_path):
    k, _ = kb()
    out = k.ficha_html("E1", carpeta=str(tmp_path))
    f = tmp_path / "relaciones_SIGMA_KORTEX.html"
    assert str(f) in out and f.read_text(encoding="utf-8").startswith("<!doctype html>")
