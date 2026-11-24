"""El HTML de la ficha debe ser EL MISMO que descarga la web (kbweb/web/ficha.js). Con node disponible se compara carácter a carácter;
sin node, se comprueba la estructura."""
import datetime as dt
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from test_kb import SERVIDA

from kortex_mcp import ficha as F

AQUI = Path(__file__).resolve().parent
REAL = Path(os.environ.get("KORTEX_SERVIDA_PRUEBA", "servida_de_prueba_no_incluida.json"))
FECHA = dt.datetime(2026, 11, 19, 9, 5)
ESTADO = {"REL-1": {"estado": "RECHAZADA", "autor": "revisora", "en": "2026-11-19T10:11:12Z", "motivo": "no aplica <script>"},
          "E2": {"estado": "CORREGIDA", "autor": "admin", "en": "2026-11-18T08:00:00Z", "parametros": {"nombre": "Contratista & cía"}}}


def test_estructura_sin_node():
    m = F.construir_ficha(SERVIDA, ESTADO, "E1", saltos=2, huella="h0", fecha=FECHA)
    assert m["kpis"] == {"directas": 3, "entidades": 1, "hpum": 0, "documentos": 1, "pendientes": 2}
    assert [s["k"] for s in m["secciones"]] == ["rel", "amb", "doc"]
    html = F.documento_ficha(m)
    assert html.startswith("<!doctype html>") and "<title>SIGMA · relaciones en la KB</title>" in html
    assert "Contratista &amp; cía" in html and "no aplica &lt;script&gt;" in html and "<script>(function(){" in html
    assert "Generada el 19 de noviembre de 2026, 9:05" in html and F.nombre_fichero(m) == "relaciones_SIGMA_KORTEX.html"
    assert ".review-kpis{" in html                                       # el CSS sale de ficha.js


def test_formatos_es():
    assert (F.num(1234), F.num(12345), F.num(1234567)) == ("1234", "12.345", "1.234.567")
    assert sorted(["Ábaco", "abeja", "Ñu", "nube", "zeta", "_x", "a b", "ab"], key=F.clave_es) == ["_x", "a b", "ab", "Ábaco", "abeja", "nube", "Ñu", "zeta"]


def _node(D, estado, ids, saltos, tmp_path):
    (tmp_path / "s.json").write_text(json.dumps(D, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "e.json").write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run(["node", str(AQUI / "ficha_node.mjs"), str(F.FICHA_JS), str(tmp_path / "s.json"), str(tmp_path / "e.json"), ",".join(ids), str(saltos)],
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)


def _iguales(D, estado, ids, saltos, tmp_path):
    J = _node(D, estado, ids, saltos, tmp_path)
    for i in ids:
        m = F.construir_ficha(D, estado, i, saltos=saltos, huella="h0", fecha=FECHA)
        assert F.html_ficha(m) == J[i]["html"], i
        assert F.nombre_fichero(m) == J[i]["nombre"] and m["kpis"] == J[i]["kpis"]


@pytest.mark.skipif(not shutil.which("node"), reason="sin node no se puede ejecutar ficha.js")
@pytest.mark.parametrize("saltos", [1, 2])
def test_igual_que_ficha_js_datos_sinteticos(tmp_path, saltos):
    _iguales(SERVIDA, ESTADO, ["E1", "E2", "A1", "D1"], saltos, tmp_path)


@pytest.mark.skipif(not shutil.which("node") or not REAL.exists(), reason="sin node o sin la KB servida de prueba")
@pytest.mark.parametrize("saltos", [1, 2])
def test_igual_que_ficha_js_kb_real(tmp_path, saltos):
    D = json.loads(REAL.read_text(encoding="utf-8"))
    grado = {}
    for a in D["grafo"]["aristas"]:
        for k in (a["origen"], a["destino"]):
            grado[k] = grado.get(k, 0) + 1
    nodos = {n["id"]: n["clase"] for n in D["grafo"]["nodos"]}
    ids = []
    for clase in ("ENTIDAD", "HPUM", "DOCUMENTO", "AMBITO", "SIN_ENCAJE"):
        c = sorted((i for i in grado if nodos.get(i) == clase), key=lambda i: -grado[i])
        ids += c[:4] + c[-1:]
    est = {r["relacion_id"]: {"estado": ["APROBADA", "RECHAZADA", "CORREGIDA"][n % 3], "autor": "admin", "en": "2026-11-19T10:11:12Z",
                              "motivo": "prueba" if n % 2 else ""} for n, r in enumerate(D["relaciones"][:60])}
    est.update({e["entidad_id"]: {"estado": "CORREGIDA", "autor": "revisora", "en": "2026-11-18T08:00:00Z", "parametros": {"nombre": f"Corregido {n}"}}
                for n, e in enumerate(D["entidades"][:20])})
    _iguales(D, est, ids, saltos, tmp_path)
