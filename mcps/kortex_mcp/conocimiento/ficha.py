"""Ficha de relaciones de un elemento de la KB: el MISMO HTML autocontenido que descarga la web de la KB (su ficha.js, copiada en
recursos/ficha.js; si cambia en la web, hay que volver a copiarla).

Por qué un port a Python y no llamar a node: el MCP tiene que funcionar en cualquier puesto con solo el .venv (quien revisa no tiene por qué
tener node). Para no divergir: el CSS y el script del filtro se LEEN de ficha.js en cada uso, y
la lógica es una traducción línea a línea de construirFicha/htmlFicha, con una prueba que compara el HTML con el que genera node a
partir de la misma KB servida (tests/conocimiento/test_ficha.py; se salta si no hay node). Diferencia conocida: el orden alfabético usa una
aproximación de la colación «es» de ICU (puntuación, cifras, letras; acentos y mayúsculas como desempate; ñ después de n)."""
import datetime as dt
import os
import re
import unicodedata
from pathlib import Path

FICHA_JS = Path(os.environ.get("KORTEX_FICHA_JS") or Path(__file__).resolve().parent / "recursos" / "ficha.js")   # copia de la de la web

FAMILIA = {"PROC": "Procesos y capacidades", "TECNO": "Tecnología y sistemas", "OBJ": "Objetos y datos", "PERSONA": "Personas y roles", "INI": "Iniciativas",
           "ORG": "Organización", "EXT": "Entidades externas", "NOR": "Normativa y requisitos", "KPI": "Indicadores", "ACTIVO": "Activos físicos",
           "CONO": "Conocimiento", "OTRA": "Otras"}
CONF = {"VALIDADO": "Validado", "PENDIENTE_VALIDAR": "Pendiente de validar", "SIN_CORROBORAR": "Sin corroborar", "SIN_CITA_LITERAL": "Sin cita literal",
        "SIN_EVIDENCIA": "Deducido sin evidencia", "FUERA_DE_CATALOGO": "Fuera del catálogo", "SIN_VINCULAR": "Sin vincular", "EN_CONFLICTO": "En conflicto",
        "VALIDADO_PERSONA": "Validado", "VALIDADO_AUTO": "Pendiente de validar", "PROPUESTO": "Sin corroborar"}
GRUPO = {"APLICACION_SISTEMA": "g-app", "COMPONENTE_TECNICO": "g-comp", "CAPACIDAD_ACTIVIDAD": "g-cap", "OTRA": "g-otra", "HPUM": "g-hpum", "AMBITO": "g-amb",
         "DOCUMENTO": "g-doc", "SIN_ENCAJE_CATALOGO": "g-sin"}
SECCION = {"RELACION_KB": "rel", "CORRESPONDENCIA_HPUM": "hpum", "DOCUMENTO_HPUM": "hpum", "JERARQUIA_HPUM": "hpum", "AMBITO_ENTIDAD": "amb",
           "CLASIFICACION_AMBITO": "amb", "MENCION": "doc", "SIN_ENCAJE": "doc", "RELACION_ENTRE_DOCUMENTOS": "doc"}
SECCIONES = [
    ("rel", "Relaciones con otras entidades", "Lo que la KB ha extraído del contenido de los documentos: qué usa, qué soporta, de qué forma parte… con la cita que lo justifica."),
    ("hpum", "Procesos HPUM", "Correspondencias con el catálogo de procesos HPUM y, en los procesos, su posición en la jerarquía."),
    ("amb", "Ámbitos de negocio", "Ámbitos a los que pertenece, deducidos de los documentos en los que aparece."),
    ("doc", "Documentos", "Documentos en los que aparece, con la cita literal de cada mención."),
    ("n2", "Segundo nivel", "Relaciones de las entidades conectadas con otras entidades: el contexto alrededor del elemento."),
]
ESTADO = {"ok": "Aprobada", "corr": "Corregida", "pending": "Pendiente de revisar", "doubt": "Hipótesis por confirmar", "rej": "Rechazada", "cat": "Del catálogo"}
DUDOSAS = {"HIPOTESIS_RUTA_NOMBRE", "DEDUCIDA_POR_COINCIDENCIA_ENTRE_DOCUMENTOS"}
MAX_CITAS = 3
_REV = {"APROBADA": "ok", "CORREGIDA": "corr", "RECHAZADA": "rej"}
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


# ---------------------------------------------------------------------- equivalentes de JS
def js(v) -> str:
    """String(v) de JS para lo que llega del JSON."""
    if v is None:
        return "undefined"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, list):
        return ",".join("" if x is None else js(x) for x in v)
    return str(v)


def jj(lista, sep) -> str:
    """Array.prototype.join de JS: null y undefined cuentan como cadena vacía."""
    return sep.join("" if x is None else js(x) for x in lista)


def esc(s) -> str:
    s = "" if s is None else js(s)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")


def num(n) -> str:
    """n.toLocaleString('es-ES') para enteros: agrupa por miles solo desde 10.000 (minimumGroupingDigits = 2)."""
    n = int(n)
    return f"{n:,}".replace(",", ".") if abs(n) >= 10000 else str(n)


def fecha_es(d: dt.datetime) -> str:
    """toLocaleString('es-ES', {dateStyle: 'long', timeStyle: 'short'}) → «9 de noviembre de 2026, 8:05»."""
    return f"{d.day} de {_MESES[d.month - 1]} de {d.year}, {d.hour}:{d.minute:02d}"


def clave_es(s: str):
    """Aproximación de localeCompare(…, 'es'): puntuación < cifras < letras; acentos y luego mayúsculas solo desempatan; ñ tras n."""
    pri, sec, ter = [], [], []
    for ch in str(s):
        base = unicodedata.normalize("NFD", ch)
        letra, marcas = base[0], base[1:]
        low = letra.lower()
        if ch.lower() == "ñ":
            pri.append((2, "n", 1)); sec.append(0)
        elif low.isalpha():
            pri.append((2, low, 0)); sec.append(1 if marcas else 0)
        elif low.isdigit():
            pri.append((1, low, 0)); sec.append(0)
        else:
            pri.append((0, ch, 0)); sec.append(0)
        ter.append(1 if letra.isupper() else 0)
    return (pri, sec, ter)


def bonito(v) -> str:
    s = js(v or "").replace("_", " ").lower()
    s = (s[:1].upper() + s[1:]) if s and s[0] != "\n" else s
    s = re.sub("hpum", "HPUM", s, flags=re.I)
    return "Proceso citado (sin mapear a HPUM)" if re.fullmatch(r"Proceso documento", s, flags=re.I) else s


def verbo(v) -> str:
    return re.sub("hpum", "HPUM", js(v or "").replace("_", " ").lower(), flags=re.I)


def ultimo(ruta):
    p = js(ruta or "").split(" > ")
    return p[-1], p[:-1]


def _cap(s):
    return s[:1].upper() + s[1:] if s else s


# ---------------------------------------------------------------------- modelo (construirFicha)
def construir_ficha(D: dict, estado: dict, id_: str, saltos: int = 1, huella: str = "", fecha: dt.datetime | None = None) -> dict:
    grafo = D.get("grafo") or {}
    nodos = {n["id"]: n for n in grafo.get("nodos") or []}
    raiz = nodos.get(id_)
    if not raiz:
        raise KeyError("Ese elemento ya no está en la KB")
    ENT = {e["entidad_id"]: e for e in D.get("entidades") or []}
    REL = {r["relacion_id"]: r for r in D.get("relaciones") or []}
    DOC = {d["doc_id"]: d for d in D.get("documentos") or []}
    amb = {n["id"]: n.get("etiqueta") for n in grafo.get("nodos") or [] if n.get("clase") == "AMBITO"}
    aristas = grafo.get("aristas") or []
    adj = {}
    for a in aristas:
        if a.get("origen") in nodos and a.get("destino") in nodos:
            for k in (a["origen"], a["destino"]):
                adj.setdefault(k, []).append(a)
    estado = estado or {}
    rv = lambda oid: (estado.get(oid) if oid else None) or None  # noqa: E731

    def nombre_de(n):
        r = rv(n["id"]); p = (r or {}).get("parametros") or {}
        if n.get("clase") == "ENTIDAD":
            return p.get("nombre") or (ENT.get(n["id"]) or {}).get("nombre") or n.get("etiqueta")
        if n.get("clase") == "HPUM":
            return ultimo((n.get("propiedades") or {}).get("ruta") or n.get("etiqueta"))[0]
        return n.get("etiqueta") or n["id"]

    def tipo_de(n):
        c = n.get("clase")
        if c == "ENTIDAD":
            r = rv(n["id"])
            return bonito(((r or {}).get("parametros") or {}).get("tipo_id") or n.get("tipo_id"))
        if c == "HPUM":
            _, arriba = ultimo((n.get("propiedades") or {}).get("ruta") or "")
            return f"Proceso HPUM {js(n.get('nivel') or '')}".strip() + (" · " + " › ".join(arriba) if arriba else "")
        if c == "AMBITO":
            return "Ámbito de negocio"
        if c == "DOCUMENTO":
            f = (n.get("propiedades") or {}).get("formato")
            return "Documento" + (" " + js(f) if f else "")
        if c == "SIN_ENCAJE":
            return "Concepto sin encaje en el catálogo"
        return bonito(c)

    def chip(n):
        return {"id": n["id"], "nombre": nombre_de(n), "tipo": tipo_de(n), "grupo": GRUPO.get(n.get("grupo")) or "g-otra", "ent": n.get("clase") == "ENTIDAD"}

    def doc_nombre(d):
        x = DOC.get(d)
        return x.get("nombre") if x else (nodos.get(d) or {}).get("etiqueta") or d

    def objeto(a):
        if a.get("clase") == "RELACION_KB":
            return a.get("relacion_id") or a.get("id")
        if a.get("clase") == "CORRESPONDENCIA_HPUM":
            return f"HPUM|{a['origen']}|{a['destino']}"
        return None

    def estado_de(a):
        r = rv(objeto(a))
        if r:
            return _REV.get(r.get("estado")) or "pending"
        if a.get("estado") == "CATALOGO":
            return "cat"
        return "doubt" if a.get("estado") in DUDOSAS else "pending"

    def notas(a):
        r = (REL.get(a.get("relacion_id")) or a) if a.get("clase") == "RELACION_KB" else a
        out = []
        for e in (r.get("evidencias") or a.get("evidencias") or []):
            if not e or not e.get("cita"):
                continue
            loc = e.get("ubicacion") or (" · ".join(f"{k} {js(v)}" for k, v in e["locator"].items()) if e.get("locator") else "")
            out.append({"cita": e["cita"], "doc": doc_nombre(e["doc_id"]) if e.get("doc_id") else "", "loc": loc, "just": e.get("justificacion") or ""})
        for j in a.get("justificaciones") or []:
            out.append({"cita": "", "doc": doc_nombre(j["doc_id"]) if j.get("doc_id") else "", "loc": "", "just": j.get("texto") or ""})
        if not out and a.get("confianza_motivos"):
            out.append({"cita": "", "doc": "", "loc": "", "just": " · ".join(a["confianza_motivos"])})
        if not out and a.get("estado") == "DEDUCIDA_DEL_DOCUMENTO":
            out.append({"cita": "", "doc": "", "loc": "", "just": "Deducido: aparece en documentos de este ámbito."})
        return out

    def flujo(a, seccion):
        o, d, r = nodos.get(a["origen"]), nodos.get(a["destino"]), rv(objeto(a))
        ns = notas(a)
        autor = ""
        if r:
            autor = f"{js(r.get('autor'))} · {js(r.get('en') or '')[:16].replace('T', ' ', 1)}" + (f" · {r['motivo']}" if r.get("motivo") else "")
        docs = list(dict.fromkeys([*(doc_nombre(x) for x in a.get("documentos") or []), *(x["doc"] for x in ns if x["doc"])]))
        return {"seccion": seccion, "tipo": a.get("tipo_id"), "rel": verbo(a.get("tipo_id")), "o": chip(o), "d": chip(d), "estado": estado_de(a),
                "notas": ns, "autor": autor, "docs": docs}

    # ------------------------------------------------------------ primer nivel
    directas = [a for a in adj.get(id_, []) if SECCION.get(a.get("clase"))]
    flujos = [flujo(a, SECCION[a["clase"]]) for a in directas]
    vecinos = list(dict.fromkeys(a["destino"] if a["origen"] == id_ else a["origen"] for a in directas))
    # ------------------------------------------------------------ segundo nivel
    segundo = []
    if saltos > 1:
        vistas = {a.get("id") or a.get("relacion_id") for a in directas}
        for v in vecinos:
            nv = nodos.get(v)
            if not nv or nv.get("clase") != "ENTIDAD":
                continue
            fs = [flujo(a, "n2") for a in adj.get(v, []) if a.get("clase") == "RELACION_KB" and a["origen"] != id_ and a["destino"] != id_
                  and (a.get("id") or a.get("relacion_id")) not in vistas]
            if fs:
                segundo.append({"via": chip(nv), "flujos": fs})
        segundo.sort(key=lambda g: (-len(g["flujos"]), clave_es(g["via"]["nombre"])))

    # ------------------------------------------------------------ entidades relacionadas (ámbito → tipo → entidad)
    ids = list(dict.fromkeys([*vecinos, *(x for g in segundo for f in g["flujos"] for x in (f["o"]["id"], f["d"]["id"]))]))
    ids = [x for x in ids if x != id_]
    amb_de = {}
    for a in aristas:
        if a.get("clase") == "AMBITO_ENTIDAD":
            amb_de.setdefault(a["origen"], []).append(amb.get(a["destino"]) or a["destino"])

    def tarjeta(eid):
        n, e, r = nodos.get(eid), ENT.get(eid) or {}, rv(eid)
        men = next((m for m in e.get("menciones") or [] if (m.get("evidencia") or {}).get("cita")), None)
        return {"id": eid, "nombre": nombre_de(n), "tipo": tipo_de(n), "familia": FAMILIA.get(e.get("familia")) or bonito(e.get("familia") or "OTRA"),
                "grupo": GRUPO.get(n.get("grupo")) or "g-otra", "estado": (_REV.get(r.get("estado")) or "pending") if r else "pending",
                "desc": ((e.get("descripciones") or [None])[0] or {}).get("texto") or "", "alias": e.get("alias") or [],
                "conf": CONF.get(e.get("confianza") or n.get("confianza")) or "", "hpum": [c.get("ruta") or c.get("nodo_id") for c in e.get("correspondencias_hpum") or []],
                "docs": [doc_nombre(x) for x in e.get("documentos") or []], "cita": men["evidencia"]["cita"] if men else "",
                "ambitos": amb_de.get(eid) or ["Sin ámbito asignado"]}

    por_amb = {}
    for eid in ids:
        n = nodos.get(eid)
        if not n or n.get("clase") != "ENTIDAD":
            continue
        t = tarjeta(eid)
        for a in t["ambitos"]:
            por_amb.setdefault(a, []).append(t)
    catalogo = []
    for nombre, ts in por_amb.items():
        tipos = {}
        for t in ts:
            tipos.setdefault(t["tipo"], []).append(t)
        tl = [{"tipo": tipo, "items": sorted(x, key=lambda p: clave_es(p["nombre"]))} for tipo, x in tipos.items()]
        tl.sort(key=lambda p: -len(p["items"]))
        catalogo.append({"nombre": nombre, "total": len(ts), "tipos": tl})
    catalogo.sort(key=lambda p: -p["total"])

    # ------------------------------------------------------------ cabecera
    e, rr, props = ENT.get(id_) or {}, rv(id_), raiz.get("propiedades") or {}
    ficha = []
    clase = raiz.get("clase")
    if clase == "ENTIDAD":
        ficha += [["Tipo", tipo_de(raiz)], ["Familia", FAMILIA.get(e.get("familia")) or bonito(e.get("familia") or "")],
                  ["Ámbitos", " · ".join(amb_de.get(id_) or ["Sin ámbito asignado"])], ["Estado", CONF.get(e.get("confianza") or raiz.get("confianza")) or "—"],
                  ["Revisión", f"{ESTADO[_REV.get(rr.get('estado')) or 'pending']} · {js(rr.get('autor'))}" if rr else ESTADO["pending"]]]
        if e.get("alias"):
            ficha.append(["También llamado", " · ".join(e["alias"])])
        if e.get("correspondencias_hpum"):
            ficha.append(["Procesos HPUM", jj([c.get("ruta") or c.get("nodo_id") for c in e["correspondencias_hpum"]], "\n")])
        ficha.append(["Documentos", jj([doc_nombre(x) for x in e.get("documentos") or []], "\n") or "—"])
    elif clase == "HPUM":
        ficha += [["Nivel", raiz.get("nivel") or "—"], ["Ruta en el catálogo", " › ".join(js(props.get("ruta") or raiz.get("etiqueta")).split(" > "))],
                  ["Ámbitos", " · ".join(js(amb.get(a) or a) for a in raiz.get("ambitos") or []) or "—"]]
        if props.get("descripcion"):
            ficha.append(["Descripción", props["descripcion"]])
    elif clase == "DOCUMENTO":
        d = DOC.get(id_) or {}
        ficha += [["Ruta documental", props.get("ruta_documental") or d.get("nombre") or "—"], ["Lectura", props.get("estado") or d.get("estado") or "—"],
                  ["Ámbitos", " · ".join(js(amb.get(a) or a) for a in raiz.get("ambitos") or []) or "—"]]
        if props.get("tipo_documental"):
            ficha.append(["Qué es", props["tipo_documental"]])
    elif clase == "AMBITO":
        if props.get("descripcion"):
            ficha.append(["Descripción", props["descripcion"]])
        ficha.append(["Documentos clasificados", str(len(raiz.get("documentos") or []))])
    descripciones = [x for x in ({"texto": y.get("texto"), "doc": doc_nombre(y["doc_id"]) if y.get("doc_id") else ""} for y in (e.get("descripciones") or [])[:3]) if x["texto"]]

    todos = flujos + [f for g in segundo for f in g["flujos"]]
    docs_fuente = {x for f in todos for x in f["docs"]}
    secciones = []
    for k, t, p in SECCIONES:
        if k == "n2":
            continue
        fs = [f for f in flujos if f["seccion"] == k]
        tipos = {}
        for f in fs:
            tipos.setdefault(f["rel"], []).append(f)
        tl = sorted(({"rel": rel, "flujos": x} for rel, x in tipos.items()), key=lambda a: -len(a["flujos"]))
        if fs:
            secciones.append({"k": k, "titulo": t, "texto": p, "total": len(fs), "tipos": tl})
    hp = {c["id"] for f in flujos if f["seccion"] == "hpum" for c in (f["o"], f["d"]) if c["grupo"] == "g-hpum" and c["id"] != id_}
    return {"campana": D.get("campana_id"), "huella": huella, "fecha": fecha or dt.datetime.now(), "saltos": saltos, "raiz": chip(raiz), "clase": clase,
            "ficha": ficha, "descripciones": descripciones, "secciones": secciones, "segundo": segundo, "n2": next(s for s in SECCIONES if s[0] == "n2"),
            "catalogo": catalogo,
            "kpis": {"directas": len(flujos), "entidades": sum(1 for x in ids if (nodos.get(x) or {}).get("clase") == "ENTIDAD"), "hpum": len(hp),
                     "documentos": len(docs_fuente), "pendientes": sum(1 for f in todos if f["estado"] in ("pending", "doubt"))}}


# ---------------------------------------------------------------------- HTML (htmlFicha)
def _nodo(c, raiz_id):
    cuerpo = f'<span class="nd-dot {c["grupo"]}" aria-hidden="true"></span><span class="nd-t"><b>{esc(c["nombre"])}</b><small>{esc(c["tipo"])}</small></span>'
    if c["id"] == raiz_id:
        return f'<span class="nd yo" title="El elemento de esta ficha">{cuerpo}</span>'
    return f'<a class="nd" href="#e-{esc(c["id"])}" title="Ver su ficha más abajo">{cuerpo}</a>' if c["ent"] else f'<span class="nd">{cuerpo}</span>'


def _flujo(f, raiz_id):
    q = jj([f["o"]["nombre"], f["rel"], f["d"]["nombre"], *(js(n["cita"]) + " " + js(n["doc"]) + " " + js(n["just"]) for n in f["notas"])], " ").lower()
    citas = "".join("<li>" + (f"<q>{esc(n['cita'])}</q>" if n["cita"] else "") + (f'<span class="just">{esc(n["just"])}</span>' if n["just"] else "")
                    + (f'<span class="src">{esc(" · ".join(x for x in (n["doc"], n["loc"]) if x))}</span>' if n["doc"] or n["loc"] else "") + "</li>"
                    for n in f["notas"][:MAX_CITAS])
    mas = f'<li class="src">y {len(f["notas"]) - MAX_CITAS} citas más en los mismos documentos</li>' if len(f["notas"]) > MAX_CITAS else ""
    lista = f'<ul class="fl-citas">{citas}{mas}</ul>' if citas or mas else ""
    return (f'<article class="flujo {f["estado"]}" data-q="{esc(q)}" data-estado="{f["estado"]}">\n'
            f'    <div class="fl-linea">{_nodo(f["o"], raiz_id)}<span class="fl-rel" aria-label="{esc(f["rel"])}"><span class="fl-l"></span><span class="fl-tag">{esc(f["rel"])}</span><span class="fl-l fl-punta"></span></span>{_nodo(f["d"], raiz_id)}</div>\n'
            f'    <div class="fl-pie"><span class="review-state {f["estado"]}">{ESTADO[f["estado"]]}</span>' + (f'<span class="src">{esc(f["autor"])}</span>' if f["autor"] else "") + "</div>\n"
            f'    {lista}</article>')


def _plural(n, s, p):
    return f"{num(n)} {s if n == 1 else p}"


def html_ficha(m) -> str:
    R = m["raiz"]["id"]
    kp = lambda v, t: f'<div class="review-kpi"><b>{esc(num(v))}</b><small>{esc(t)}</small></div>'  # noqa: E731
    secciones = "".join(
        f'<details class="review-scope" data-seccion="{s["k"]}"{" open" if i < 2 else ""}>\n'
        f'    <summary><span><strong>{esc(s["titulo"])}</strong><span class="caption">{esc(s["texto"])}</span></span><span class="meta" data-cuenta>{_plural(s["total"], "relación", "relaciones")}</span></summary>\n'
        f'    <div class="review-scope-body">' + "".join(
            f'<details class="review-type" open><summary><b>{esc(_cap(t["rel"]))}</b><span class="review-num" data-cuenta>{len(t["flujos"])}</span></summary>\n'
            f'      <div class="flujos">{"".join(_flujo(f, R) for f in t["flujos"])}</div></details>' for t in s["tipos"]) + "</div></details>"
        for i, s in enumerate(m["secciones"]))
    segundo = (f'<details class="review-scope" data-seccion="n2">\n'
               f'    <summary><span><strong>{esc(m["n2"][1])}</strong><span class="caption">{esc(m["n2"][2])}</span></span><span class="meta" data-cuenta>{_plural(sum(len(g["flujos"]) for g in m["segundo"]), "relación", "relaciones")}</span></summary>\n'
               f'    <div class="review-scope-body">' + "".join(
                   f'<details class="review-family"><summary><span class="via">A través de {_nodo(g["via"], R)}</span><small data-cuenta>{_plural(len(g["flujos"]), "relación", "relaciones")}</small></summary>\n'
                   f'      <div class="review-family-body flujos">{"".join(_flujo(f, R) for f in g["flujos"])}</div></details>' for g in m["segundo"]) + "</div></details>") if m["segundo"] else ""

    def item(t):
        q = (js(t["nombre"]) + " " + js(t["tipo"]) + " " + jj(t["alias"], " ") + " " + jj(t["hpum"], " ") + " " + jj(t["docs"], " ")).lower()
        cita = js(t["cita"])
        desc = f'<span class="desc">{esc(t["desc"])}</span>' if t["desc"] else ""
        return (f'<article class="review-item {t["estado"]}" id="e-{esc(t["id"])}" data-q="{esc(q)}" data-estado="{t["estado"]}">\n'
                f'    <span class="it-cab"><span class="nd-dot {t["grupo"]}" aria-hidden="true"></span><strong>{esc(t["nombre"])}</strong><span class="review-state {t["estado"]}">{ESTADO[t["estado"]]}</span></span>\n'
                f'    {desc}\n'
                f'    <span class="links"><b>Tipo:</b> {esc(t["tipo"])} · <b>Familia:</b> {esc(t["familia"])}' + (f' · <b>Estado:</b> {esc(t["conf"])}' if t["conf"] else "")
                + (f' · <b>Alias:</b> {esc(jj(t["alias"][:3], ", "))}' if t["alias"] else "") + "</span>\n"
                f'    ' + (f'<span class="links"><b>Proceso HPUM:</b> {esc(jj(t["hpum"][:3], " · "))}' + (f' (+{len(t["hpum"]) - 3})' if len(t["hpum"]) > 3 else "") + "</span>" if t["hpum"] else "") + "\n"
                f'    ' + (f'<q class="cita">{esc(cita[:260])}{"…" if len(cita) > 260 else ""}</q>' if t["cita"] else "") + "\n"
                f'    <span class="source">Fuente: {esc(jj(t["docs"][:3], " · ") or "—")}' + (f' (+{len(t["docs"]) - 3})' if len(t["docs"]) > 3 else "") + "</span></article>")

    catalogo = (f'<details class="review-scope" data-seccion="cat">\n'
                f'    <summary><span><strong>Entidades relacionadas</strong><span class="caption">Cada entidad que aparece arriba, ordenada como en el catálogo: ámbito, tipo y entidad. Una entidad aparece en todos sus ámbitos.</span></span><span class="meta" data-cuenta>{_plural(m["kpis"]["entidades"], "entidad", "entidades")}</span></summary>\n'
                f'    <div class="review-scope-body">' + "".join(
                    f'<details class="review-family"><summary><strong>{esc(a["nombre"])}</strong><small data-cuenta>{_plural(a["total"], "entidad", "entidades")} · {_plural(len(a["tipos"]), "tipo", "tipos")}</small></summary>\n'
                    f'      <div class="review-family-body">' + "".join(
                        f'<details class="review-type"><summary><b>{esc(t["tipo"])}</b><span class="review-num" data-cuenta>{len(t["items"])}</span></summary><div class="review-items">{"".join(item(x) for x in t["items"])}</div></details>'
                        for t in a["tipos"]) + "</div></details>" for a in m["catalogo"]) + "</div></details>") if m["catalogo"] else ""
    ficha = ""
    if m["ficha"] or m["descripciones"]:
        dl = "".join(f"<div><dt>{esc(k)}</dt><dd>{esc(v).replace(chr(10), '<br>')}</dd></div>" for k, v in m["ficha"])
        descs = ('<div class="descs">' + "".join(f"<p>{esc(d['texto'])}" + (f'<span class="src">{esc(d["doc"])}</span>' if d["doc"] else "") + "</p>" for d in m["descripciones"]) + "</div>") if m["descripciones"] else ""
        ficha = f'<section class="ficha" aria-label="Ficha del elemento"><dl>{dl}</dl>\n    {descs}</section>'
    vacio = '<p class="review-empty">Este elemento no tiene relaciones en la KB servida.</p>' if not m["secciones"] and not m["segundo"] else ""
    opciones = [(s["k"], s["titulo"]) for s in m["secciones"]] + ([("n2", m["n2"][1])] if m["segundo"] else []) + ([("cat", "Entidades relacionadas")] if m["catalogo"] else [])
    return (f'<header class="hero">\n'
            f'    <div class="hero-cab"><span class="nd-dot grande {m["raiz"]["grupo"]}" aria-hidden="true"></span><div><h1>{esc(m["raiz"]["nombre"])}</h1><p class="hero-tipo">{esc(m["raiz"]["tipo"])}</p></div></div>\n'
            f'    <p>Ficha de relaciones de la KB {esc(m["campana"])}' + (f", versión {esc(m['huella'])}" if m["huella"] else "")
            + f'. Generada el {esc(fecha_es(m["fecha"]))} con {"las relaciones directas y las de segundo nivel" if m["saltos"] > 1 else "las relaciones directas"}.</p>\n'
            f'  </header>\n'
            f'  <div class="review-app">\n'
            f'    {ficha}\n'
            f'    <div class="review-tools" role="search">\n'
            f'      <input id="f-q" type="search" placeholder="Buscar en las relaciones, citas y documentos…" aria-label="Buscar" autocomplete="off">\n'
            f'      <select id="f-sec" aria-label="Sección"><option value="">Todas las secciones</option>' + "".join(f'<option value="{k}">{esc(t)}</option>' for k, t in opciones) + "</select>\n"
            f'      <select id="f-est" aria-label="Estado de revisión"><option value="">Cualquier estado</option>' + "".join(f'<option value="{k}">{ESTADO[k]}</option>' for k in ("pending", "doubt", "ok", "corr", "rej")) + "</select>\n"
            f'      <button type="button" id="f-abrir">Desplegar todo</button><button type="button" id="f-imp">Imprimir o PDF</button>\n'
            f'    </div>\n'
            f'    <div class="review-kpis">{kp(m["kpis"]["directas"], "relaciones directas")}{kp(m["kpis"]["entidades"], "entidades conectadas")}{kp(m["kpis"]["hpum"], "procesos HPUM")}{kp(m["kpis"]["documentos"], "documentos que lo sustentan")}</div>\n'
            f'    <div class="review-legend"><span class="ok">Aprobada o corregida</span><span class="pending">Pendiente de revisar</span><span class="doubt">Hipótesis por confirmar</span><span class="rej">Rechazada</span><span class="cat">Del catálogo HPUM</span>\n'
            f'      <span class="estado-n" id="f-n" role="status">{_plural(m["kpis"]["pendientes"], "relación por revisar", "relaciones por revisar")} en esta ficha</span></div>\n'
            f'    {vacio}{secciones}{segundo}{catalogo}\n'
            f'    <p class="review-disclaimer">Es una foto de la KB en el momento de la descarga: no se actualiza sola. Lo pendiente y las hipótesis todavía no están validados; para decidir, vuelve a la web de la KB. Las citas son literales del documento que se indica.</p>\n'
            f'  </div>')


def _recursos():
    """CSS y script del filtro, leídos de ficha.js (la misma fuente que la web)."""
    try:
        src = FICHA_JS.read_text(encoding="utf-8")
        css = re.search(r"export const CSS = `(.*?)`;", src, re.S).group(1)
        script = re.search(r"const SCRIPT = `(.*?)`;", src, re.S).group(1)
        return css, script
    except (OSError, AttributeError):
        return "body{font:14px/1.5 system-ui,sans-serif;margin:24px}", ""      # sin el repositorio al lado: ficha legible pero sin estilos de la web


def documento_ficha(m) -> str:
    css, script = _recursos()
    return ('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">'
            f'<title>{esc(m["raiz"]["nombre"])} · relaciones en la KB</title><style>{css}</style></head><body><main class="page">{html_ficha(m)}</main><script>{script}</script></body></html>')


def nombre_fichero(m) -> str:
    s = unicodedata.normalize("NFKD", js(m["raiz"]["nombre"]))
    s = re.sub(r"[̀-ͯ]", "", s)
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:60] or "elemento"
    return f"relaciones_{s}_{js(m['campana'])}.html"
