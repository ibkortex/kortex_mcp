"""Fichas de conocimiento (entidad + relaciones): selección por confianza real, contexto, una sola revisión por relación, cobertura,
HTML, importación con todos los casos del procedimiento, plan con impactos y circuito por KB con HTTP falso. Nada toca la KB real."""
import json

import pytest
from conftest import Resp
from datos_fichas import servida

from kortex_mcp import fichas_revision as FR
from kortex_mcp.kb import KB
from kortex_mcp.sesion import ErrorKortex


def ix_de(D=None, rev=None):
    return FR.Indice(D or servida(), rev or {})


@pytest.fixture
def reg(tmp_path):
    return FR.Registro(tmp_path / "registro")


def lote(reg, tmp_path, modo="A", D=None, rev=None, **k):
    return FR.generar(ix_de(D, rev), modo, "h1", "KORTEX", reg, tmp_path / "salida", **k)


def ficha_con(fichas, obj):
    return next(m for m in fichas if any(i["objeto"] == obj for i in m["items"]))


def tarjeta(fichas, eid):
    return next(t for m in fichas for t in m["tarjetas"] if t["id"] == eid)


def respuestas(m, cambios=None, revisor=None, quitar=(), contexto=None, **extra):
    """El JSON que descargaría la ficha: cada elemento a revisar con la respuesta indicada {objeto: {respuesta, motivo…}}."""
    ents, rels = [], []
    for i in m["items"]:
        if i["objeto"] in quitar:
            continue
        c = {"respuesta": "SIN_REVISAR", "via": "individual", **(cambios or {}).get(i["objeto"], {})}
        x = {"firma": i["firma"], "en": "", **{k: c.get(k, "") for k in FR._CAMPOS}, "respuesta": c["respuesta"], "via": c["via"]}
        (ents if i["clase"] == "ENT" else rels).append({**x, ("entidad_id" if i["clase"] == "ENT" else "relacion_id"): i["objeto"]})
    j = {"formato": FR.FORMATO_RESPUESTAS, "ficha_id": m["ficha_id"], "modo": m["modo"], "huella": m["huella"], "sello": m["sello"], "campana": "KORTEX",
         "exportado_en": "2026-11-20T10:00:00Z", "revisor": revisor if revisor is not None else {"nombre": "María Pruebas", "correo": "maria@ejemplo.test", "ambito": "Redes"},
         "entidades": ents, "relaciones": rels, "contexto": contexto or []}
    j.update(extra)
    return json.dumps(j, ensure_ascii=False)


def importar(reg, texto, D=None, rev=None, huella="h1", usuario="admin"):
    return FR.importar(texto, reg, ix_de(D, rev), huella, usuario, reloj=lambda: "2026-11-20T11:00:00Z")


ACRED = "María verificada por correo corporativo del 20/11"


def estados(imp):
    return {i["objeto"]: (i["respuesta"], i["estado"]) for i in imp["items"]}


# ====================================================================== selección y modalidades
def test_dos_modalidades_sobre_entidades_y_relaciones():
    ix = ix_de()
    ea, ra, _, _ = FR.seleccionar(ix, "VALIDADO_AUTO")
    eb, rb, _, _ = FR.seleccionar(ix, "NO_VALIDADO_AUTO")
    assert ea == {"E-SIGMA", "E-SIRIO", "E-SAP", "E-SICO", "E-EQ"} and ra == {"REL-001", "REL-002", "REL-003", "REL-005", "REL-006", "REL-010"}
    assert {str(ix.ent[e]["confianza"]) for e in eb} == {"PROPUESTO", "EN_CONFLICTO", "None", "RARO_FUTURO"}       # nulos y futuros, a la B
    assert {str(ix.rel[r]["confianza"]) for r in rb} == {"PROPUESTO", "EN_CONFLICTO", "None", "RARO_FUTURO"}
    assert ea | eb == set(ix.ent) and not ea & eb and ra | rb == set(ix.rel) and not ra & rb
    with pytest.raises(FR.ErrorFicha, match="Modo no admitido"):
        FR.seleccionar(ix, None)                                       # sin modo solo vale con una entidad (ficha completa)
    e, r, f, _ = FR.seleccionar(ix, None, entidad="SIGMA")
    assert f["modo"] == "COMPLETA" and e == {"E-SIGMA"} and r == {"REL-001", "REL-002", "REL-004", "REL-011"}


def test_lo_confirmado_por_una_persona_no_vuelve_a_revision(reg, tmp_path):
    """Tras aplicar las respuestas: la KB servida marca lo aprobado como VALIDADO_PERSONA y /estado guarda la decisión. Ni la A ni la B
    lo vuelven a pedir; sale como contexto. Lo que queda pendiente (sin decisión) sí sigue saliendo."""
    D = servida()
    for e in D["entidades"]:
        if e["entidad_id"] in ("E-SIGMA", "E-CONTR"):
            e["confianza"] = "VALIDADO_PERSONA"                  # E-CONTR era PROPUESTO: no debe pasar a la ficha B
    for r in D["relaciones"]:
        if r["relacion_id"] in ("REL-001", "REL-004"):
            r["confianza"] = "VALIDADO_PERSONA"
    rev = {k: {"estado": "APROBADA", "autor": "admin", "en": "2026-11-23T10:00:00Z"} for k in ("E-SIGMA", "E-CONTR", "REL-001", "REL-004")}
    rev["REL-002"] = {"estado": "RECHAZADA", "autor": "admin", "en": "2026-11-23T10:00:00Z"}
    ix = ix_de(D, rev)
    ea, ra, _, _ = FR.seleccionar(ix, "A")
    eb, rb, _, _ = FR.seleccionar(ix, "B")
    hechos = {"E-SIGMA", "E-CONTR", "REL-001", "REL-004", "REL-002"}
    assert not (ea | ra | eb | rb) & hechos
    assert {"E-SIRIO", "REL-010"} <= ea | ra and {"E-SIRIO4P", "REL-011"} <= eb | rb       # lo pendiente sigue
    _, _, fa = lote(reg, tmp_path, "A", D, rev)
    t = tarjeta(fa, "E-SIRIO")
    assert "REL-001" in {i["objeto"] for i in t["ctx"]}                                  # aprobado: se ve como contexto
    e, r, _, _ = FR.seleccionar(ix, None, entidad="SIGMA")                               # la ficha completa lo enseña todo
    assert "E-SIGMA" in e and "REL-001" in r


def test_estados_nuevos_de_la_kb_servida(reg, tmp_path):
    """Con la KB servida ya en estados nuevos: A = PENDIENTE_VALIDAR; B = cualquier otro estado pendiente (también uno futuro); VALIDADO,
    nunca. Las etiquetas salen del catálogo que publica la KB."""
    D = servida()
    nuevos = {"E-SIGMA": "PENDIENTE_VALIDAR", "E-SIRIO": "VALIDADO", "E-CONTR": "SIN_CITA_LITERAL", "E-OT": "FUERA_DE_CATALOGO",
              "E-GAS": "ESTADO_DEL_FUTURO", "E-SAP": "PENDIENTE_VALIDAR"}
    for e in D["entidades"]:
        e["confianza"] = nuevos.get(e["entidad_id"], "SIN_CORROBORAR")
    D["catalogos"] = {"estados": {"estados": [{"id": "ESTADO_DEL_FUTURO", "etiqueta": "Estado del futuro"}, {"id": "SIN_CITA_LITERAL", "etiqueta": "Sin cita literal"}]}}
    ix = ix_de(D)
    ea, _, _, _ = FR.seleccionar(ix, "PENDIENTE_VALIDAR")
    eb, _, _, _ = FR.seleccionar(ix, "OTROS_ESTADOS")
    assert ea == {"E-SIGMA", "E-SAP"} and "E-SIRIO" not in eb and {"E-CONTR", "E-OT", "E-GAS"} <= eb
    assert FR.modo_de("A") == FR.modo_de("pendiente de validar") == FR.modo_de("VALIDADO_AUTO") == "PENDIENTE_VALIDAR"
    assert FR.modo_de("B") == FR.modo_de("resto") == FR.modo_de("NO_VALIDADO_AUTO") == "OTROS_ESTADOS"
    _, _, fb = lote(reg, tmp_path, "B", D)
    h = "".join(open(x["fichero"], encoding="utf-8").read() for x in fb)
    assert "estado del futuro" in h and "sin cita literal" in h and "fuera del catálogo" in h
    assert FR.legado("VALIDADO_AUTO") == "PENDIENTE_VALIDAR" and FR.legado("VALIDADO_PERSONA") == "VALIDADO"
    assert FR.legado("PROPUESTO", ["sin cita literal exacta"]) == "SIN_CITA_LITERAL" and FR.legado("ESTADO_DEL_FUTURO") == "ESTADO_DEL_FUTURO"


def test_validacion_no_se_confunde_con_confianza():
    D = servida()
    D["entidades"][0]["estado"] = "CANDIDATA"
    D["entidades"][0]["confianza"] = "PROPUESTO"
    ea, _, _, _ = FR.seleccionar(ix_de(D), "A")
    assert "E-SIGMA" not in ea


def test_filtros_ambito_y_entidad():
    ix = ix_de()
    e, r, f, _ = FR.seleccionar(ix, "B", ambito="gas")
    assert f["ambito"] == "Gas" and e == {"E-GAS", "E-KPI"} and r == {"REL-007", "REL-009"}
    e, r, f, _ = FR.seleccionar(ix, "A", entidad="SIRIO")
    assert f["entidades"] == ["SIRIO", "SIRIO 4P"] and e == {"E-SIRIO"} and r == {"REL-001", "REL-003", "REL-010"}
    with pytest.raises(FR.ErrorFicha, match="ningún ámbito"):
        FR.seleccionar(ix, "A", ambito="Marte")
    with pytest.raises(FR.ErrorFicha, match="ninguna entidad"):
        FR.seleccionar(ix, "A", entidad="NOEXISTE")


# ====================================================================== tarjetas: contexto completo y una sola revisión por relación
def test_caso1_entidad_validada_con_todas_sus_relaciones_validadas(reg, tmp_path):
    _, _, fa = lote(reg, tmp_path, "A")
    t = tarjeta(fa, "E-SIRIO")
    revisa = {i["objeto"] for i in t["rels"]} | {i["objeto"] for i in t["ref"]}
    assert t["revision"] and revisa == {"REL-001", "REL-003", "REL-010"} and not t["ctx"]


def test_caso2_y_5_entidad_validada_con_relaciones_propuestas_entrantes_y_salientes(reg, tmp_path):
    _, _, fa = lote(reg, tmp_path, "A")
    t = tarjeta(fa, "E-SIGMA")
    assert t["revision"] and {i["objeto"] for i in t["ctx"]} == {"REL-004", "REL-011"}           # las PROPUESTO, como contexto
    assert any(i["o"]["id"] != "E-SIGMA" for i in t["ctx"]) and any(i["o"]["id"] == "E-SIGMA" for i in t["rels"] + t["ref"])  # entra y sale
    _, _, fb = lote(reg, tmp_path, "B")
    sg = tarjeta(fb, "E-SIGMA")                                         # en la B SIGMA aparece como CONTEXTO para revisar su relación con SICO
    assert not sg["revision"] and [i["objeto"] for i in sg["rels"]] == ["REL-011"]
    assert {i["objeto"] for i in sg["ctx"]} == {"REL-001", "REL-002"}
    assert "E-SIGMA" in ficha_con(fb, "REL-011")["contexto"] and "E-SIGMA" not in [i["objeto"] for m in fb for i in m["items"]]


def test_caso3_entidad_propuesta_con_relacion_validada(reg, tmp_path):
    _, _, fa = lote(reg, tmp_path, "A")
    _, _, fb = lote(reg, tmp_path, "B")
    assert "E-SIRIO4P" not in [i["objeto"] for m in fa for i in m["items"]] and "REL-003" in [i["objeto"] for m in fa for i in m["items"]]
    t = tarjeta(fb, "E-SIRIO4P")
    assert t["revision"] and [i["objeto"] for i in t["ctx"]] == ["REL-003"]


def test_caso4_entidad_propuesta_sin_relaciones(reg, tmp_path):
    _, cob, fb = lote(reg, tmp_path, "B")
    t = tarjeta(fb, "E-HUERFANA")
    assert t["revision"] and not (t["rels"] or t["ref"] or t["ctx"]) and cob["entidades_sin_relaciones_a_revisar"] >= 1


def test_caso6_relacion_compartida_se_revisa_una_vez(reg, tmp_path):
    _, _, fa = lote(reg, tmp_path, "A")
    donde = [t["id"] for m in fa for t in m["tarjetas"] if "REL-001" in [i["objeto"] for i in t["rels"]]]
    refs = [t["id"] for m in fa for t in m["tarjetas"] if "REL-001" in [i["objeto"] for i in t["ref"]]]
    assert len(donde) == 1 and len(refs) == 1 and set(donde + refs) == {"E-SIGMA", "E-SIRIO"}
    assert [i["objeto"] for m in fa for i in m["items"]].count("REL-001") == 1


def test_caso7_posible_duplicado_visible(reg, tmp_path):
    _, _, fa = lote(reg, tmp_path, "A")
    e = tarjeta(fa, "E-SAP")["ent"]
    assert [d["nombre"] for d in e["duplicados"]] == ["SAP ERP"] and e["duplicados"][0]["id"] == "DUP|E-SAP|E-SAP2"


@pytest.mark.parametrize("modo", ["A", "B"])
@pytest.mark.parametrize("extra", [0, 30, 80, 200])
def test_cobertura_sin_perdidas_ni_repeticiones(reg, tmp_path, modo, extra):
    D = servida(extra)
    ix = ix_de(D)
    carpeta, cob, fichas = lote(reg, tmp_path, modo, D)
    ents, rels, _, _ = FR.seleccionar(ix, modo)
    es = [i["objeto"] for m in fichas for i in m["items"] if i["clase"] == "ENT"]
    rs = [i["objeto"] for m in fichas for i in m["items"] if i["clase"] == "REL"]
    assert sorted(es) == sorted(ents) and sorted(rs) == sorted(rels)
    assert cob["entidades"]["perdidas"] == cob["relaciones"]["perdidas"] == cob["entidades"]["repetidas"] == cob["relaciones"]["repetidas"] == []
    tarjetas = [t["id"] for m in fichas for t in m["tarjetas"]]
    assert len(tarjetas) == len(set(tarjetas))                                    # una entidad no se parte entre fichas
    for m in fichas:
        assert len(m["items"]) <= FR.MAX_POR_FICHA or len(m["tarjetas"]) == 1
        for t in m["tarjetas"]:                                                    # lo que se revisa en una tarjeta toca a su entidad
            assert all(t["id"] in (i["o"]["id"], i["d"]["id"]) for i in t["rels"] + t["ref"] + t["ctx"])
    assert (carpeta / "indice.html").exists() and json.loads((carpeta / "cobertura.json").read_text(encoding="utf-8"))["relaciones"]["perdidas"] == []
    vistas_ctx = {i["objeto"] for m in fichas for t in m["tarjetas"] for i in t["ctx"]}
    assert not vistas_ctx & set(rels)                                              # lo que se revisa no se enseña además como contexto


def test_sin_nada_no_genera(reg, tmp_path):
    with pytest.raises(FR.ErrorFicha, match="No hay entidades ni relaciones"):
        lote(reg, tmp_path, "A", ambito="Gas")


# ====================================================================== HTML
def test_html_simple_y_escapado(reg, tmp_path):
    _, _, fa = lote(reg, tmp_path, "A")
    m = ficha_con(fa, "E-SIGMA")
    h = open(m["fichero"], encoding="utf-8").read()
    for txt in ("Kortex · Validación funcional", m["ficha_id"], "KB KORTEX versión h1", "nadie las ha confirmado todavía", "Validación funcional · SIGMA",
                "Kortex ha identificado lo siguiente:", "«SIGMA» se identifica como sistema.", "SIGMA se integra con SIRIO.", "¿Es correcta esta representación?",
                "Sí, es correcta", "Parcialmente, hay que corregir algo", "No es correcta", "No tengo información suficiente", "No es de mi ámbito",
                "Indica qué relación cambiarías o qué falta…", "Señalar excepción", "SIGMA envía las obras a SIRIO", "Manual de obras.docx · página 3",
                "Esta sí es correcta", "El nombre no es correcto", "El tipo no es correcto", "Es la misma que otra entidad", "La dirección está al revés",
                "(contexto: no se responde aquí)", "se revisa en"):
        assert txt in h, txt
    assert h.count('class="conj"') == len(m["tarjetas"]) and h.count('<li class="linea" data-obj=') == len(m["items"])
    _, _, fb = lote(reg, tmp_path, "B")
    hb = "".join(open(x["fichero"], encoding="utf-8").read() for x in fb)
    assert "Contratista &lt;b&gt; utiliza SIGMA." in hb and "sin corroborar" in hb and "en conflicto" in hb and "no cumple todos los controles automáticos" in hb
    assert "<script>alert(1)</script>" not in hb and "&lt;script&gt;alert(1)&lt;/script&gt;" in hb
    datos = json.loads(hb.split('<script type="application/json" id="kx-datos">')[1].split("</script>")[0])
    assert datos["formato_respuestas"] == FR.FORMATO_RESPUESTAS and all(set(i) == {"objeto", "clase", "firma", "tarjeta"} for i in datos["items"])


def test_html_muestra_revision_humana(reg, tmp_path):
    rev = {"REL-001": {"estado": "APROBADA", "autor": "revisora", "en": "2026-11-19T10:00:00Z"}}
    _, _, fa = lote(reg, tmp_path, "A", rev=rev)
    assert "Aprobada por revisora el 2026-11-19" in "".join(open(x["fichero"], encoding="utf-8").read() for x in fa)


# ====================================================================== importación y plan (casos 8–12)
def test_caso8_correccion_de_nombre_y_tipo_con_impacto(reg, tmp_path):
    _, _, fa = lote(reg, tmp_path, "A")
    m = ficha_con(fa, "E-SIGMA")
    otra = next(i["objeto"] for i in m["items"] if i["clase"] == "ENT" and i["objeto"] != "E-SIGMA")
    imp = importar(reg, respuestas(m, {"E-SIGMA": {"respuesta": "CORREGIR_NOMBRE", "nombre_nuevo": "SIGMA Distribuidora"},
                                       otra: {"respuesta": "CORREGIR_TIPO", "tipo_nuevo": "APLICACION" if otra != "E-SAP" else "MODULO"}}))
    p = FR.plan(imp, ix_de(), acreditacion=ACRED)
    nom = next(d for d in p["decisiones"] if d["accion"] == "CORREGIR_NOMBRE")
    assert nom["bloque"]["valor"] == ["E-SIGMA"] and nom["parametros"] == {"nombre": "SIGMA Distribuidora"} and len(nom["motivo"]) >= 3
    tip = next(d for d in p["decisiones"] if d["accion"] == "CORREGIR_TIPO")
    assert tip["bloque"]["valor"] == [otra]
    imp_sigma = next(x for x in p["filas"]["impactos"] if x["objeto"] == "E-SIGMA")
    assert imp_sigma["n"] == 4 and "SIGMA Distribuidora" in imp_sigma["accion"]                      # se ve en sus 4 relaciones, que no cambian de estado
    assert not [d for d in p["decisiones"] if any(v.startswith("REL-") for v in d["bloque"]["valor"])]
    mal = importar(reg, respuestas(m, {"E-SIGMA": {"respuesta": "CORREGIR_TIPO", "tipo_nuevo": "PROCESO_HPUM"}}, revisor={"nombre": "Otra", "correo": "", "ambito": ""}))
    pm = FR.plan(mal, ix_de(), acreditacion=ACRED)
    assert not pm["decisiones"] and "no es del catálogo" in pm["filas"]["excluidas"][0]["motivo_exclusion"]


def test_caso9_rechazo_de_relacion_sin_rechazar_la_entidad(reg, tmp_path):
    _, _, fa = lote(reg, tmp_path, "A")
    m = ficha_con(fa, "REL-002")
    imp = importar(reg, respuestas(m, {"E-SIGMA": {"respuesta": "CORRECTA"}, "REL-002": {"respuesta": "INCORRECTA", "motivo": "ya no se integran"}}))
    p = FR.plan(imp, ix_de(), acreditacion=ACRED)
    acc = {(d["accion"], tuple(d["bloque"]["valor"])) for d in p["decisiones"]}
    assert ("APROBAR", ("E-SIGMA",)) in acc and ("RECHAZAR", ("REL-002",)) in acc
    assert not any(a == "RECHAZAR" and "E-SIGMA" in v for a, v in acc)


def test_caso10_confirmar_entidad_no_confirma_sus_relaciones(reg, tmp_path):
    _, _, fa = lote(reg, tmp_path, "A")
    m = ficha_con(fa, "E-SIGMA")
    p = FR.plan(importar(reg, respuestas(m, {"E-SIGMA": {"respuesta": "CORRECTA"}})), ix_de(), acreditacion=ACRED)
    assert [d["bloque"]["valor"] for d in p["decisiones"]] == [["E-SIGMA"]]


def test_caso11_respuestas_parciales(reg, tmp_path):
    _, _, fa = lote(reg, tmp_path, "A")
    m = ficha_con(fa, "E-SIGMA")
    imp = importar(reg, respuestas(m, {"E-SIGMA": {"respuesta": "CORRECTA"}, "REL-001": {"respuesta": "PARCIAL", "motivo": "solo las obras de BT"}},
                                   quitar=("REL-002",)))
    est = estados(imp)
    assert est["REL-002"] == ("SIN_REVISAR", "OK") and any("incompleta" in a for a in imp["avisos"])
    p = FR.plan(imp, ix_de(), acreditacion=ACRED)
    assert [x["objeto"] for x in p["filas"]["por_interpretar"]] == ["REL-001"]                 # matiz: lo traduce Claude a una operación
    assert p["filas"]["por_interpretar"][0]["comentario"] == "solo las obras de BT"
    assert all("REL-001" not in d["bloque"]["valor"] for d in p["decisiones"])
    assert not any(o.get("relacion") == "REL-001" or "REL-001" in (o.get("ids") or []) for o in p["operaciones"])


def test_caso12_conflictos_y_versiones_obsoletas(reg, tmp_path):
    _, _, fa = lote(reg, tmp_path, "A")
    m = ficha_con(fa, "E-SIGMA")
    a = importar(reg, respuestas(m, {"E-SIGMA": {"respuesta": "CORRECTA"}, "REL-001": {"respuesta": "CORRECTA"}}))
    reg.guardar_importacion(a)
    b = importar(reg, respuestas(m, {"E-SIGMA": {"respuesta": "INCORRECTA", "motivo": "no existe"}, "REL-001": {"respuesta": "CORRECTA"}},
                                 revisor={"nombre": "Persona Pruebas", "correo": "pruebas@ejemplo.test", "ambito": "Sistemas"}))
    est = {i["objeto"]: i for i in b["items"]}
    assert est["E-SIGMA"]["estado"] == "CONFLICTO" and "choca con la revisión " + a["importacion_id"] in est["E-SIGMA"]["notas"][0]
    assert est["REL-001"]["estado"] == "OK" and "coincide con la revisión" in est["REL-001"]["notas"][0]
    D = servida()
    next(e for e in D["entidades"] if e["entidad_id"] == "E-SIGMA")["nombre"] = "SIGMA 2"              # la entidad cambió en la KB
    D["relaciones"] = [r for r in D["relaciones"] if r["relacion_id"] != "REL-001"]                   # la relación desapareció
    c = importar(reg, respuestas(m, {"E-SIGMA": {"respuesta": "CORRECTA"}, "REL-001": {"respuesta": "CORRECTA"}}, revisor={"nombre": "Ane", "correo": "", "ambito": ""}),
                 D=D, huella="h2")
    assert estados(c)["E-SIGMA"] == ("CORRECTA", "OBSOLETA") and estados(c)["REL-001"] == ("CORRECTA", "DESAPARECIDA")
    rev = {"REL-002": {"estado": "RECHAZADA", "autor": "revisora", "en": "2099-01-01T00:00:00Z"}}
    d = importar(reg, respuestas(m, {"REL-002": {"respuesta": "CORRECTA"}}, revisor={"nombre": "Iker", "correo": "", "ambito": ""}), rev=rev)
    assert estados(d)["REL-002"] == ("CORRECTA", "CONFLICTO")
    assert FR.plan(d, ix_de(rev=rev), acreditacion=ACRED)["decisiones"] == []


def test_duplicado_propuesto_no_fusiona_solo(reg, tmp_path):
    _, _, fa = lote(reg, tmp_path, "A")
    m = ficha_con(fa, "E-SAP")
    imp = importar(reg, respuestas(m, {"E-SAP": {"respuesta": "DUPLICADO", "duplicado_de": "SAP ERP"}}))
    p = FR.plan(imp, ix_de(), acreditacion=ACRED)
    assert p["decisiones"] == [] and p["filas"]["fusionar"][0]["dup_id"] == "DUP|E-SAP|E-SAP2"
    assert p["operaciones"] == [{"op": "FUSIONAR_ENTIDADES", "conservar": "E-SAP2", "absorber": ["E-SAP"], "motivo": p["operaciones"][0]["motivo"]}]
    assert any(x["objeto"] == "E-SAP" and "se fusiona en" in x["accion"] for x in p["filas"]["impactos"])


def test_rechazar_entidad_avisa_de_sus_relaciones(reg, tmp_path):
    _, _, fa = lote(reg, tmp_path, "A")
    m = ficha_con(fa, "E-SAP")
    p = FR.plan(importar(reg, respuestas(m, {"E-SAP": {"respuesta": "INCORRECTA", "motivo": "no es un sistema de Redes"}})), ix_de(), acreditacion=ACRED)
    assert [d["bloque"]["valor"] for d in p["decisiones"] if d["accion"] == "RECHAZAR"] == [["E-SAP"]]
    x = next(x for x in p["filas"]["impactos"] if x["objeto"] == "E-SAP")
    assert "NO se rechazan" in x["accion"] and x["n"] == 3


def test_observacion_de_contexto(reg, tmp_path):
    _, _, fb = lote(reg, tmp_path, "B")
    m = ficha_con(fb, "REL-011")
    imp = importar(reg, respuestas(m, contexto=[{"objeto": "E-SIGMA", "texto": "SIGMA es de Distribuidora, no de Redes España"}]))
    p = FR.plan(imp, ix_de(), acreditacion=ACRED)
    assert p["filas"]["observaciones_contexto"][0]["texto"].startswith("SIGMA es de Distribuidora") and p["decisiones"] == []
    with pytest.raises(FR.ErrorFicha, match="contexto"):
        importar(reg, respuestas(m, contexto=[{"objeto": "E-HUERFANA-NO", "texto": "x"}], revisor={"nombre": "Z", "correo": "", "ambito": ""}))


def test_respuesta_de_tarjeta_y_aportacion(reg, tmp_path):
    _, _, fa = lote(reg, tmp_path, "A")
    m = ficha_con(fa, "E-SIGMA")
    j = json.loads(respuestas(m, {"E-SIGMA": {"respuesta": "CORRECTA", "via": "grupo"}}))
    j["conjuntos"] = [{"seccion": "E-SIGMA", "respuesta": "SI", "comentario": "", "aportacion": "SIGMA también alimenta el cuadro de mando"}]
    imp = importar(reg, json.dumps(j))
    assert any("cuadro de mando" in x["aportacion"] for x in FR.plan(imp, ix_de(), acreditacion=ACRED)["filas"]["aportaciones"])
    j["conjuntos"] = [{"seccion": "OTRA", "respuesta": "SI"}]
    with pytest.raises(FR.ErrorFicha, match="conjunto"):
        importar(reg, json.dumps(j))


@pytest.mark.parametrize("trampa, mensaje", [
    (lambda j: j["relaciones"].append({**j["relaciones"][0], "relacion_id": "REL-004"}), "no se revisa en esta ficha"),
    (lambda j: j["entidades"].append({**j["entidades"][0], "entidad_id": "REL-001"}), "no se revisa en esta ficha"),   # una relación como entidad
    (lambda j: j["relaciones"][0].update(firma="0000000000000000"), "la firma"),
    (lambda j: j.update(sello="f" * 32), "sello"),
    (lambda j: j.update(huella="otra"), "«huella»"),
    (lambda j: j["entidades"][0].update(respuesta="OTRO_TIPO"), "respuesta no válida"),                              # opción de relación en una entidad
    (lambda j: j["relaciones"].append(dict(j["relaciones"][0])), "dos veces"),
])
def test_archivo_manipulado_se_rechaza_entero(reg, tmp_path, trampa, mensaje):
    _, _, fa = lote(reg, tmp_path, "A")
    j = json.loads(respuestas(ficha_con(fa, "E-SIGMA"), {"E-SIGMA": {"respuesta": "CORRECTA"}}))
    trampa(j)
    with pytest.raises(FR.ErrorFicha, match=mensaje):
        importar(reg, json.dumps(j))
    assert reg.importaciones() == []


def test_ficha_desconocida_otro_puesto_y_duplicado(reg, tmp_path):
    _, _, fa = lote(reg, tmp_path, "A")
    m = ficha_con(fa, "E-SIGMA")
    j = json.loads(respuestas(m))
    j["ficha_id"] = "FR-A-20261120-deadbeef"
    with pytest.raises(FR.ErrorFicha, match="no la generó este MCP"):
        importar(reg, json.dumps(j))
    with pytest.raises(FR.ErrorFicha, match="formato"):
        importar(reg, json.dumps({"hola": 1}))
    otro = FR.Registro(tmp_path / "otro_puesto")
    otro.guardar_ficha(reg.ficha(m["ficha_id"]))
    with pytest.raises(FR.ErrorFicha, match="sello"):
        importar(otro, respuestas(m))
    t = respuestas(m, {"E-SIGMA": {"respuesta": "CORRECTA"}})
    reg.guardar_importacion(importar(reg, t))
    with pytest.raises(FR.ErrorFicha, match="ya se importó"):
        importar(reg, t)


def test_sin_acreditar_y_ambito_acreditado(reg, tmp_path):
    _, _, fa = lote(reg, tmp_path, "A")
    m = ficha_con(fa, "E-SIGMA")
    imp = importar(reg, respuestas(m, {"E-SIGMA": {"respuesta": "CORRECTA"}, "REL-001": {"respuesta": "INCORRECTA", "motivo": "no"}}))
    assert FR.plan(imp, ix_de())["decisiones"] == [] and FR.plan(imp, ix_de(), acreditacion="corto")["decisiones"] == []
    assert len(FR.plan(imp, ix_de())["filas"]["pendiente_acreditar"]) == 2
    assert FR.plan(imp, ix_de(), acreditacion=ACRED, ambito_acreditado="Gas")["decisiones"] == []
    assert len(FR.plan(imp, ix_de(), acreditacion=ACRED, ambito_acreditado="Redes")["decisiones"]) == 2


def test_formato_de_la_primera_version_sigue_importando(reg, tmp_path):
    ix = ix_de()
    r = ix.rel["REL-001"]
    items = [{"relacion_id": "REL-001", "firma": FR.firma(r), "confianza": "VALIDADO_AUTO", "ambitos": ["Redes"], "seccion": "x", "revision_estado": None}]
    fid = "FR-A-20261120-0000abcd"
    reg.guardar_ficha({"ficha_id": fid, "lote": "A_v1", "modo": "VALIDADO_AUTO", "huella": "h1", "generada": "2026-11-20T09:00:00Z", "titulo": "v1",
                       "fichero": "x.html", "secciones": [{"id": "x", "titulo": "x"}], "items": items, "sello": FR.sello(reg.clave(), fid, "h1", "VALIDADO_AUTO", items)})
    j = {"formato": FR.FORMATO_RESPUESTAS_V1, "ficha_id": fid, "modo": "VALIDADO_AUTO", "huella": "h1", "sello": reg.ficha(fid)["sello"],
         "revisor": {"nombre": "Antigua"}, "respuestas": [{"relacion_id": "REL-001", "firma": FR.firma(r), "respuesta": "CORRECTA"}]}
    imp = importar(reg, json.dumps(j))
    assert estados(imp) == {"REL-001": ("CORRECTA", "OK")}
    assert FR.plan(imp, ix, acreditacion=ACRED)["decisiones"][0]["bloque"]["valor"] == ["REL-001"]


# ====================================================================== a través de KB (HTTP falso): ninguna escritura hasta confirmar
def rutas(D, huella="h1"):
    return {("GET", "/campanas/KORTEX/servida"): Resp(200, {"url": "https://s3.example/servida.json", "huella": huella}),
            ("GET", "servida.json"): Resp(200, D),
            ("GET", "/campanas/KORTEX/estado"): Resp(200, {"estado": {}, "huella": huella, "resumen": {}}),
            ("GET", "/campanas/KORTEX/decisiones"): Resp(200, {"decisiones": []}),
            ("POST", "/campanas/KORTEX/decisiones"): lambda ll: Resp(201, {"decision": {"sk": "2026-11-20T12:00:00Z#dec_0123456789ab", "accion": ll["json"]["accion"],
                                                                                       "n_objetos": len(ll["json"]["bloque"]["valor"]), "autor": "admin"}}),
            ("POST", "/campanas/KORTEX/operaciones"): _operaciones_falsas}


def _operaciones_falsas(ll):
    """API de operaciones falsa: previsualiza (sin escribir) o «guarda» una decisión por operación."""
    ops = ll["json"]["operaciones"]
    if ll["json"].get("previsualizar", True):
        return Resp(200, {"resumen": {"relaciones_retiradas": sum(o["op"] == "RECHAZAR" for o in ops)}, "huella_antes": "h1", "huella_despues": "h2",
                          "cambios": [{"texto": f"{o['op']} {o.get('ids') or o.get('relacion')}"} for o in ops], "total_cambios": len(ops),
                          "decisiones": [{"accion": o["op"]} for o in ops]})
    return Resp(201, {"lote": "lote_0123456789ab", "autor": "admin", "huella": "h2",
                      "hechas": [{"sk": f"2026-11-20T12:00:0{n}Z#dec_0123456789ab", "accion": o["op"], "operacion": n, "objetos": o.get("ids") or [o.get("relacion")]}
                                 for n, o in enumerate(ops, 1)]})


@pytest.fixture
def kbf(sesion, reloj):
    def hacer(D=None):
        s, http, _ = sesion("kb", perfil="admin", rutas=rutas(D or servida()))
        return KB(s, http=http, reloj=reloj), http
    return hacer


def test_circuito_completo_por_kb(kbf, tmp_path):
    k, http = kbf()
    out = k.generar_fichas_revision("VALIDADO_AUTO", carpeta=str(tmp_path / "f"))
    assert "A revisar: 5 entidades" in out and "y 6 relaciones" in out and "perdidas 0 entidades y 0 relaciones" in out
    reg = k._registro()
    m = next(f for f in reg.fichas() if any(i["objeto"] == "E-SIGMA" for i in FR.items_registro(f)))
    m = {**m, "items": FR.items_registro(m)}
    f = tmp_path / f"respuestas_{m['ficha_id']}.json"
    f.write_text(respuestas(m, {"E-SIGMA": {"respuesta": "CORRECTA"}, "REL-002": {"respuesta": "INCORRECTA", "motivo": "no se integran"}}), encoding="utf-8")
    inf = k.importar_respuestas_ficha([str(f)])
    assert "Revisor DECLARADO en el fichero (sin acreditar): María Pruebas" in inf and "Importado por (usuario autenticado): admin" in inf
    assert "Entidades: confirmadas 1" in inf and "Relaciones: confirmadas 0" in inf and "Nada se ha cambiado en la KB" in inf
    iid = reg.importaciones()[0]["importacion_id"]
    assert "No hay operaciones que guardar: falta acreditar al revisor" in k.previsualizar_correcciones_ficha(iid)
    pv = k.previsualizar_correcciones_ficha(iid, acreditacion=ACRED)
    assert "Se validan (lo confirma el revisor): 1" in pv and "Se rechazan" in pv and "relaciones retiradas 1" in pv
    escritos = lambda: [c["json"] for c in http.llamadas if c["metodo"] == "POST" and (c["url"].endswith("/decisiones") or (c["json"] or {}).get("previsualizar") is False)]   # noqa: E731
    assert not escritos()                                               # previsualizar no escribe
    cod = pv.split('confirmar="')[1].split('"')[0]
    hecho = k.aplicar_correcciones_ficha(cod)
    (cuerpo,) = escritos()
    assert [(o["op"], o["ids"]) for o in cuerpo["operaciones"]] == [("VALIDAR", ["E-SIGMA"]), ("RECHAZAR", ["REL-002"])]
    assert "Fichas " + iid in cuerpo["motivo"] and cuerpo["origen"]["importaciones"] == iid
    assert "lote_0123456789ab" in hecho and "deshacer(sk=…)" in hecho and reg.importacion(iid)["estado"] == "APLICADA"
    with pytest.raises(ErrorKortex, match="acredítalo"):
        k.previsualizar_correcciones_ficha(iid, operaciones_adicionales=[{"op": "INVERTIR_RELACION", "relacion": "REL-001"}])
    pv2 = k.previsualizar_correcciones_ficha(iid, acreditacion=ACRED, operaciones_adicionales=[{"op": "CREAR_RELACION", "origen": "E-SIGMA", "tipo_id": "PRODUCE",
                                                                                               "destino": "E-SAP", "_lectura": "x"}])
    assert "Incluye 1 operaciones interpretadas" in pv2
    ult = [c["json"] for c in http.llamadas if c["metodo"] == "POST" and c["url"].endswith("/operaciones")][-1]
    assert ult["operaciones"][-1] == {"op": "CREAR_RELACION", "origen": "E-SIGMA", "tipo_id": "PRODUCE", "destino": "E-SAP", "motivo": "según el comentario del revisor"}
    with pytest.raises(ErrorKortex, match="no existe o ha caducado"):
        k.aplicar_correcciones_ficha(cod)
    assert "entidades confirmadas 1" in k.fichas_revision()


def test_kb_ficha_completa_y_errores(kbf, tmp_path):
    k, _ = kbf()
    out = k.generar_fichas_revision(None, entidad="SIGMA", carpeta=str(tmp_path / "f"))
    assert "Ficha completa" in out and "A revisar: 1 entidades" in out and "y 4 relaciones" in out
    with pytest.raises(ErrorKortex, match="Modo no admitido"):
        k.generar_fichas_revision("TODO")
    with pytest.raises(ErrorKortex, match="Indica el fichero"):
        k.importar_respuestas_ficha([])
    with pytest.raises(ErrorKortex, match="No hay ninguna importación"):
        k.previsualizar_correcciones_ficha("IMP-00000000")


def test_direccion_y_otro_tipo_se_aplican_y_el_matiz_trae_sugerencias(reg, tmp_path):
    """23/11/2026: dirección al revés → INVERTIR_RELACION; otro tipo → CORREGIR_RELACION; «no es con SIRIO sino con SAP ERP» → sugerencias."""
    _, _, fa = lote(reg, tmp_path, "A")
    m = ficha_con(fa, "E-SIGMA")
    imp = importar(reg, respuestas(m, {"E-SIGMA": {"respuesta": "CORRECTA"},
                                       "REL-001": {"respuesta": "DIRECCION", "motivo": "es SIRIO quien manda a SIGMA"},
                                       "REL-002": {"respuesta": "OTRO_TIPO", "tipo_nuevo": "PRODUCE", "motivo": "le genera los costes"}}))
    p = FR.plan(imp, ix_de(), acreditacion=ACRED)
    ops = {o["op"]: o for o in p["operaciones"]}
    assert ops["INVERTIR_RELACION"]["relacion"] == "REL-001" and "es SIRIO quien manda" in ops["INVERTIR_RELACION"]["motivo"]
    assert (ops["CORREGIR_RELACION"]["relacion"], ops["CORREGIR_RELACION"]["tipo_id"]) == ("REL-002", "PRODUCE")
    assert ops["VALIDAR"]["ids"] == ["E-SIGMA"]
    imp2 = importar(reg, respuestas(m, {"REL-001": {"respuesta": "INCORRECTA", "motivo": "SIGMA no se integra con SIRIO, se integra con SAP ERP"}},
                                    revisor={"nombre": "Otra", "correo": "", "ambito": ""}))
    p2 = FR.plan(imp2, ix_de(), acreditacion=ACRED)
    assert [o["op"] for o in p2["operaciones"]] == ["RECHAZAR"]
    pi = p2["filas"]["por_interpretar"][0]
    assert pi["ya_se_rechaza"] and [e["id"] for e in pi["entidades_nombradas"]] == ["E-SAP2"] and "INTEGRA_CON" in pi["tipos_nombrados"]
    assert {"op": "CORREGIR_RELACION", "relacion": "REL-001", "destino": "E-SAP2", "tipo_id": "INTEGRA_CON"}.items() <= pi["sugerencias"][0].items()
    assert pi["sugerencias"][0]["_lectura"] == "SIGMA ─ INTEGRA_CON ▸ SAP ERP"


def test_a_operacion_traduce_las_decisiones_de_siempre():
    d = lambda a, v, par=None: {"accion": a, "bloque": {"criterio": "ids", "valor": v}, "parametros": par or {}, "motivo": "m"}   # noqa: E731
    assert FR.a_operacion(d("APROBAR", ["E-1", "REL-1"])) == {"op": "VALIDAR", "ids": ["E-1", "REL-1"], "motivo": "m"}
    assert FR.a_operacion(d("CORREGIR_NOMBRE", ["E-1"], {"nombre": "X"})) == {"op": "CORREGIR_NOMBRE", "entidad": "E-1", "nombre": "X", "motivo": "m"}
    assert FR.a_operacion(d("CORREGIR_TIPO", ["E-1"], {"tipo_id": "MODULO"}))["tipo_id"] == "MODULO"


def test_operar_kb_en_dos_pasos(kbf):
    k, http = kbf()
    ops = [{"op": "INVERTIR_RELACION", "relacion": "REL-001", "motivo": "al revés"}]
    with pytest.raises(ErrorKortex, match="motivo general"):
        k.operar(ops, "")
    pv = k.operar(ops, "Corrección de Sofía")
    assert "Previsualización (1 operaciones" in pv and 'confirmar="OPE-' in pv
    assert not [c for c in http.llamadas if (c["json"] or {}).get("previsualizar") is False]
    hecho = k.operar(confirmar=pv.split('confirmar="')[1].split('"')[0])
    assert "Lote lote_0123456789ab · 1 decisiones guardadas" in hecho
    assert [c["json"]["operaciones"] for c in http.llamadas if (c["json"] or {}).get("previsualizar") is False] == [ops]
