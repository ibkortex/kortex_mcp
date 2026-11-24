"""Las fichas HTML en un navegador de verdad (Playwright + Chromium, sin conexión, file://): una pregunta por entidad, excepciones por
línea, contexto, exportación del JSON, persistencia (recarga y «Cargar respuestas») y, con el JSON descargado, importación → plan.
Datos sintéticos; nada toca la KB real."""
import json

import pytest
from datos_fichas import servida

from mcps.kortex_mcp.conocimiento import fichas_revision as FR

sync_api = pytest.importorskip("playwright.sync_api")
ACRED = "Persona de Prueba verificada por correo corporativo"


@pytest.fixture(scope="module")
def navegador():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"Chromium de Playwright no disponible: {e}")
        yield b
        b.close()


@pytest.fixture
def entorno(tmp_path):
    reg = FR.Registro(tmp_path / "registro")
    ix = FR.Indice(servida(), {})
    _, _, fa = FR.generar(ix, "A", "h1", "KORTEX", reg, tmp_path / "salida")
    _, _, fb = FR.generar(ix, "B", "h1", "KORTEX", reg, tmp_path / "salida")
    return reg, ix, fa, fb, tmp_path


def con(fichas, obj):
    return next(m for m in fichas if any(i["objeto"] == obj for i in m["items"]) or any(t["id"] == obj for t in m["tarjetas"]))


def abrir(navegador, fichero):
    ctx = navegador.new_context(accept_downloads=True, viewport={"width": 1280, "height": 1000})
    pg = ctx.new_page()
    errores = []
    pg.on("pageerror", lambda e: errores.append(str(e)))
    pg.goto("file:///" + str(fichero).replace("\\", "/"))
    return ctx, pg, errores


def descargar(pg, destino):
    with pg.expect_download() as d:
        pg.click("#b-export")
    d.value.save_as(destino)
    return json.loads(open(destino, encoding="utf-8").read())


def test_circuito_en_el_navegador(navegador, entorno):
    reg, ix, fa, _, tmp = entorno
    m = con(fa, "E-SIGMA")
    ctx, pg, errores = abrir(navegador, m["fichero"])
    # ---------------------------------------------------------------- visualización: una tarjeta por entidad, la entidad es la primera línea
    assert pg.locator(".conj").count() == len(m["tarjetas"]) and pg.locator(".linea[data-obj]").count() == len(m["items"])
    sg = pg.locator('.conj[data-sec="E-SIGMA"]')
    assert sg.locator("h2").inner_text().startswith("Validación funcional · SIGMA")
    assert sg.locator(".linea[data-obj]").first.inner_text().startswith("«SIGMA» se identifica como sistema.")
    assert "¿Es correcta esta representación?" in sg.inner_text()
    sirio = pg.locator('.conj[data-sec="E-SIRIO"]')
    assert "se revisa en SIGMA" in sirio.locator("details.tambien").text_content()               # REL-001 se revisa en SIGMA; en SIRIO, referencia
    assert not sirio.locator('.linea[data-obj="REL-001"]').count()
    assert sg.locator('details.tambien .linea[data-ctx="REL-011"]').count() == 1                # la PROPUESTO, como contexto en la ficha A
    # ---------------------------------------------------------------- evidencia y excepciones a un clic
    ev = sg.locator('.linea[data-obj="REL-001"] .ev')
    assert not ev.is_visible()
    sg.locator('.linea[data-obj="REL-001"] [data-abre=ev]').click()
    assert ev.is_visible() and "SIGMA envía las obras a SIRIO" in ev.inner_text()
    pg.fill("#rv-nombre", "Persona de Prueba")
    pg.fill("#rv-correo", "prueba@ejemplo.test")
    sg.locator(".pregunta input[value=SI]").check()
    l2 = sg.locator('.linea[data-obj="REL-002"]')
    l2.locator("[data-abre=exc]").click()
    l2.locator("input[value=INCORRECTA]").check()
    l2.locator("[data-x=nota]").fill("Ya no se integran")
    assert "No es cierta" in l2.inner_text()
    # error señalado en un elemento de contexto
    c11 = sg.locator('details.tambien')
    c11.locator("summary").click()
    c11.locator('.linea[data-ctx="REL-011"] [data-abre=ctx-err]').click()
    c11.locator('.linea[data-ctx="REL-011"] textarea').fill("El SICO no recibe datos de SIGMA")
    # otra tarjeta: parcialmente, con excepción de nombre en la entidad
    sap = pg.locator('.conj[data-sec="E-SAP"]')
    sap.locator(".pregunta input[value=PARCIAL]").check()
    assert sap.locator(".falta").is_visible()
    le = sap.locator('.linea[data-obj="E-SAP"]')
    le.locator("[data-abre=exc]").click()
    le.locator("input[value=CORREGIR_NOMBRE]").check()
    le.locator("[data-x=nota]").fill("SAP S/4HANA")
    assert not sap.locator(".falta").is_visible()
    assert pg.locator("#estado").inner_text().startswith(f"2 de {len(m['tarjetas'])} respondidas · Sí 1 · Parcialmente 1")
    # ---------------------------------------------------------------- navegación: filtros y búsqueda
    pg.select_option("#f-ver", "pend")
    assert not sg.is_visible() and not sap.is_visible()
    pg.select_option("#f-ver", "hechos")
    assert sg.is_visible() and pg.locator(".conj:visible").count() == 2
    pg.select_option("#f-ver", "")
    pg.fill("#f-q", "sirio 4p")
    assert sirio.is_visible() and not sap.is_visible()
    pg.fill("#f-q", "")
    # ---------------------------------------------------------------- exportación: cada elemento con su respuesta, independiente
    j = descargar(pg, tmp / f"respuestas_{m['ficha_id']}.json")
    E = {x["entidad_id"]: x for x in j["entidades"]}
    R = {x["relacion_id"]: x for x in j["relaciones"]}
    assert E["E-SIGMA"]["respuesta"] == "CORRECTA" and E["E-SIGMA"]["via"] == "grupo"
    assert R["REL-002"]["respuesta"] == "INCORRECTA" and R["REL-002"]["motivo"] == "Ya no se integran" and R["REL-002"]["via"] == "individual"
    sig_rels = [i["objeto"] for t in m["tarjetas"] if t["id"] == "E-SIGMA" for i in t["rels"]]
    assert all(R[r]["respuesta"] == "CORRECTA" for r in sig_rels if r != "REL-002")
    assert E["E-SAP"]["respuesta"] == "CORREGIR_NOMBRE" and E["E-SAP"]["nombre_nuevo"] == "SAP S/4HANA"
    assert j["contexto"] == [{"objeto": "REL-011", "texto": "El SICO no recibe datos de SIGMA"}]
    assert len(E) + len(R) == len(m["items"])
    # ---------------------------------------------------------------- persistencia: recarga y «Cargar respuestas» en otro navegador
    pg.reload()
    assert pg.locator('.conj[data-sec="E-SIGMA"] .pregunta input[value=SI]').is_checked() and pg.input_value("#rv-nombre") == "Persona de Prueba"
    ctx2, pg2, err2 = abrir(navegador, m["fichero"])
    assert not pg2.locator(".pregunta input:checked").count()
    pg2.set_input_files("#f-cargar", str(tmp / f"respuestas_{m['ficha_id']}.json"))
    pg2.wait_for_function("document.querySelector('#msg').textContent.indexOf('Cargadas')>=0")
    assert pg2.locator('.conj[data-sec="E-SAP"] .pregunta input[value=PARCIAL]').is_checked()
    assert "El nombre no es correcto" in pg2.locator('.linea[data-obj="E-SAP"]').inner_text()
    j2 = descargar(pg2, tmp / "repetida.json")
    assert [x["respuesta"] for x in j2["relaciones"]] == [x["respuesta"] for x in j["relaciones"]]
    # ---------------------------------------------------------------- importación y plan con el JSON del navegador
    texto = open(tmp / f"respuestas_{m['ficha_id']}.json", encoding="utf-8").read()
    imp = FR.importar(texto, reg, ix, "h1", "admin", reloj=lambda: "2026-11-20T12:00:00Z")
    p = FR.plan(imp, ix, acreditacion=ACRED)
    acc = {(d["accion"], tuple(d["bloque"]["valor"])) for d in p["decisiones"]}
    assert ("RECHAZAR", ("REL-002",)) in acc and ("CORREGIR_NOMBRE", ("E-SAP",)) in acc
    assert any(a == "APROBAR" and "E-SIGMA" in v for a, v in acc) and not any(a == "RECHAZAR" and "E-SIGMA" in v for a, v in acc)
    assert p["filas"]["observaciones_contexto"][0]["objeto"] == "REL-011"
    t = json.loads(texto)
    t["relaciones"][0]["relacion_id"] = "REL-004"
    with pytest.raises(FR.ErrorFicha, match="manipulado"):
        FR.importar(json.dumps(t), reg, ix, "h1", "admin")
    assert errores == [] and err2 == []
    ctx.close()
    ctx2.close()


def test_ficha_b_contexto_y_avisos(navegador, entorno):
    _, _, _, fb, tmp = entorno
    m = con(fb, "REL-011")
    ctx, pg, errores = abrir(navegador, m["fichero"])
    sg = pg.locator('.conj[data-sec="E-SIGMA"]')                           # SIGMA (VALIDADO_AUTO) como contexto para revisar su relación con SICO
    assert sg.locator('.linea[data-ctx="E-SIGMA"]').count() == 1 and not sg.locator('.linea[data-obj="E-SIGMA"]').count()
    assert sg.locator('.linea[data-obj="REL-011"]').count() == 1 and "sin cita literal" in sg.inner_text()
    sg.locator(".pregunta input[value=NO]").check()
    j = descargar(pg, tmp / "b.json")
    msg = pg.locator("#msg").inner_text()
    assert "no has indicado tu nombre" in msg and "no dicen qué cambiar" in msg
    assert {x["relacion_id"]: x["respuesta"] for x in j["relaciones"]}["REL-011"] == "INCORRECTA" and "E-SIGMA" not in {x["entidad_id"] for x in j["entidades"]}
    pg.set_viewport_size({"width": 390, "height": 900})
    assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    assert errores == []
    ctx.close()


def test_entidad_sin_relaciones_y_otra_ficha(navegador, entorno):
    _, _, _, fb, tmp = entorno
    m = con(fb, "E-HUERFANA")
    ctx, pg, _ = abrir(navegador, m["fichero"])
    h = pg.locator('.conj[data-sec="E-HUERFANA"]')
    assert h.locator(".linea[data-obj]").count() == 1 and "¿Es correcta esta representación?" in h.inner_text()
    (tmp / "otra.json").write_text(json.dumps({"ficha_id": "FR-A-20200101-00000000", "estado_ficha": {}}), encoding="utf-8")
    pg.set_input_files("#f-cargar", str(tmp / "otra.json"))
    pg.wait_for_function("document.querySelector('#msg').textContent.length>0")
    assert "otra ficha" in pg.locator("#msg").inner_text()
    ctx.close()
