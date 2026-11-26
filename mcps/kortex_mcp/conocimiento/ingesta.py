"""Herramientas de consulta sobre la API de conocimiento (lo mismo que ve la persona en la web de ingesta, con sus permisos).

Las salidas son texto compacto para Claude: numeradas, con el doc_id para seguir tirando del hilo y sin repetir campos vacíos."""
import base64
import json
import re
from pathlib import Path

import requests

from . import config
from .sesion import ErrorKortex

MAX_ADJUNTOS_MB = 20


def _r(texto, n=400):
    t = re.sub(r"\s+", " ", str(texto or "")).strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def _equipos(s) -> list:
    return (s.pedir("GET", "me") or {}).get("teams") or []


def _equipo(s, equipo):
    if equipo:
        return equipo
    eq = _equipos(s)
    if len(eq) == 1:
        return eq[0]["team_id"]
    if not eq:
        raise ErrorKortex("Tu usuario no pertenece a ningún equipo.")
    raise ErrorKortex("Ves varios equipos; indica cuál: " + ", ".join(f"{t['team_id']} ({t['name']})" for t in eq))


# ---------------------------------------------------------------------- quién soy y qué veo
ESTADOS = {"to_prepare": "preparado (ya lo usa el chat)", "pending": "enviado a aprobación", "approved": "aprobado",
           "rejected": "devuelto", "processing": "preparándose", "failed": "con incidencia", "unprocessed": "sin archivo preparado",
           "abandoned": "abandonado"}


def quien_soy(s, perfil=None, cuentas=None) -> str:
    """19/11/2026: dice también QUÉ MCP es y con qué usuario entra, para que no haya dudas de a cuál se ha conectado Claude Code."""
    me = s.pedir("GET", "me")
    lineas = []
    if perfil:
        lineas.append(f"MCP: kortex · {'todas las herramientas (admin de la KB)' if perfil == 'admin' else 'herramientas de consulta'} (perfil {perfil})")
        for cuenta, usuario in (cuentas or {}).items():
            lineas.append(f"Sesión: {usuario or '—'}")
    nombre = me.get("label") or me.get("identity")
    email = me.get("email") or me.get("username")
    lineas.append(f"Usuario en la web: {nombre}" + (f" <{email}>" if email and email != nombre else "")
                  + (" · operador de plataforma" if me.get("platform_operator") else ""))
    for t in me.get("teams") or []:
        lineas.append(f"- Equipo {t['name']} ({t['team_id']}): roles {', '.join(t.get('roles') or []) or '—'}" + (" · propietario" if t.get("owner") else ""))
    f = me.get("features") or {}
    lineas.append("Activo en la API: " + ", ".join(k for k, v in f.items() if v) if any(f.values()) else "Sin funciones extra activas.")
    return "\n".join(lineas)


def equipos_y_carpetas(s, equipo=None) -> str:
    equipos = [t for t in _equipos(s) if not equipo or t["team_id"] == equipo]
    if not equipos:
        return "No ves ese equipo." if equipo else "Tu usuario no pertenece a ningún equipo."
    out = []
    for t in equipos:
        cols = (s.pedir("GET", f"teams/{t['team_id']}/collections") or {}).get("collections") or []
        out.append(f"Equipo {t['name']} ({t['team_id']}) · {len(cols)} carpetas")
        hijos = {}
        for c in cols:
            hijos.setdefault(c.get("parent_id"), []).append(c)
        def pinta(padre, nivel):
            for c in sorted(hijos.get(padre, []), key=lambda x: (x.get("position") or 0, str(x.get("name") or "").lower())):
                h = c.get("hpum") or {}
                proc = h.get("label") or h.get("name") or h.get("node_key") or ""
                out.append(f"{'  ' * nivel}- {c.get('name')} [{c['collection_id']}]" + (f" · HPUM: {_r(proc, 90)}" if proc else ""))
                pinta(c["collection_id"], nivel + 1)
        pinta(None, 1)
        huerfanas = [c for c in cols if c.get("parent_id") and c["parent_id"] not in {x["collection_id"] for x in cols}]
        for c in huerfanas:
            out.append(f"  - {c.get('name')} [{c['collection_id']}]")
    return "\n".join(out)


def documentos(s, equipo=None, carpeta=None, texto=None, estado=None, limite=50, cursor=None) -> str:
    team = _equipo(s, equipo)
    q = {"limit": str(max(1, min(int(limite or 50), 200))), "order": "name"}
    if carpeta:
        q.update(collection=carpeta, recursive="true")
    if texto:
        q["q"] = texto
    if estado:
        q["state"] = estado
    if cursor:
        q["cursor"] = cursor
    r = s.pedir("GET", f"teams/{team}/documents", params=q)
    items = r.get("items") or []
    out = [f"{r.get('total', len(items))} documentos en {team}" + (f" (carpeta {carpeta})" if carpeta else "") + f"; se muestran {len(items)}."]
    for i, d in enumerate(items, 1):
        st = d.get("status") or {}
        crudo = st.get("state") or d.get("state") or ""
        estado_doc = ESTADOS.get(crudo) or st.get("label") or crudo or st.get("stage") or ""
        # 19/11/2026: «uncertain» era la duda de la clasificación HPUM, que ya no existe: no se muestra
        out.append(f"{i}. {d.get('title_display') or d.get('name')} [{d['doc_id']}] · v{d.get('current_version') or '—'}"
                   + (f" · {estado_doc}" if estado_doc else ""))
    if r.get("next_cursor"):
        out.append(f"Hay más: vuelve a llamar con cursor=\"{r['next_cursor']}\".")
    return "\n".join(out)


# ---------------------------------------------------------------------- la consulta (POST /consulta)
def consultar(s, pregunta, colecciones=None, k=None, kb=True, notas=True) -> str:
    """POST /consulta: fragmentos de los documentos que la persona puede leer + lo que la KB sabe de lo preguntado (transversal). Lo
    transversal llega como hechos y, si la política autoriza fragmentos de otros equipos, como notas que Kortex ya ha redactado (nunca
    el texto original); notas=False las evita (son la única parte de la consulta que usa el modelo de Kortex)."""
    cuerpo = {"pregunta": pregunta}
    if colecciones:
        cuerpo["colecciones"] = list(colecciones)
    if k:
        cuerpo["k"] = int(k)
    if kb is False:
        cuerpo["kb"] = False
    if notas is False:
        cuerpo["notas"] = False
    r = s.pedir("POST", "consulta", cuerpo=cuerpo, ruta_nueva=True)
    frs = r.get("fragmentos") or []
    out = [f"Pregunta: {r.get('pregunta') or pregunta}",
           f"Documentos consultados: {r.get('documentos_consultados', '—')} · fragmentos: {len(frs)}"
           + (f" · coste {r['coste_usd']} USD" if r.get("coste_usd") is not None else "")]
    pan = r.get("panorama") or {}
    if pan:                                                   # pregunta panorámica («¿qué información tienes?»): sin fragmentos
        out.append("\n## Panorama de lo que puedes consultar")
        if pan.get("texto"):
            out.append(str(pan["texto"]).strip())
        for d in pan.get("documentos") or []:
            if isinstance(d, dict):
                desc = d.get("descripcion") or d.get("de_que_trata") or ""
                out.append(f"- {d.get('documento') or d.get('nombre') or d.get('name')} [{d.get('doc_id')}]"
                           + (f" · {d['carpeta']}" if d.get("carpeta") else "") + (f" — {_r(desc, 200)}" if desc else ""))
            else:
                out.append(f"- {d}")
    if frs:
        out.append("\n## Fragmentos de tu documentación (cita [n] y el doc_id)")
        if any(f.get("via") in ("kb", "cercano") for f in frs):
            out.append("(vía: documental = coincide con la pregunta · kb = llegó por un concepto de la KB · cercano = contiguo a otro fragmento)")
    for f in frs:
        donde = " · ".join(str(x) for x in (f.get("carpeta"), f"v{f['version']}" if f.get("version") else None, f.get("ubicacion")) if x)
        out.append(f"[{f.get('n')}] {f.get('documento')} [{f.get('doc_id')}]" + (f" · {donde}" if donde else "")
                   + (f" · vía {f['via']}" if f.get("via") and f.get("via") != "documental" else "")
                   + (f" · puntuación {f['puntuacion']:.2f}" if isinstance(f.get("puntuacion"), (int, float)) else ""))
        out.append("    " + str(f.get("texto") or "").strip().replace("\n", "\n    "))
    kbd = r.get("kb") or {}
    ents, rels, trans = kbd.get("entidades") or [], kbd.get("relaciones") or [], kbd.get("transversal") or []
    temas = kbd.get("temas_transversales") or []
    # Notas: el contrato es kb.notas_transversales ({nota, tema?, uso}). Mientras dure la sincronización con la PoC se aceptan también
    # las de su forma antigua, dentro de kb.transversal con clase «nota» ({texto, tema?, uso}), y no se repiten abajo.
    notas = [n for n in kbd.get("notas_transversales") or [] if (n.get("nota") if isinstance(n, dict) else n)]
    notas += [{"nota": t.get("texto"), "tema": t.get("tema"), "uso": t.get("uso")} for t in trans
              if isinstance(t, dict) and t.get("clase") == "nota" and t.get("texto")]
    trans = [t for t in trans if not (isinstance(t, dict) and t.get("clase") == "nota")]
    if ents or rels or trans or temas or notas:
        out.append("\n## Conocimiento transversal de la KB (a modo de información; no es documentación de tu equipo:"
                   " parafrasea, no lo cites como si fuera un documento)")
    if temas:
        out.append("Temas transversales: " + " · ".join(_r(t if isinstance(t, str) else (t.get("nombre") or t.get("tema") or t), 80) for t in temas))
    usos = set()
    if notas:                                                   # fragmentos de otros equipos, ya redactados por Kortex (sin origen)
        out.append("Notas de otras fuentes de Kortex (redactadas por Kortex; sin documento ni equipo de origen):")
        for n in notas:
            tema = n.get("tema") if isinstance(n, dict) else None
            out.append("- [nota] " + (f"{_r(tema, 80)}: " if tema else "") + _r(n.get("nota") if isinstance(n, dict) else n, 400))
            if isinstance(n, dict) and n.get("uso"):
                usos.add(str(n["uso"]))
        out.append("Cómo usar las notas: es lo que Kortex sabe por otros equipos. Explícalo con tus palabras, sin citarlo literalmente "
                   "ni atribuirlo a documentos, equipos o personas; solo los fragmentos [n] se citan con su documento.")
    for e in ents:
        extra = " · ".join(x for x in (", ".join(e.get("ambitos") or []), "HPUM: " + "; ".join(e["procesos_hpum"][:3]) if e.get("procesos_hpum") else "") if x)
        out.append(f"- {e.get('nombre')} [{e.get('tipo')}] ({e.get('id')})" + (f" · {extra}" if extra else ""))
        if e.get("descripcion"):
            out.append(f"    {_r(e['descripcion'], 300)}")
    for x in rels:
        cita = (x.get("citas") or [{}])[0]
        out.append(f"- {x.get('origen')} ─ {x.get('tipo')} ▸ {x.get('destino')}" + (f" · confianza {x['confianza']}" if x.get("confianza") else "")
                   + (f"\n    «{_r(cita.get('cita'), 240)}» — {cita.get('documento')}" if cita.get("cita") else ""))
    for t in trans:
        if t.get("uso"):
            usos.add(str(t["uso"]))
        if t.get("clase") == "pasaje":                          # texto redactado, sin documento ni equipo de origen
            out.append("- [pasaje] " + _r(t.get("texto") or t.get("detalle") or "", 600))
            continue
        resto = {k2: v for k2, v in t.items() if k2 not in ("clase", "procedencia", "detalle", "uso")}
        out.append(f"- [{t.get('clase')}] " + _r(" · ".join(f"{k2}: {v}" for k2, v in resto.items() if v), 260)
                   + (f" · procedencia: {t['procedencia']}" if t.get("procedencia") else "") + (f"\n    {_r(t['detalle'], 300)}" if t.get("detalle") else ""))
    for u in sorted(usos):
        out.append(f"Uso de lo transversal: {u}")
    for a in r.get("avisos") or []:
        txt = a if isinstance(a, str) else (a.get("mensaje") or a.get("codigo") or json.dumps(a, ensure_ascii=False))
        if "SIN_COINCIDENCIAS_CLARAS" in str(txt):
            txt = "SIN_COINCIDENCIAS_CLARAS: nada coincide claramente con la pregunta; lo de arriba es lo más cercano, úsalo con cautela."
        out.append(f"Aviso: {txt}")
    if not frs and not pan and not (ents or rels or trans or notas):
        out.append("No hay nada relevante en lo que puedes consultar.")
    return "\n".join(out)


def leer_documento(s, doc_id, desde=0, max=None) -> str:  # noqa: A002 — mismo nombre que el parámetro de la API
    desde = int(desde or 0)
    if desde < 0:
        raise ErrorKortex("«desde» no puede ser negativo.")
    q = {"desde": str(desde)}
    if max:
        if not 1 <= int(max) <= 200:
            raise ErrorKortex("«max» va de 1 a 200 segmentos por llamada.")
        q["max"] = str(int(max))
    r = s.pedir("GET", f"documents/{doc_id}/texto", params=q, ruta_nueva=True)
    segs = r.get("segmentos") or []
    out = [f"{r.get('nombre')} [{r.get('doc_id') or doc_id}] · {r.get('carpeta') or '—'} · v{r.get('version') or '—'}"
           f" · segmentos {segs[0]['i'] if segs else desde}–{segs[-1]['i'] if segs else desde} de {r.get('total_segmentos', '—')}"
           + (f" · lectura: {r['lectura']}" if r.get("lectura") else "")]
    for g in segs:
        cab = " · ".join(str(x) for x in (g.get("tipo"), g.get("ubicacion")) if x)
        out.append(f"\n[{g.get('i')}]" + (f" ({cab})" if cab else ""))
        out.append(str(g.get("texto") or "").rstrip())
    if r.get("siguiente") is not None:
        out.append(f"\n… sigue: leer_documento(doc_id=\"{doc_id}\", desde={r['siguiente']})")
    else:
        out.append("\n(fin del documento)")
    return "\n".join(out)


# ---------------------------------------------------------------------- el chat de la web (para comparar)
def descargar_original(s, doc_id, version=None, carpeta=None) -> str:
    d = s.pedir("GET", f"documents/{doc_id}")
    n = int(version or d.get("current_version") or 0)
    if not n:
        raise ErrorKortex("Ese documento no tiene una versión aprobada que puedas descargar.")
    url = s.pedir("GET", f"documents/{doc_id}/versions/{n}/download")["url"]
    destino = Path(carpeta).expanduser() if carpeta else config.descargas()
    destino.mkdir(parents=True, exist_ok=True)
    nombre = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", d.get("title_display") or d.get("name") or doc_id)[:150]
    f = destino / nombre
    with requests.get(url, stream=True, timeout=(10, 300)) as r:            # URL prefirmada de S3: sin cabecera de autorización
        if r.status_code != 200:
            raise ErrorKortex(f"No se pudo descargar el original ({r.status_code}); el enlace caduca en segundos, vuelve a intentarlo.")
        with open(f, "wb") as fh:
            for trozo in r.iter_content(1 << 16):
                fh.write(trozo)
    return f"Descargado «{d.get('title_display') or d.get('name')}» v{n} en {f} ({f.stat().st_size:,} bytes)".replace(",", ".")
