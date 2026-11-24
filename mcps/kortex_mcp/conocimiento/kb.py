"""Administración de la KB (campaña KORTEX) sobre la API de la web de la KB.

Lectura: la KB SERVIDA (la misma que pintan la web, el Excel y la IA) se descarga una vez por huella y se consulta en local.
Escritura: SIEMPRE como decisiones auditables (POST /decisiones), con autor = el usuario que hizo login. Lo masivo, lo destructivo y lo
que cuesta dinero va en DOS PASOS: la primera llamada previsualiza y devuelve un código; la segunda, con confirmar=<código>, ejecuta
exactamente lo previsualizado (caduca a los 15 minutos)."""
import datetime as dt
import hashlib
import json
import re
import secrets
import time
import unicodedata
from pathlib import Path

import requests

from . import config, ficha as FICHA, fichas_revision as FR
from .sesion import ErrorKortex

ACCIONES = {"APROBAR", "RECHAZAR", "CORREGIR_TIPO", "CORREGIR_NOMBRE", "FUSIONAR", "MANTENER_SEPARADAS"}
CRITERIOS = {"proceso_hpum", "tipo", "familia", "documento", "grupo_duplicados", "relaciones_tipo", "ids"}
CON_MOTIVO = {"RECHAZAR", "CORREGIR_TIPO", "CORREGIR_NOMBRE", "FUSIONAR"}
TOPE_BLOQUE = 2000
CADUCA_CODIGO = 15 * 60
_REV = {"APROBADA": "aprobada", "CORREGIDA": "corregida", "RECHAZADA": "rechazada", "FUSIONAR": "a fusionar", "SEPARADAS": "separadas"}


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _r(texto, n=300):
    t = re.sub(r"\s+", " ", str(texto or "")).strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def compacto(obj, n=4000) -> str:
    t = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)
    return t if len(t) <= n else t[: n - 40] + f"… (recortado; {len(t)} caracteres)"


def clase_de(oid: str) -> str:
    return "HPUM" if oid.startswith("HPUM|") else "DUP" if oid.startswith("DUP|") else "REL" if oid.startswith("REL-") else "ENT"


class KB:
    def __init__(self, sesion, campana=None, http=None, reloj=time.time):
        self.s = sesion
        self.cid = campana or config.cargar().campana
        self.http = http or requests.Session()
        self.reloj = reloj
        self._D = None          # (huella, servida)
        self._est = None        # (instante, respuesta de /estado)
        self._pend = {}         # código → operación previsualizada

    # ================================================================== lectura base
    def _p(self, sub=""):
        return f"campanas/{self.cid}" + (f"/{sub}" if sub else "")

    def estado(self, fresco=False) -> dict:
        if fresco or not self._est or self.reloj() - self._est[0] > 20:
            self._est = (self.reloj(), self.s.pedir("GET", self._p("estado")))
        return self._est[1]

    def revisado(self) -> dict:
        return self.estado().get("estado") or {}

    def servida(self) -> dict:
        ref = self.s.pedir("GET", self._p("servida"))
        huella = ref["huella"]
        if self._D and self._D[0] == huella:
            return self._D[1]
        cache = config.carpeta() / "cache"
        cache.mkdir(exist_ok=True)
        f = cache / f"servida_{self.cid}_{huella}.json"
        if f.exists():
            D = json.loads(f.read_text(encoding="utf-8"))
        else:
            r = self.http.get(ref["url"], timeout=(10, 120))            # URL prefirmada de S3: sin cabecera de autorización
            if r.status_code != 200:
                raise ErrorKortex(f"No se pudo descargar la KB servida ({r.status_code}).")
            D = r.json()
            f.write_text(json.dumps(D, ensure_ascii=False), encoding="utf-8")
            viejas = sorted(cache.glob(f"servida_{self.cid}_*.json"), key=lambda x: x.stat().st_mtime)[:-3]
            for v in viejas:                                            # se guardan las tres últimas
                v.unlink(missing_ok=True)
        self._D = (huella, D)
        self._foto(huella, D)
        return D

    def huella(self) -> str:
        self.servida()
        return self._D[0]

    # ---------------------------------------------------------------- índices sobre la servida
    def _idx(self):
        D = self.servida()
        if getattr(self, "_idx_h", None) != self._D[0]:
            g = D.get("grafo") or {}
            nodos = {n["id"]: n for n in g.get("nodos") or []}
            amb = {n["id"]: n.get("etiqueta") for n in nodos.values() if n.get("clase") == "AMBITO"}
            amb_de = {}
            for a in g.get("aristas") or []:
                if a.get("clase") == "AMBITO_ENTIDAD":
                    amb_de.setdefault(a["origen"], []).append(amb.get(a["destino"]) or a["destino"])
            self._ix = {"ent": {e["entidad_id"]: e for e in D.get("entidades") or []}, "rel": {r["relacion_id"]: r for r in D.get("relaciones") or []},
                        "doc": {d["doc_id"]: d for d in D.get("documentos") or []}, "nodos": nodos, "amb": amb, "amb_de": amb_de, "aristas": g.get("aristas") or []}
            self._idx_h = self._D[0]
        return self._ix

    def _nombre(self, oid):
        ix = self._idx()
        if oid in ix["ent"]:
            p = ((self.revisado().get(oid) or {}).get("parametros") or {})
            return p.get("nombre") or ix["ent"][oid].get("nombre")
        if oid in ix["doc"]:
            return ix["doc"][oid].get("nombre")
        n = ix["nodos"].get(oid)
        return (n or {}).get("etiqueta") or oid

    def _rev(self, oid):
        r = self.revisado().get(oid)
        if not r:
            return "pendiente"
        return _REV.get(r.get("estado"), str(r.get("estado")).lower()) + f" ({r.get('autor')}, {str(r.get('en') or '')[:10]})"

    def _doc(self, d):
        return (self._idx()["doc"].get(d) or {}).get("nombre") or d

    def _rel_linea(self, r):
        cita = next((e for e in r.get("evidencias") or [] if e.get("cita")), None)
        return (f"- {self._nombre(r['origen'])} ─ {r.get('tipo_id')} ▸ {self._nombre(r['destino'])} [{r['relacion_id']}] · {self._rev(r['relacion_id'])}"
                + (f" · {r['confianza']}" if r.get("confianza") else "")
                + (f"\n    «{_r(cita['cita'], 200)}» — {self._doc(cita.get('doc_id') or (r.get('documentos') or [''])[0])}" if cita else ""))

    # ================================================================== herramientas de lectura
    def estado_kb(self) -> str:
        est = self.estado(fresco=True)
        meta = self.s.pedir("GET", self._p())
        D = self.servida()
        res, srv = D.get("resumen") or {}, est.get("servida") or {}
        out = [f"KB {self.cid} · versión (huella) {est.get('huella')} · {D.get('estado')} · {D.get('fecha')}",
               f"Contenido: {len(D.get('entidades') or [])} entidades, {len(D.get('relaciones') or [])} relaciones, {len(D.get('documentos') or [])} documentos"
               + (f" · modelo {D['modelo'].get('id')}" if isinstance(D.get("modelo"), dict) else ""),
               "Revisión: " + compacto(est.get("resumen") or meta.get("resumen_revision") or {}, 600)]
        if D.get("observaciones"):
            out.append("Observaciones: " + compacto(D["observaciones"], 500))
        fu = D.get("fuentes") or {}
        if fu:
            out.append(f"Fuentes: {fu.get('origen')} · base {((fu.get('base') or {}).get('fichero'))} · ingesta actualizada "
                       f"{((fu.get('ingesta') or {}).get('actualizada_en'))} ({((fu.get('ingesta') or {}).get('documentos'))} documentos)")
        if srv:
            out.append("Servida: " + compacto(srv, 400))
        if res:
            out.append("Resumen: " + compacto(res, 600))
        return "\n".join(out)

    def buscar_entidades(self, texto="", tipo=None, ambito=None, estado=None, limite=25) -> str:
        ix, q = self._idx(), norm(texto)
        filas = []
        for e in ix["ent"].values():
            nombres = [e.get("nombre"), *(e.get("alias") or []), *(e.get("nombres_observados") or [])]
            ns = [norm(x) for x in nombres if x]
            if q:
                if any(n == q for n in ns):
                    p = 3
                elif any(n.startswith(q) for n in ns):
                    p = 2
                elif any(q in n for n in ns) or all(w in " ".join(ns) for w in q.split()):
                    p = 1
                else:
                    continue
            else:
                p = 0
            if tipo and norm(tipo) not in (norm(e.get("tipo_id")), norm(e.get("familia"))):
                continue
            ambs = ix["amb_de"].get(e["entidad_id"]) or []
            if ambito and not any(norm(ambito) in norm(a) for a in ambs):
                continue
            rv = self._rev(e["entidad_id"])
            if estado and not rv.startswith(norm(estado)[:6]):
                continue
            filas.append((-p, -len(e.get("documentos") or []), norm(e.get("nombre")), e, ambs, rv))
        filas.sort(key=lambda x: x[:3])
        out = [f"{len(filas)} entidades" + (f" para «{texto}»" if texto else "") + (f"; se muestran {min(len(filas), limite)}" if len(filas) > limite else "")]
        for _, _, _, e, ambs, rv in filas[:limite]:
            out.append(f"- {self._nombre(e['entidad_id'])} [{e.get('tipo_id')}] ({e['entidad_id']}) · {len(e.get('documentos') or [])} docs · {rv}"
                       + (f" · {', '.join(ambs[:3])}" if ambs else "") + (f" · alias: {', '.join((e.get('alias') or [])[:3])}" if e.get("alias") else ""))
        return "\n".join(out)

    def entidad(self, id_) -> str:
        ix = self._idx()
        e = ix["ent"].get(id_)
        if not e:
            raise ErrorKortex(f"No hay ninguna entidad «{id_}» en la KB servida (usa buscar_entidades).")
        rels = [r for r in ix["rel"].values() if id_ in (r["origen"], r["destino"])]
        out = [f"{self._nombre(id_)} ({id_})", f"Tipo {e.get('tipo_id')} · familia {e.get('familia')} · confianza {e.get('confianza')} · estado KB {e.get('estado')} · revisión: {self._rev(id_)}"]
        if e.get("alias"):
            out.append("Alias: " + " · ".join(e["alias"]))
        if ix["amb_de"].get(id_):
            out.append("Ámbitos: " + " · ".join(ix["amb_de"][id_]))
        for d in (e.get("descripciones") or [])[:3]:
            out.append(f"Descripción: {_r(d.get('texto'), 400)}" + (f" — {self._doc(d['doc_id'])}" if d.get("doc_id") else ""))
        for c in (e.get("correspondencias_hpum") or [])[:8]:
            out.append(f"HPUM: {c.get('ruta') or c.get('nodo_id')} · {c.get('estado') or ''} · revisión {self._rev('HPUM|' + id_ + '|' + str(c.get('nodo_id')))}")
        out.append(f"Documentos ({len(e.get('documentos') or [])}): " + " · ".join(self._doc(d) for d in (e.get("documentos") or [])[:12]))
        for m in [m for m in e.get("menciones") or [] if (m.get("evidencia") or {}).get("cita")][:3]:
            out.append(f"Mención: «{_r(m['evidencia']['cita'], 220)}» — {self._doc(m.get('doc_id'))}")
        if e.get("preguntas_abiertas"):
            out.append("Preguntas abiertas: " + compacto(e["preguntas_abiertas"], 400))
        out.append(f"\nRelaciones ({len(rels)}):")
        out += [self._rel_linea(r) for r in rels[:25]]
        if len(rels) > 25:
            out.append(f"… y {len(rels) - 25} más (usa relaciones(entidad=\"{id_}\"))")
        return "\n".join(out)

    def relaciones(self, entidad=None, tipo=None, estado=None, documento=None, limite=40) -> str:
        ix = self._idx()
        rs = []
        for r in ix["rel"].values():
            if entidad and entidad not in (r["origen"], r["destino"]):
                continue
            if tipo and norm(tipo) != norm(r.get("tipo_id")):
                continue
            if documento and documento not in (r.get("documentos") or []) and norm(documento) not in " ".join(norm(self._doc(d)) for d in r.get("documentos") or []):
                continue
            if estado and not self._rev(r["relacion_id"]).startswith(norm(estado)[:6]):
                continue
            rs.append(r)
        out = [f"{len(rs)} relaciones" + (f"; se muestran {limite}" if len(rs) > limite else "")]
        return "\n".join(out + [self._rel_linea(r) for r in rs[:limite]])

    def por_que(self, id_) -> str:
        """Por qué existe un elemento en la KB: evidencias, reglas, motivos de confianza y decisiones del equipo."""
        ix = self._idx()
        out = []
        if id_ in ix["rel"]:
            r = ix["rel"][id_]
            out += [f"Relación {self._nombre(r['origen'])} ─ {r.get('tipo_id')} ▸ {self._nombre(r['destino'])}",
                    f"Estado en la KB: {r.get('estado')} · confianza {r.get('confianza')} · fuentes {compacto(r.get('fuentes'), 120)} · revisión: {self._rev(id_)}"]
            for e in (r.get("evidencias") or [])[:6]:
                out.append(f"- «{_r(e.get('cita'), 300)}» — {self._doc(e.get('doc_id') or (r.get('documentos') or [''])[0])} ({e.get('fuente')}, {e.get('coincidencia')})")
            out += [f"- Motivo: {m}" for m in r.get("confianza_motivos") or []]
        elif id_ in ix["ent"]:
            e = ix["ent"][id_]
            out += [f"Entidad {self._nombre(id_)} [{e.get('tipo_id')}]",
                    f"Origen: {e.get('origen_dato')} · base: {compacto(e.get('origen_base'), 160)} · confianza {e.get('confianza')} (base {e.get('confianza_base')}) · revisión: {self._rev(id_)}"]
            out += [f"- Motivo: {m}" for m in e.get("confianza_motivos") or []]
            for m in [m for m in e.get("menciones") or [] if (m.get("evidencia") or {}).get("cita")][:5]:
                out.append(f"- «{_r(m['evidencia']['cita'], 260)}» — {self._doc(m.get('doc_id'))}")
            if e.get("decisiones_base"):
                out.append("Decisiones de la base: " + compacto(e["decisiones_base"], 500))
            if e.get("avisos"):
                out.append("Avisos: " + compacto(e["avisos"], 300))
        elif id_.startswith("HPUM|"):
            _, o, d = id_.split("|", 2)
            a = next((x for x in ix["aristas"] if x.get("clase") == "CORRESPONDENCIA_HPUM" and x["origen"] == o and x["destino"] == d), None)
            if not a:
                raise ErrorKortex("No existe esa correspondencia con HPUM en la KB servida.")
            out += [f"{self._nombre(o)} ↔ HPUM {self._nombre(d)} · {a.get('estado')} · regla {a.get('regla')} · revisión: {self._rev(id_)}"]
            out += [f"- {j.get('texto')}" + (f" — {self._doc(j['doc_id'])}" if j.get("doc_id") else "") for j in a.get("justificaciones") or []]
            out += [f"- Motivo: {m}" for m in a.get("confianza_motivos") or []]
        else:
            raise ErrorKortex(f"No reconozco «{id_}»: pasa el id de una entidad, de una relación (REL-…) o HPUM|entidad|nodo.")
        decs = [d for d in self.historial_bruto() if id_ in ((d.get("bloque") or {}).get("valor") or []) or d.get("propuesta_id") == id_]
        if decs:
            out.append("Decisiones del equipo:")
            out += [f"- {d.get('en') or d.get('sk', '')[:20]} {d.get('autor')}: {d.get('accion')} · {d.get('estado')} · {_r(d.get('motivo'), 160)}" for d in decs[:8]]
        return "\n".join(out)

    def documento_en_kb(self, documento) -> str:
        ix = self._idx()
        d = ix["doc"].get(documento) or next((x for x in ix["doc"].values() if norm(documento) in norm(x.get("nombre"))), None)
        if not d:
            raise ErrorKortex(f"Ese documento no está en la KB servida: «{documento}».")
        did = d["doc_id"]
        ents = [e for e in ix["ent"].values() if did in (e.get("documentos") or [])]
        rels = [r for r in ix["rel"].values() if did in (r.get("documentos") or [])]
        out = [f"{d.get('nombre')} ({did}) · estado {d.get('estado')} · lectura {d.get('estado_lectura')} · {d.get('ubicacion') or ''}",
               "Clasificación: " + compacto(d.get("clasificacion"), 400)]
        if d.get("procesos_citados"):
            out.append("Procesos citados: " + compacto(d["procesos_citados"], 400))
        if d.get("advertencias"):
            out.append("Advertencias: " + compacto(d["advertencias"], 300))
        if d.get("rechazos"):
            out.append(f"Descartes de la extracción: {len(d['rechazos']) if isinstance(d['rechazos'], list) else d['rechazos']}")
        out.append(f"\nEntidades ({len(ents)}): " + " · ".join(f"{self._nombre(e['entidad_id'])} [{e.get('tipo_id')}]" for e in ents[:60]))
        out.append(f"\nRelaciones ({len(rels)}):")
        out += [self._rel_linea(r) for r in rels[:30]]
        return "\n".join(out)

    def ambito(self, ambito) -> str:
        ix = self._idx()
        aid = ambito if ambito in ix["amb"] else next((k for k, v in ix["amb"].items() if norm(ambito) in norm(v)), None)
        if not aid:
            return "Ámbitos de la KB: " + " · ".join(f"{v} ({k})" for k, v in ix["amb"].items())
        ents = [e for e in ix["ent"].values() if ix["amb"][aid] in (ix["amb_de"].get(e["entidad_id"]) or [])]
        docs = [a["origen"] for a in ix["aristas"] if a.get("clase") == "CLASIFICACION_AMBITO" and a["destino"] == aid]
        por_tipo = {}
        for e in ents:
            por_tipo.setdefault(e.get("tipo_id"), []).append(self._nombre(e["entidad_id"]))
        out = [f"Ámbito {ix['amb'][aid]} ({aid}) · {len(ents)} entidades · {len(docs)} documentos clasificados"]
        n = ix["nodos"].get(aid) or {}
        if (n.get("propiedades") or {}).get("descripcion"):
            out.append(_r(n["propiedades"]["descripcion"], 400))
        for t, ns in sorted(por_tipo.items(), key=lambda x: -len(x[1])):
            out.append(f"- {t} ({len(ns)}): " + ", ".join(sorted(ns)[:25]) + (" …" if len(ns) > 25 else ""))
        out.append("Documentos: " + " · ".join(self._doc(d) for d in docs[:20]) + (" …" if len(docs) > 20 else ""))
        return "\n".join(out)

    def contexto(self, entidad=None, ambito=None, formato="json", carpeta=None) -> str:
        if not (entidad or ambito):
            raise ErrorKortex("Indica entidad o ámbito.")
        q = {"entidad": entidad} if entidad else {"ambito": ambito}
        if formato == "csv":
            r = self.s.pedir("GET", self._p("contexto"), params={**q, "formato": "csv"}, crudo=True)
            f = Path(carpeta).expanduser() if carpeta else config.descargas()
            f.mkdir(parents=True, exist_ok=True)
            f = f / f"contexto_{re.sub(r'[^A-Za-z0-9_-]', '_', entidad or ambito)}.csv"
            f.write_bytes(r.content)
            return f"Contexto guardado en {f} (CSV con «;», el mismo que da la web para Excel)."
        return compacto(self.s.pedir("GET", self._p("contexto"), params=q), 12000)

    def metricas(self) -> str:
        est = self.estado(fresco=True)
        c = self.s.pedir("GET", self._p("consolidacion"))
        out = [f"KB {self.cid} · huella {est.get('huella')}", "Revisión: " + compacto(est.get("resumen"), 800),
               "Salud (agentes de consolidación): " + compacto(c.get("salud"), 1500),
               "Calibración (aciertos de los agentes según lo decidido): " + compacto(c.get("calibracion"), 600)]
        hist = [h for h in c.get("historico") or [] if h]
        if hist:
            out.append("Evolución: " + " | ".join(f"{str(h.get('en'))[:10]}: {compacto({k: v for k, v in h.items() if k != 'en'}, 160)}" for h in hist[-5:]))
        return "\n".join(out)

    # ---------------------------------------------------------------- «lo nuevo desde»: fotos locales por huella
    def _fotos(self):
        p = config.carpeta() / "revisiones" / self.cid
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _foto(self, huella, D, marca=False):
        f = self._fotos() / f"{huella}.json"
        if not f.exists() or marca:
            datos = {"huella": huella, "fecha": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "marca": marca,
                     "entidades": {e["entidad_id"]: e.get("nombre") for e in D.get("entidades") or []},
                     "relaciones": {r["relacion_id"]: f"{r['origen']}|{r.get('tipo_id')}|{r['destino']}" for r in D.get("relaciones") or []},
                     "documentos": {d["doc_id"]: d.get("nombre") for d in D.get("documentos") or []}}
            if f.exists() and not marca:
                return
            f.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")

    def marcar_revision(self) -> str:
        D = self.servida()
        self._foto(self._D[0], D, marca=True)
        return f"Marcada la versión {self._D[0]} como revisada: «lo_nuevo_desde» sin fecha comparará con esta."

    def lo_nuevo_desde(self, fecha=None) -> str:
        D = self.servida()
        actual = self._D[0]
        fotos = []
        for f in self._fotos().glob("*.json"):
            try:
                fotos.append(json.loads(f.read_text(encoding="utf-8")))
            except ValueError:
                continue
        fotos.sort(key=lambda x: x["fecha"])
        if fecha:
            base = next((x for x in reversed(fotos) if x["fecha"][:len(fecha)] <= fecha and x["huella"] != actual), None)
        else:
            base = next((x for x in reversed(fotos) if x.get("marca") and x["huella"] != actual), None) or \
                next((x for x in reversed(fotos) if x["huella"] != actual), None)
        desde = fecha or (base or {}).get("fecha")
        decs = [d for d in self.historial_bruto() if desde and str(d.get("sk") or d.get("en") or "") >= desde] if desde else []
        out = []
        if not base:
            out.append("No tengo una foto anterior de la KB en este puesto (se guarda una cada vez que la consultas; usa marcar_revision tras revisar).")
        else:
            ahora = {"entidades": {e["entidad_id"]: e.get("nombre") for e in D.get("entidades") or []},
                     "relaciones": {r["relacion_id"]: f"{r['origen']}|{r.get('tipo_id')}|{r['destino']}" for r in D.get("relaciones") or []},
                     "documentos": {d["doc_id"]: d.get("nombre") for d in D.get("documentos") or []}}
            out.append(f"Cambios desde la versión {base['huella'][:12]} ({base['fecha']}) hasta la actual {actual[:12]}:")
            for k in ("documentos", "entidades", "relaciones"):
                nuevos = [x for x in ahora[k] if x not in base[k]]
                idos = [x for x in base[k] if x not in ahora[k]]
                out.append(f"- {k}: +{len(nuevos)} / −{len(idos)}")
                for x in nuevos[:15]:
                    out.append(f"    + {self._nombre(x) if k != 'relaciones' else self._rel_corta(x)} ({x})")
                for x in idos[:8]:
                    out.append(f"    − {base[k][x]} ({x})")
        if decs:
            out.append(f"Decisiones en ese periodo: {len(decs)}")
            out += [f"- {str(d.get('en') or d.get('sk'))[:16]} {d.get('autor')}: {d.get('accion')} ({d.get('n_objetos')} obj.) · {d.get('estado')}" for d in decs[:15]]
        return "\n".join(out)

    def _rel_corta(self, rid):
        r = self._idx()["rel"].get(rid)
        return f"{self._nombre(r['origen'])} ─ {r.get('tipo_id')} ▸ {self._nombre(r['destino'])}" if r else rid

    # ---------------------------------------------------------------- ficha HTML
    def ficha_html(self, id_, saltos=1, carpeta=None) -> str:
        D = self.servida()
        try:
            m = FICHA.construir_ficha(D, self.revisado(), id_, saltos=2 if int(saltos or 1) > 1 else 1, huella=self._D[0])
        except KeyError:
            raise ErrorKortex(f"«{id_}» no está en la KB servida (entidad, proceso HPUM, documento o ámbito).") from None
        dest = Path(carpeta).expanduser() if carpeta else config.descargas()
        dest.mkdir(parents=True, exist_ok=True)
        f = dest / FICHA.nombre_fichero(m)
        f.write_text(FICHA.documento_ficha(m), encoding="utf-8")
        k = m["kpis"]
        return (f"Ficha guardada en {f}\n{m['raiz']['nombre']} · {m['raiz']['tipo']} · {k['directas']} relaciones directas, {k['entidades']} entidades, "
                f"{k['hpum']} procesos HPUM, {k['documentos']} documentos, {k['pendientes']} por revisar.")

    # ---------------------------------------------------------------- fichas de conocimiento (A: PENDIENTE_VALIDAR · B: el resto de estados · completa de una entidad)
    def _registro(self):
        return FR.Registro(config.carpeta() / "fichas_revision" / self.cid)

    def _ix_fichas(self):
        self._est = None                                   # la revisión humana, siempre la del momento
        D = self.servida()
        return FR.Indice(D, self.revisado())

    def generar_fichas_revision(self, modo=None, ambito=None, entidad=None, carpeta=None) -> str:
        ix = self._ix_fichas()
        dest = Path(carpeta).expanduser() if carpeta else config.descargas() / "fichas_revision"
        try:
            lote, cob, fichas = FR.generar(ix, modo, self._D[0], self.cid, self._registro(), dest, ambito, entidad)
        except FR.ErrorFicha as e:
            raise ErrorKortex(str(e)) from None
        f, E, R = cob["filtro"], cob["entidades"], cob["relaciones"]
        humanas = sum(1 for m in fichas for i in m["items"] if i["revision_estado"])
        alcance = " · ".join(x for x in [f"ámbito {f['ambito']}" if f.get("ambito") else "",
                                         f"entidad {f['entidad']} ({', '.join(f['entidades'][:8])})" if f.get("entidad") else ""] if x)
        out = [f"Fichas {FR.CORTO[cob['modo']]} · {FR.MODOS[cob['modo']]} · KB {self.cid} versión {cob['huella']}",
               "Alcance: " + (alcance or "toda la KB"),
               f"A revisar: {E['a_revisar']} entidades (de {E['total_kb']}; por confianza {compacto(E['por_confianza'], 120)}) y {R['a_revisar']} relaciones "
               f"(de {R['total_kb']}; {compacto(R['por_confianza'], 120)}), en {sum(len(m['tarjetas']) for m in fichas)} tarjetas de entidad y {len(fichas)} fichas",
               f"Cobertura: perdidas {len(E['perdidas'])} entidades y {len(R['perdidas'])} relaciones · repetidas {len(E['repetidas'])} y {len(R['repetidas'])} · "
               f"cada relación se revisa una sola vez ({R['referencias_a_otra_tarjeta']} aparecen además como referencia en la otra entidad)",
               f"Solo como contexto: {E['solo_contexto']} entidades y {R['solo_contexto']} relaciones · fuera del lote: {E['fuera_del_lote']} entidades y "
               f"{R['fuera_del_lote']} relaciones · entidades a revisar sin relaciones: {cob['entidades_sin_relaciones_a_revisar']}",
               f"Con decisión de una persona: {humanas} (solo VALIDADO es definitivo: lo pone una persona; lo demás está pendiente)",
               f"Carpeta: {lote}", f"Índice: {lote / 'indice.html'} · cobertura: {lote / 'cobertura.json'}", "Fichas:"]
        for m in fichas:
            ne = sum(1 for i in m["items"] if i["clase"] == "ENT")
            nr = sum(1 for i in m["items"] if i["clase"] == "REL")
            out.append(f"- {m['ficha_id']} · {m['titulo']} · {len(m['tarjetas'])} tarjetas · {ne} entidades y {nr} relaciones a revisar · {Path(m['fichero']).name}")
        out.append("Cada ficha se responde sin conexión y descarga un JSON de respuestas; impórtalo con importar_respuestas_ficha.")
        return "\n".join(out)

    def importar_respuestas_ficha(self, ficheros) -> str:
        rutas = []
        for x in ([ficheros] if isinstance(ficheros, str) else ficheros or []):
            p = Path(str(x)).expanduser()
            rutas += sorted(p.glob("respuestas_*.json")) if p.is_dir() else [p]
        if not rutas:
            raise ErrorKortex("Indica el fichero (o la carpeta) con las respuestas descargadas de la ficha (respuestas_FR-….json).")
        ix, reg, usuario = self._ix_fichas(), self._registro(), self.s.usuario() or "admin"
        out = []
        for p in rutas:
            try:
                imp = FR.importar(p.read_text(encoding="utf-8"), reg, ix, self._D[0], usuario, nombre_fichero=str(p))
            except OSError as e:
                out.append(f"✗ {p.name}: no se puede leer ({type(e).__name__}).")
                continue
            except FR.ErrorFicha as e:
                out.append(f"✗ {p.name}: {e}")
                continue
            reg.guardar_importacion(imp)
            out.append(self._informe_importacion(imp, ix))
        out.append("\nNada se ha cambiado en la KB. Para ver las decisiones que habría que guardar: previsualizar_correcciones_ficha(importacion=…).")
        return "\n".join(out)

    def _informe_importacion(self, imp, ix) -> str:
        res = FR.resumen_importacion(imp)
        rv = imp["revisor_declarado"]
        lin = [f"\n✓ {imp['importacion_id']} · ficha {imp['ficha_id']} ({imp['ficha_titulo']})",
               f"Revisor DECLARADO en el fichero (sin acreditar): {rv.get('nombre') or '—'} · {rv.get('correo') or '—'} · ámbito {rv.get('ambito') or '—'}",
               f"Importado por (usuario autenticado): {imp['importada_por']} · {imp['importada_en']}"]
        lin += [f"Aviso: {a}" for a in imp["avisos"]]
        e, r = res["ENT"], res["REL"]
        if sum(e.values()):
            lin.append(f"Entidades: confirmadas {e['CORRECTA']} · nombre a corregir {e['CORREGIR_NOMBRE']} · tipo a corregir {e['CORREGIR_TIPO']} · "
                       f"duplicadas {e['DUPLICADO']} · rechazadas {e['INCORRECTA']} · sin información {e['SIN_INFORMACION']} · fuera de su ámbito "
                       f"{e['FUERA_DE_AMBITO']} · sin revisar {e['SIN_REVISAR']}")
        lin.append(f"Relaciones: confirmadas {r['CORRECTA']} (de golpe {res['en_grupo']}) · rechazadas {r['INCORRECTA']} · a matizar {r['PARCIAL']} · "
                   f"otro tipo {r.get('OTRO_TIPO', 0)} · dirección al revés {r.get('DIRECCION', 0)} · sin información {r['SIN_INFORMACION']} · fuera de su ámbito "
                   f"{r['FUERA_DE_AMBITO']} · sin revisar {r['SIN_REVISAR']} · aportaciones {res['aportaciones']} · errores de contexto {res['contexto']}")
        cambios = [i for i in imp["items"] if i["respuesta"] in FR.CON_CAMBIO]
        if cambios:
            lin.append("Con cambios propuestos:")
            for i in cambios[:25]:
                datos = "".join(f" · {k.replace('_', ' ')}: {_r(i[k], 120)}" for k in ("nombre_nuevo", "tipo_nuevo", "duplicado_de", "motivo", "correccion") if i.get(k))
                lin.append(f"  - [{i['clase']}] {ix.describir(i['objeto'], i['clase'])} · {FR.RESP[i['clase']][i['respuesta']]}{datos}")
        conf = [i for i in imp["items"] if i["estado"] != "OK"]
        lin.append(f"Conflictos y obsoletas: {len(conf)}" + (" · " + compacto(res["estados"], 120) if conf else ""))
        lin += [f"  - [{i['clase']}] {ix.describir(i['objeto'], i['clase'])} · {i['estado']}: {'; '.join(i['notas'])}" for i in conf[:20]]
        coinc = [i for i in imp["items"] if any(n.startswith("coincide con") for n in i["notas"])]
        if coinc:
            lin.append(f"Coinciden con otras revisiones: {len(coinc)}")
        f = FR.plan(imp, ix, acreditacion="simulación: revisor acreditado")["filas"]
        n = {k: len(v) for k, v in f.items()}
        lin.append(f"Cambios que serían necesarios SI se acredita al revisor: aprobar {n['aprobar']} · rechazar {n['rechazar']} · corregir nombre "
                   f"{n['corregir_nombre']} · corregir tipo {n['corregir_tipo']} · invertir {n['invertir']} · otro tipo de relación "
                   f"{n['corregir_relacion']} · fusionar {n['fusionar']} · por interpretar (matices: Claude propone la operación buena) "
                   f"{n['por_interpretar']} · excluidas {n['excluidas']} · sin cambio {n['sin_cambio'] + n['fuera_ambito']}")
        return "\n".join(lin)

    def previsualizar_correcciones_ficha(self, importacion, acreditacion=None, ambito_acreditado=None, operaciones_adicionales=None) -> str:
        """23/11/2026: lo que dicen las fichas se traduce a OPERACIONES (kbweb_operaciones) y se previsualiza con la KB servida real
        antes/después. Lo correcto se valida; lo falso se rechaza; dirección, otro tipo y duplicado se aplican; los matices quedan
        «por interpretar» con sugerencias: Claude propone la operación buena y la pasa en operaciones_adicionales."""
        reg, ix = self._registro(), self._ix_fichas()
        ids = [importacion] if isinstance(importacion, str) else list(importacion or [])
        if not ids:
            raise ErrorKortex("Indica la importación (IMP-…) que devolvió importar_respuestas_ficha.")
        ops, out, sin_acreditar, acreditadas, por_interp = [], [], 0, [], []
        secciones = (("aprobar", "Se validan (lo confirma el revisor)"), ("rechazar", "Se rechazan (sin borrar: reversible)"),
                     ("corregir_nombre", "Se corrige el nombre"), ("corregir_tipo", "Se corrige el tipo"),
                     ("invertir", "Se invierte la relación (la dirección estaba al revés)"), ("corregir_relacion", "Se cambia el tipo de la relación"),
                     ("fusionar", "Se fusionan (el revisor dice que son la misma entidad)"),
                     ("pendiente_acreditar", "Pendientes de acreditar al revisor (no se escribe nada)"), ("excluidas", "Excluidas"),
                     ("fuera_ambito", "Fuera del ámbito del revisor (sin cambio)"), ("aportaciones", "Aportaciones del revisor (no son evidencia documental)"),
                     ("observaciones_contexto", "Errores señalados en elementos de contexto (para revisar)"))
        for iid in ids:
            imp = reg.importacion(iid)
            if not imp:
                raise ErrorKortex(f"No hay ninguna importación «{iid}» en este puesto (mira fichas_revision).")
            p = FR.plan(imp, ix, acreditacion, ambito_acreditado)
            f = p["filas"]
            sin_acreditar += len(f["pendiente_acreditar"])
            if p["acreditado"]:
                acreditadas.append(iid)
            rd = p["revisor_declarado"]
            out.append(f"{iid} · ficha {imp['ficha_id']} · revisor declarado {rd.get('nombre') or rd.get('correo') or '—'}"
                       + (f" · ACREDITADO por {p['importada_por']}" if p["acreditado"] else " · SIN ACREDITAR")
                       + (f" · ámbito acreditado {p['ambito_acreditado']}" if p["ambito_acreditado"] else ""))
            for k, t in secciones:
                xs = f[k]
                if not xs:
                    continue
                out.append(f"{t}: {len(xs)}")
                for x in xs[:25]:
                    det = self._detalle_fila(x)
                    out.append(f"  - [{x.get('clase') or '—'}] {x['descripcion']} [{x['objeto']}]" + (f" · {_r(det, 220)}" if det else ""))
                if len(xs) > 25:
                    out.append(f"  … y {len(xs) - 25} más")
            por_interp += [{**x, "_imp": iid} for x in f["por_interpretar"]]
            out.append(f"Sin cambio (sin revisar o sin información): {len(f['sin_cambio'])}")
            ops += p["operaciones"]
        if por_interp:
            out.append(f"\nPOR INTERPRETAR ({len(por_interp)}): el revisor matiza o dice qué es lo correcto. Tradúcelo a operaciones y vuelve a "
                       "llamar con operaciones_adicionales=[…] (lo que afirma el revisor entra VALIDADO). Si el comentario no da para una "
                       "operación concreta, déjalo pendiente y dilo:")
            for x in por_interp[:40]:
                out.append(f"  - [{x['clase']}] {x['descripcion']} [{x['objeto']}] · respuesta: {x['respuesta']}"
                           + (" · (ya se rechaza)" if x.get("ya_se_rechaza") else "") + f" · comentario: «{_r(x.get('comentario'), 300)}»")
                if x.get("entidades_nombradas"):
                    out.append("      entidades que nombra: " + "; ".join(f"{e['nombre']} ({e['tipo']}) [{e['id']}]" for e in x["entidades_nombradas"]))
                if x.get("relaciones"):
                    out.append("      sus relaciones: " + "; ".join(f"{r['texto']} [{r['id']}]" for r in x["relaciones"][:8]))
                for g in x.get("sugerencias") or []:
                    out.append(f"      sugerencia: {compacto({k: v for k, v in g.items() if not k.startswith('_')}, 260)}"
                               + (f"  → {g['_lectura']}" if g.get("_lectura") else ""))
            if len(por_interp) > 40:
                out.append(f"  … y {len(por_interp) - 40} más")
        extra = [x for x in (operaciones_adicionales or []) if isinstance(x, dict)]
        if extra and not acreditadas:
            raise ErrorKortex("Las operaciones adicionales salen de lo que dice el revisor: acredítalo antes (acreditacion=…).")
        extra = [{**{k: v for k, v in x.items() if not str(k).startswith("_")}, "motivo": x.get("motivo") or "según el comentario del revisor"} for x in extra]
        todas = ops + extra
        if not todas:
            motivo = ("falta acreditar al revisor (pasa acreditacion= con cómo se ha comprobado su identidad y competencia)" if sin_acreditar
                      else "no hay nada aplicable" + (" salvo lo POR INTERPRETAR" if por_interp else ""))
            return "\n".join(out + [f"\nNo hay operaciones que guardar: {motivo}. Nada se ha cambiado."])
        motivo = FR.limpio(f"Fichas {', '.join(acreditadas)} · acreditación: {acreditacion}", 500)
        origen = {"importaciones": ",".join(acreditadas), "via": "fichas_revision"}
        pv = self._previsualizar_ops(todas, motivo, origen)
        out.append("")
        out.append(pv)
        if extra:
            out.append(f"Incluye {len(extra)} operaciones interpretadas de los comentarios del revisor.")
        return self._codigo("fichas", {"operaciones": todas, "motivo": motivo, "origen": origen, "importaciones": acreditadas},
                            "\n".join(out) + "\nSe aplican con aplicar_correcciones_ficha(confirmar=<código>).")

    @staticmethod
    def _detalle_fila(x) -> str:
        if x.get("motivo_exclusion"):
            return x["motivo_exclusion"]
        if x.get("texto"):
            return x["texto"]
        if x.get("aportacion"):
            return x["aportacion"]
        if x.get("otra"):
            return f"se fusiona en «{x['otra']}»"
        if x.get("nuevo"):
            return f"→ {x['nuevo']}"
        return " · ".join(v for v in (x.get("tipo_nuevo"), x.get("motivo"), x.get("correccion"), x.get("observaciones")) if v)

    def aplicar_correcciones_ficha(self, confirmar) -> str:
        datos = self._confirmado("fichas", confirmar)
        r = self._aplicar_ops(datos["operaciones"], datos["motivo"], datos["origen"])
        reg = self._registro()
        for iid in datos.get("importaciones") or []:
            imp = reg.importacion(iid)
            if imp:
                imp.setdefault("aplicaciones", []).append({"lote": r.get("lote"), "decisiones": [h["sk"] for h in r.get("hechas") or []], "en": FR.ahora_iso()})
                imp["estado"] = "APLICADA" if r.get("estado") == 201 else "APLICADA_EN_PARTE"
                reg.guardar_importacion(imp)
        return self._texto_aplicado(r)

    # ================================================================== operaciones directas (23/11/2026): lo mismo que tocando AWS
    def _previsualizar_ops(self, operaciones, motivo, origen=None) -> str:
        pv = self.s.pedir("POST", self._p("operaciones"), cuerpo={"operaciones": operaciones, "motivo": motivo, "origen": origen or {}, "previsualizar": True},
                          ruta_nueva=True)
        res = pv.get("resumen") or {}
        lin = [f"Previsualización ({len(operaciones)} operaciones → {len(pv.get('decisiones') or [])} decisiones) · KB {pv.get('huella_antes')} → {pv.get('huella_despues')}",
               "Resultado: " + " · ".join(f"{k.replace('_', ' ')} {v}" for k, v in res.items() if v) if any(res.values()) else "Resultado: sin cambios"]
        for c_ in (pv.get("cambios") or [])[:80]:
            lin.append(f"  - {c_['texto']}")
        if (pv.get("total_cambios") or 0) > 80:
            lin.append(f"  … y {pv['total_cambios'] - 80} cambios más")
        if pv.get("aviso"):
            lin.append(pv["aviso"])
        return "\n".join(lin)

    def _aplicar_ops(self, operaciones, motivo, origen=None) -> dict:
        r = self.s.pedir("POST", self._p("operaciones"), cuerpo={"operaciones": operaciones, "motivo": motivo, "origen": origen or {}, "previsualizar": False},
                         crudo=True, ruta_nueva=True)
        self._est = None
        try:
            j = r.json()
        except ValueError:
            j = {}
        return {**j, "estado": r.status_code}

    @staticmethod
    def _texto_aplicado(r) -> str:
        hechas = r.get("hechas") or []
        out = [f"{'✓' if r.get('estado') == 201 else '⚠'} Lote {r.get('lote')} · {len(hechas)} decisiones guardadas · autor {r.get('autor') or '—'}"
               + (f" · KB ahora {r['huella']}" if r.get("huella") else "")]
        if r.get("error"):
            out.append(f"✗ {r['error']}")
        for h in hechas[:40]:
            out.append(f"  - {h['sk']} · {h['accion']} · {', '.join(h.get('objetos') or [])[:160]}")
        out.append("Cada decisión se puede deshacer con deshacer(sk=…); el lote entero, deshaciendo sus decisiones (historial las agrupa por lote).")
        return "\n".join(out)

    def operar(self, operaciones=None, motivo="", origen=None, confirmar=None) -> str:
        if confirmar:
            datos = self._confirmado("operaciones", confirmar)
            return self._texto_aplicado(self._aplicar_ops(datos["operaciones"], datos["motivo"], datos.get("origen")))
        ops = [x for x in (operaciones or []) if isinstance(x, dict)]
        if not ops:
            raise ErrorKortex("Pasa la lista de operaciones (mira la descripción de operar_kb).")
        if len(str(motivo or "").strip()) < 3:
            raise ErrorKortex("Indica un motivo general (queda en el historial de cada decisión).")
        pv = self._previsualizar_ops(ops, motivo, origen)
        return self._codigo("operaciones", {"operaciones": ops, "motivo": motivo, "origen": origen or {}}, pv)

    def catalogo(self) -> str:
        c = self.s.pedir("GET", self._p("catalogo"), ruta_nueva=True)
        out = ["Tipos de relación (tipo_id):"]
        for t in c.get("tipos_relacion") or []:
            out.append(f"  - {t['id']} · {t.get('nombre')} · {_r(t.get('criterio'), 160)}")
        out.append("Tipos de entidad por familia (tipo_id; PROCESO_HPUM solo lo son los del Excel):")
        for f in c.get("familias_entidad") or []:
            out.append(f"  - {f['id']} ({f.get('nombre')}): " + ", ".join(t["id"] for t in f.get("tipos") or []))
        amp = c.get("ampliaciones") or []
        out.append(f"Ampliaciones por decisión: {len(amp)}" + ("".join(f"\n  - {x['clase']} {x['id']} · {x['etiqueta']}" + (f" · familia {x['familia']}" if x.get('familia') else "")
                                                                   + f" · {_r(x.get('descripcion'), 120)}" for x in amp)))
        est = (c.get("estados") or {}).get("estados") or []
        out.append("Estados: " + "; ".join(f"{e['id']} = {e.get('etiqueta')}" for e in est))
        D = self.servida()
        amb = [n for n in (D.get("grafo") or {}).get("nodos") or [] if n.get("clase") == "AMBITO"]
        out.append("Ámbitos (para ASIGNAR_AMBITO / CREAR_ENTIDAD): " + ", ".join(f"{n['id']} = {n.get('etiqueta')}" for n in amb))
        return "\n".join(out)

    def buscar_hpum(self, texto="", limite=20) -> str:
        D, q = self.servida(), norm(texto)
        hs = [n for n in (D.get("grafo") or {}).get("nodos") or [] if n.get("clase") == "HPUM"]
        hit = [n for n in hs if not q or q in norm(n.get("etiqueta")) or q in norm((n.get("propiedades") or {}).get("ruta"))]
        hit.sort(key=lambda n: (q not in norm(n.get("etiqueta")), str(n.get("nivel") or ""), len(str((n.get("propiedades") or {}).get("ruta") or ""))))
        out = [f"{len(hit)} procesos HPUM" + (f" con «{texto}»" if texto else "") + (f" (se muestran {limite})" if len(hit) > limite else "")]
        for n in hit[:limite]:
            out.append(f"- {n['id']} · {n.get('nivel') or ''} · {(n.get('propiedades') or {}).get('ruta') or n.get('etiqueta')}")
        return "\n".join(out)

    def fichas_revision(self) -> str:
        reg = self._registro()
        fs, imps = reg.fichas(), reg.importaciones()
        out = [f"{len(fs)} fichas generadas en este puesto · {len(imps)} importaciones de respuestas"]
        lotes = {}
        for f in fs:
            lotes.setdefault(f["lote"], []).append(f)
        for lote in sorted(lotes, reverse=True)[:10]:
            xs = lotes[lote]
            its = [i for x in xs for i in FR.items_registro(x)]
            ne = sum(1 for i in its if i["clase"] == "ENT")
            nr = sum(1 for i in its if i["clase"] == "REL")
            out.append(f"- Lote {lote} · {FR.MODOS.get(xs[0]['modo'], xs[0]['modo'])} · KB {xs[0]['huella']} · {len(xs)} fichas · "
                       f"{ne} entidades y {nr} relaciones · {Path(xs[0]['fichero']).parent}")
        for i in imps[-15:]:
            res = FR.resumen_importacion(i)
            out.append(f"- {i['importacion_id']} · {i['estado']} · ficha {i['ficha_id']} · revisor declarado {i['revisor_declarado'].get('nombre') or '—'} · "
                       f"entidades confirmadas {res['ENT']['CORRECTA']} · relaciones confirmadas {res['REL']['CORRECTA']}, "
                       f"rechazadas {res['REL']['INCORRECTA']}, sin revisar {res['REL']['SIN_REVISAR']}")
        return "\n".join(out)

    # ================================================================== decisiones (escritura auditable)
    def historial_bruto(self) -> list:
        return self.s.pedir("GET", self._p("decisiones")).get("decisiones") or []

    def historial(self, limite=30, autor=None, accion=None) -> str:
        ds = [d for d in self.historial_bruto() if (not autor or norm(autor) in norm(d.get("autor"))) and (not accion or (d.get("accion") or "").upper() == accion.upper())]
        out = [f"{len(ds)} decisiones (de la más reciente a la más antigua)"]
        for d in ds[:limite]:
            b = d.get("bloque") or {}
            out.append(f"- {d.get('sk')} · {d.get('autor')} · {d.get('accion')} · {d.get('estado')} · {d.get('n_objetos')} obj. ({b.get('criterio')})"
                       + (f" · {_r(d.get('motivo'), 120)}" if d.get("motivo") else "") + (f" · {d['consolidacion_id']}" if d.get("consolidacion_id") else "")
                       + (f" · {d['lote']} op. {d.get('operacion')}" if d.get("lote") else ""))
        return "\n".join(out)

    def _cuerpo(self, accion, criterio, valor, parametros, motivo):
        accion = (accion or "").upper()
        if accion not in ACCIONES:
            raise ErrorKortex(f"Acción no admitida: {accion}. Las de la web: {', '.join(sorted(ACCIONES))}. "
                              "Para crear o corregir relaciones, crear entidades, enlazar con HPUM, asignar ámbitos o ampliar el catálogo: operar_kb.")
        if criterio not in CRITERIOS:
            raise ErrorKortex(f"Criterio no admitido: {criterio}. Valen: {', '.join(sorted(CRITERIOS))}.")
        if accion in CON_MOTIVO and len(str(motivo or "").strip()) < 3:
            raise ErrorKortex(f"{accion} necesita un motivo (al menos 3 caracteres): queda en el historial.")
        if criterio == "ids":
            valor = [str(x) for x in (valor if isinstance(valor, list) else [valor]) if str(x).strip()]
            if not valor:
                raise ErrorKortex("No hay ids.")
            if len(valor) > TOPE_BLOQUE:
                raise ErrorKortex(f"Como mucho {TOPE_BLOQUE} objetos por decisión.")
        return {"accion": accion, "bloque": {"criterio": criterio, "valor": valor}, "parametros": parametros or {}, "motivo": str(motivo or "").strip()}

    def _codigo(self, tipo, datos, resumen) -> str:
        ahora = self.reloj()
        for k in [k for k, v in self._pend.items() if v["caduca"] < ahora]:
            del self._pend[k]
        cod = f"{tipo[:3].upper()}-" + secrets.token_hex(3)
        self._pend[cod] = {"tipo": tipo, "datos": datos, "caduca": ahora + CADUCA_CODIGO,
                           "huella": hashlib.sha256(json.dumps(datos, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
        return resumen + f"\n\nNo se ha cambiado nada todavía. Para ejecutarlo, vuelve a llamar con confirmar=\"{cod}\" (caduca en 15 min)."

    def _confirmado(self, tipo, cod):
        p = self._pend.pop(str(cod), None)
        if not p or p["caduca"] < self.reloj():
            raise ErrorKortex("Ese código de confirmación no existe o ha caducado: vuelve a previsualizar.")
        if p["tipo"] != tipo:
            raise ErrorKortex(f"Ese código es de otra operación ({p['tipo']}).")
        return p["datos"]

    def decidir(self, accion, ids=None, parametros=None, motivo="", criterio="ids", valor=None, confirmar=None) -> str:
        """Una decisión de un solo objeto se guarda directamente; cualquier bloque (varios ids o criterio distinto de ids), en dos pasos."""
        if confirmar:
            cuerpo = self._confirmado("decision", confirmar)
            return self._guardar(cuerpo)
        cuerpo = self._cuerpo(accion, criterio, valor if criterio != "ids" else ids, parametros, motivo)
        if criterio == "ids" and len(cuerpo["bloque"]["valor"]) == 1:
            return self._guardar(cuerpo)
        pv = self.s.pedir("POST", self._p("previsualizar"), cuerpo=cuerpo)
        resumen = (f"Previsualización de {cuerpo['accion']} ({cuerpo['bloque']['criterio']}): {pv.get('total')} objetos, cambian {pv.get('cambian')}, "
                   f"ya estaban {pv.get('ya_estaban')} · por clase {compacto(pv.get('por_clase'), 200)}"
                   + (f" · destino {compacto(pv.get('destino'), 120)}" if pv.get("destino") else "")
                   + "\nMuestra: " + "; ".join(_r(m if isinstance(m, str) else (m.get("descripcion") or m.get("id") or m), 90) for m in (pv.get("muestra") or [])[:10]))
        if not pv.get("cambian"):
            return resumen + "\nNo cambiaría nada: no hace falta confirmar."
        return self._codigo("decision", cuerpo, resumen)

    def _guardar_dec(self, cuerpo) -> dict:
        r = self.s.pedir("POST", self._p("decisiones"), cuerpo=cuerpo)
        self._est = None
        return r.get("decision") or {}

    def _guardar(self, cuerpo) -> str:
        d = self._guardar_dec(cuerpo)
        return (f"Guardada la decisión {d.get('sk')}: {d.get('accion')} sobre {d.get('n_objetos')} objetos, autor {d.get('autor')}."
                f" Se puede deshacer con deshacer(sk=\"{d.get('sk')}\").")

    def deshacer(self, sk) -> str:
        if not re.fullmatch(r"\d{4}-\d\d-\d\dT[\d:]+Z#dec_[0-9a-f]{12}", str(sk or "")):
            raise ErrorKortex("Pasa el «sk» de la decisión tal como sale en historial (fecha#dec_…).")
        self.s.pedir("POST", self._p("decisiones/deshacer"), cuerpo={"sk": sk})
        self._est = None
        return f"Decisión {sk} deshecha (queda en el historial como DESHECHA)."

    def exportar_decisiones(self, formato="csv", carpeta=None) -> str:
        r = self.s.pedir("GET", self._p("exportar"), params={"formato": "json"} if formato == "json" else None, crudo=True)
        dest = Path(carpeta).expanduser() if carpeta else config.descargas()
        dest.mkdir(parents=True, exist_ok=True)
        f = dest / f"revision_{self.cid}.{ 'json' if formato == 'json' else 'csv'}"
        f.write_bytes(r.content)
        return f"Decisiones activas exportadas en {f}."

    # ================================================================== consolidación
    def consolidaciones(self) -> str:
        r = self.s.pedir("GET", self._p("consolidaciones"))
        out = [f"Abierta: {(r.get('abierta') or {}).get('consolidacion_id') or 'ninguna'}"]
        for c in r.get("consolidaciones") or []:
            out.append(f"- {c.get('consolidacion_id')} · {c.get('estado')} · {c.get('nombre')} · {c.get('autor')} · {str(c.get('creada_en') or c.get('en') or '')[:16]}"
                       + (f" · {compacto(c.get('progreso') or c.get('resumen'), 160)}" if c.get("progreso") or c.get("resumen") else ""))
        return "\n".join(out)

    def abrir_consolidacion(self, nombre, objetivo="") -> str:
        r = self.s.pedir("POST", self._p("consolidaciones"), cuerpo={"nombre": nombre, "objetivo": objetivo})
        c = r.get("consolidacion") or r
        return f"Abierta la consolidación {c.get('consolidacion_id')} «{c.get('nombre') or nombre}»."

    def consolidacion(self, cons_id) -> str:
        r = self.s.pedir("GET", self._p(f"consolidaciones/{cons_id}"))
        c = r.get("consolidacion") or {}
        out = [f"{c.get('consolidacion_id')} · {c.get('estado')} · {c.get('nombre')} — {_r(c.get('objetivo'), 200)}",
               f"Pendientes de decidir: {len(r.get('pendientes_ids') or [])}"]
        for d in (r.get("decisiones") or [])[:25]:
            out.append(f"- {d.get('sk')} · {d.get('accion')} · {d.get('estado')} · {d.get('n_objetos')} obj. · {_r(d.get('titulo') or d.get('motivo'), 120)}")
        return "\n".join(out)

    def cerrar_consolidacion(self, cons_id, nota="") -> str:
        self.s.pedir("POST", self._p(f"consolidaciones/{cons_id}/cerrar"), cuerpo={"nota": nota})
        return f"Consolidación {cons_id} cerrada."

    def _propuestas(self):
        return self.s.pedir("GET", self._p("consolidacion"))

    def propuestas(self, caso=None, limite=30) -> str:
        c = self._propuestas()
        ps = [p for p in c.get("propuestas") or [] if not caso or p.get("caso") == caso]
        casos = {}
        for p in c.get("propuestas") or []:
            casos[p.get("caso")] = casos.get(p.get("caso"), 0) + 1
        out = [f"{len(c.get('propuestas') or [])} propuestas de los agentes (KB {str(c.get('huella'))[:12]}) · por caso: {compacto(casos, 400)}"]
        for p in ps[:limite]:
            out.append(f"- {p['id']} · {p.get('caso')} · {p.get('accion')} · confianza {p.get('confianza')} · {len(p.get('objetos') or [])} obj."
                       + (" · informativa" if p.get("informativa") else "") + f" · {_r(p.get('titulo'), 140)}")
        if len(ps) > limite:
            out.append(f"… y {len(ps) - limite} más (filtra por caso)")
        return "\n".join(out)

    def explicar_propuesta(self, pid) -> str:
        p = next((x for x in self._propuestas().get("propuestas") or [] if x["id"] == pid), None)
        if not p:
            raise ErrorKortex(f"No hay ninguna propuesta «{pid}» en el análisis actual (las propuestas cambian con la KB).")
        out = [f"{p['id']} · {p.get('caso')} · agente {p.get('agente')} · confianza {p.get('confianza')}", f"Propuesta: {p.get('titulo')}",
               f"Acción: {p.get('accion')} · parámetros {compacto(p.get('parametros'), 300)}", f"Antes: {_r(p.get('antes'), 300)}", f"Después: {_r(p.get('despues'), 300)}"]
        out += [f"- Señal ({x.get('puntos'):+d}): {x.get('texto')}" if isinstance(x.get("puntos"), int) else f"- Señal: {x.get('texto')}" for x in p.get("senales") or []]
        out += [f"- «{_r(e.get('cita'), 220)}» — {e.get('documento')}" for e in (p.get("evidencias") or [])[:6]]
        objs = p.get("objetos") or []
        out.append(f"Objetos ({len(objs)}): " + ", ".join(objs[:20]) + (" …" if len(objs) > 20 else ""))
        if (p.get("tabla") or {}).get("seleccionable"):
            out.append("Se puede aplicar solo a una parte: aplicar_propuestas(..., seleccion={\"" + pid + "\": [objetos]}).")
        return "\n".join(out)

    def analizar(self) -> str:
        r = self.s.pedir("POST", self._p("consolidacion/analizar"))
        return f"Análisis hecho sobre la KB {str(r.get('huella'))[:12]}: {r.get('total')} propuestas · {compacto(r.get('por_caso'), 400)}"

    def aplicar_propuestas(self, ids, seleccion=None, confirmar=None) -> str:
        if confirmar:
            datos = self._confirmado("aplicar", confirmar)
            r = self.s.pedir("POST", self._p("consolidacion/aplicar"), cuerpo=datos)
            self._est = None
            return f"Aplicadas {r.get('hechas')} propuestas como decisiones" + (f"; omitidas {r.get('omitidas')}" if r.get("omitidas") else "") + f". KB ahora {str(r.get('huella'))[:12]}."
        ids = [str(x) for x in ids or []][:500]
        idx = {p["id"]: p for p in self._propuestas().get("propuestas") or []}
        faltan = [i for i in ids if i not in idx]
        lineas = [f"- {i} · {idx[i].get('accion')} · {len((seleccion or {}).get(i) or idx[i].get('objetos') or [])} obj. · {_r(idx[i].get('titulo'), 120)}"
                  + (" · INFORMATIVA (no se aplica)" if idx[i].get("informativa") else "") for i in ids if i in idx]
        resumen = f"Se aplicarían {len(lineas)} propuestas en la consolidación abierta:\n" + "\n".join(lineas) + (f"\nNo existen: {', '.join(faltan)}" if faltan else "")
        return self._codigo("aplicar", {"propuestas": ids, "seleccion": seleccion or {}}, resumen)

    def descartar_propuestas(self, ids, motivo, confirmar=None) -> str:
        if confirmar:
            datos = self._confirmado("descartar", confirmar)
            r = self.s.pedir("POST", self._p("consolidacion/descartar"), cuerpo=datos)
            return f"Descartadas {r.get('hechas')} propuestas (quedan como decisiones DESCARTAR_PROPUESTA)."
        if len(str(motivo or "").strip()) < 3:
            raise ErrorKortex("Indica por qué se descartan (queda en el historial).")
        ids = [str(x) for x in ids or []][:500]
        return self._codigo("descartar", {"propuestas": ids, "motivo": motivo}, f"Se descartarían {len(ids)} propuestas: {', '.join(ids[:20])} · motivo «{motivo}»")

    # ================================================================== fuentes
    def fuentes(self) -> str:
        return compacto(self.s.pedir("GET", "fuentes"), 3000)

    def ingesta_pendiente(self, forzar=False) -> str:
        r = self.s.pedir("GET", "ingesta/pendiente", params={"forzar": "1"} if forzar else None)
        return compacto(r, 6000)

    def actualizar_desde_ingesta(self, forzar=False, confirmar=None) -> str:
        if confirmar:
            datos = self._confirmado("actualizar", confirmar)
            r = self.s.pedir("POST", "ingesta/actualizar", cuerpo=datos)
            self._est = None
            return "Actualización lanzada: " + compacto({k: v for k, v in r.items() if k != "fuentes"}, 1200)
        pend = self.s.pedir("GET", "ingesta/pendiente")
        return self._codigo("actualizar", {"forzar": bool(forzar)},
                            "Se reconstruiría la KB con lo analizado en la ingesta. Pendiente ahora: " + compacto(pend, 1500))

    def documentos_kb(self, quitar=None, incorporar=None, confirmar=None) -> str:
        if confirmar:
            datos = self._confirmado("documentos", confirmar)
            r = self.s.pedir("POST", "ingesta/documentos", cuerpo=datos)
            self._est = None
            return "Actualización dirigida lanzada: " + compacto({k: v for k, v in r.items() if k != "fuentes"}, 1200)
        quitar, incorporar = [str(x) for x in quitar or []], [str(x) for x in incorporar or []]
        if not quitar and not incorporar:
            raise ErrorKortex("Indica qué documentos quitar o incorporar (doc_id).")
        nombres = lambda xs: ", ".join(f"{self._doc(x)} ({x})" for x in xs[:20])  # noqa: E731
        return self._codigo("documentos", {"quitar": quitar, "incorporar": incorporar},
                            (f"Se QUITARÍAN de la KB {len(quitar)} documentos (y lo que solo sale de ellos): {nombres(quitar)}\n" if quitar else "")
                            + (f"Se incorporarían {len(incorporar)}: {nombres(incorporar)}" if incorporar else ""))

    def reanalisis(self) -> str:
        return compacto(self.s.pedir("GET", "ingesta/reanalisis"), 5000)

    def reanalizar(self, documentos, confirmar=None) -> str:
        if confirmar:
            datos = self._confirmado("reanalizar", confirmar)
            r = self.s.pedir("POST", "ingesta/reanalisis", cuerpo=datos)
            return "Reanálisis pedido: " + compacto(r, 1500)
        docs = [str(x) for x in documentos or []]
        if not docs:
            raise ErrorKortex("Indica los documentos a reanalizar.")
        info = self.s.pedir("GET", "ingesta/reanalisis")
        return self._codigo("reanalizar", {"documentos": docs},
                            f"Se reanalizarían {len(docs)} documentos con el modelo (cuesta dinero en Bedrock). Estimación: "
                            f"{compacto(info.get('estimacion_unitaria'), 200)} por documento · extractor {info.get('extractor_actual')}")

    # ================================================================== asistente de la web (para comparar)
    def asistente_web(self, mensaje, historial=None, contexto=None) -> str:
        r = self.s.pedir("POST", self._p("asistente"), cuerpo={"mensaje": str(mensaje)[:2000], "historial": historial or [], "contexto": contexto or {}})
        out = []
        for b in r.get("bloques") or []:
            if b.get("texto"):
                out.append(str(b["texto"]))
            resto = {k: v for k, v in b.items() if k not in ("tipo", "texto")}
            if resto:
                out.append(compacto(resto, 1500))
        if r.get("herramientas"):
            out.append("Herramientas usadas: " + ", ".join(r["herramientas"]))
        if r.get("enlaces"):
            out.append("Enlaces: " + compacto(r["enlaces"], 600))
        return "\n".join(out) or compacto(r)
