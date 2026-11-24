"""Fichas de conocimiento para la revisión de la KB (20/11/2026): la unidad es una ENTIDAD con sus relaciones (entrantes y salientes).

Dos modalidades, sobre la confianza REAL de cada elemento (`confianza`, de entidades y de relaciones):
- PENDIENTE_VALIDAR (ficha A): entidades y relaciones en estado PENDIENTE_VALIDAR (la IA las interpretó y cumplen todos los controles
  automáticos). Falta que una persona las valide: se contrastan, normalmente en bloque.
- OTROS_ESTADOS (ficha B): cualquier otro estado pendiente (SIN_CORROBORAR, SIN_CITA_LITERAL, SIN_EVIDENCIA, FUERA_DE_CATALOGO,
  SIN_VINCULAR, EN_CONFLICTO, nulo o uno nuevo): se revisan con detalle.
Lo VALIDADO (solo lo pone una persona) y lo que ya tiene decisión de una persona no entra nunca; se enseña como contexto.
Los estados vienen de la KB servida (kbweb_estados, 23/11/2026); los valores antiguos (VALIDADO_AUTO, PROPUESTO, VALIDADO_PERSONA) se
traducen con legado().
Con `entidad` y sin modo: ficha completa de esa entidad (todos sus elementos, cada uno con su confianza).

Contexto completo: lo que no entra en la modalidad se enseña igual, marcado como CONTEXTO (sin aprobar ni rechazar; solo se puede
señalar un error). Una relación se revisa en UNA sola tarjeta del lote (la canónica: la punta que está en revisión o, si no, la más
conectada); en la otra punta aparece como referencia. Así no hay dos decisiones de la misma relación ni se pierde ninguna.

Circuito: generar (HTML autocontenido + registro local con sello HMAC) → la persona responde sin conexión y descarga un JSON →
importar (sello, identificadores, firmas, versión de la KB y choques con otras revisiones; NO escribe en la KB) → previsualizar (qué
decisiones habría que guardar y su impacto, solo con revisor acreditado) → aplicar en dos pasos con las decisiones auditables de siempre.
Las decisiones de entidad y de relación son independientes: aprobar una entidad no aprueba sus relaciones ni rechazar una relación
toca la entidad. Sin modelo: plantillas y datos de la KB; los grupos salen del ámbito y de la familia del catálogo."""
import datetime as dt
import hashlib
import hmac
import json
import re
import secrets
import unicodedata
from pathlib import Path

from .ficha import FAMILIA, bonito, clave_es, esc, num

FORMATO_RESPUESTAS = "kortex-ficha-respuestas/2"
FORMATO_RESPUESTAS_V1 = "kortex-ficha-respuestas/1"        # fichas solo de relaciones (20/11, primera versión): se siguen importando
FORMATO_FICHA = "kortex-ficha-revision/2"
MODOS = {"PENDIENTE_VALIDAR": "Pendiente de validar (cumple todos los controles)", "OTROS_ESTADOS": "Pendiente con dudas (resto de estados)",
         "VALIDADO_AUTO": "Pendiente de validar (cumple todos los controles)", "NO_VALIDADO_AUTO": "Pendiente con dudas (resto de estados)",
         "COMPLETA": "Ficha completa"}
CORTO = {"PENDIENTE_VALIDAR": "A", "OTROS_ESTADOS": "B", "COMPLETA": "C", "VALIDADO_AUTO": "A", "NO_VALIDADO_AUTO": "B"}   # las dos últimas: fichas anteriores
RESP_ENT = {
    "CORRECTA": "Sí, está bien identificada", "CORREGIR_NOMBRE": "El nombre no es correcto", "CORREGIR_TIPO": "El tipo no es correcto",
    "DUPLICADO": "Es la misma que otra entidad", "INCORRECTA": "No es una entidad válida", "PARCIAL": "Hay que matizarla", "SIN_INFORMACION": "No lo sé",
    "FUERA_DE_AMBITO": "No es de mi ámbito", "SIN_REVISAR": "Sin revisar"}
RESP_REL = {
    "CORRECTA": "Sí", "PARCIAL": "Hay que matizarla", "INCORRECTA": "No es cierta", "OTRO_TIPO": "Es otro tipo de relación",
    "DIRECCION": "La dirección está al revés", "SIN_INFORMACION": "No lo sé", "FUERA_DE_AMBITO": "No es de mi ámbito", "SIN_REVISAR": "Sin revisar"}
RESP = {"ENT": RESP_ENT, "REL": RESP_REL}
RESPUESTAS = RESP_REL                                         # nombre de la primera versión
CON_CAMBIO = {"PARCIAL", "INCORRECTA", "OTRO_TIPO", "DIRECCION", "CORREGIR_NOMBRE", "CORREGIR_TIPO", "DUPLICADO"}
PIDE_MOTIVO = {"PARCIAL", "INCORRECTA"}
MANUALES = {"PARCIAL", "OTRO_TIPO", "DIRECCION", "DUPLICADO"}  # 23/11/2026: ya no quedan a mano: dirección, otro tipo y duplicado se aplican
# (INVERTIR_RELACION, CORREGIR_RELACION, FUSIONAR_ENTIDADES); los matices van «por interpretar» con sugerencias para que Claude proponga lo bueno
RESPUESTAS_CONJUNTO = {"SI": "Sí", "PARCIAL": "Parcialmente", "NO": "No", "SIN_INFORMACION": "No lo sé", "FUERA_DE_AMBITO": "No es de mi ámbito", "": "Sin responder"}
MAX_POR_FICHA = 40          # elementos a revisar por HTML (entidades + relaciones): lo que una persona revisa de una sentada
MIN_BLOQUE = 4              # temas con menos elementos se juntan en «Varios temas» del mismo ámbito
MAX_TEXTO = 2000
SIN_AMBITO = "Sin ámbito asignado"
FAMILIAS = {**FAMILIA, "AMB_APL": "Ámbitos de aplicación"}
# Estados (copia de kbweb_estados: el MCP no lleva el código de la web). Si la KB servida publica catalogos.estados, mandan sus etiquetas.
ESTADOS = {"VALIDADO": "Validado", "PENDIENTE_VALIDAR": "Pendiente de validar", "SIN_CORROBORAR": "Sin corroborar", "SIN_CITA_LITERAL": "Sin cita literal",
           "SIN_EVIDENCIA": "Deducido sin evidencia", "FUERA_DE_CATALOGO": "Fuera del catálogo", "SIN_VINCULAR": "Sin vincular", "EN_CONFLICTO": "En conflicto"}
_ESTADO_ANTIGUO = {"VALIDADO_PERSONA": "VALIDADO", "VALIDADO_AUTO": "PENDIENTE_VALIDAR"}


def legado(valor, motivos=()) -> str:
    """Estado actual a partir de un valor antiguo de «confianza» (PROPUESTO se resuelve por sus motivos). Un estado nuevo pasa tal cual."""
    v = str(valor or "")
    if v in ESTADOS or (v and v not in _ESTADO_ANTIGUO and v != "PROPUESTO"):
        return v
    if v in _ESTADO_ANTIGUO:
        return _ESTADO_ANTIGUO[v]
    m = " ".join(str(x) for x in motivos or []).lower()
    if "fuera del catálogo" in m:
        return "FUERA_DE_CATALOGO"
    if "mapear" in m:
        return "SIN_VINCULAR"
    if "hipótesis" in m or "ruta o nombre" in m:
        return "SIN_EVIDENCIA"
    if "sin cita literal" in m:
        return "SIN_CITA_LITERAL"
    return "SIN_CORROBORAR"


def estado_txt(v) -> str:
    return ESTADOS.get(legado(v)) or str(v or "Sin estado")
REVISION_TXT = {"APROBADA": "Aprobada", "CORREGIDA": "Corregida", "RECHAZADA": "Rechazada"}
AVISOS_TXT = {"DE_UNA_PASADA_ANTERIOR": "Se conserva de un análisis anterior del mismo documento.",
              "DECIDIDA_EN_LA_REVISION_DE_LA_BASE": "Viene de una decisión de la revisión del Excel base."}
PROCEDENCIA = {"BASE_EXCEL": "Excel base (catálogo)", "INGESTA": "Documentos de la ingesta", "BASE_EXCEL+INGESTA": "Excel base y documentos de la ingesta"}
MOTIVO_TXT = {"sin cita literal exacta": "la cita no aparece literalmente en el documento"}
VERBOS = {"FORMA_PARTE_DE": ("forma parte de", "formar parte de"), "PRODUCE": ("produce", "producir"),
          "CONSUME": ("utiliza como entrada", "utilizar como entrada"), "MIDE": ("mide", "medir"), "INTEGRA_CON": ("se integra con", "integrarse con"),
          "SOPORTA": ("da soporte a", "dar soporte a"), "GESTIONA": ("gestiona", "gestionar"), "UTILIZA": ("utiliza", "utilizar"),
          "EJECUTA": ("ejecuta", "ejecutar"), "INTERACTUA_CON": ("interactúa con", "interactuar con"),
          "RESPONSABLE_DE": ("es responsable de", "ser responsable de"), "REQUIERE": ("requiere", "requerir"), "AFECTA_A": ("afecta a", "afectar a"),
          "DEPENDE_DE": ("depende de", "depender de")}


# solo para mostrar (el catálogo no cambia): los tipo_id sin tildes ni preposiciones se leen mal en una ficha para negocio
TIPO_TXT = {"ACTIVO_FISICO": "Activo físico", "APLICACION": "Aplicación", "CAPACIDAD_NEGOCIO": "Capacidad de negocio", "CAPACIDAD_TECNICA": "Capacidad técnica",
            "COMPONENTE_SOFTWARE": "Componente de software", "CONJUNTO_DATOS": "Conjunto de datos", "METRICA": "Métrica", "MODULO": "Módulo",
            "OBJETO_NEGOCIO": "Objeto de negocio", "PAIS_REGION": "País o región", "SOCIEDAD_GRUPO": "Sociedad del grupo", "SOLICITUD_CAMBIO": "Solicitud de cambio",
            "TECNOLOGIA": "Tecnología"}


def tipo_txt(t) -> str:
    return TIPO_TXT.get(t) or bonito(t)


class ErrorFicha(Exception):
    pass


def ahora_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def modo_de(v, permitir_completa=False) -> str:
    k = re.sub(r"[^A-Z]+", "_", str(v or "").upper()).strip("_")
    if k in ("A", "PENDIENTE_VALIDAR", "PENDIENTE_DE_VALIDAR", "VALIDADO_AUTO", "VALIDADAS_AUTO", "VALIDACION_AUTOMATICA"):
        return "PENDIENTE_VALIDAR"
    if k in ("B", "OTROS_ESTADOS", "RESTO", "RESTO_DE_ESTADOS", "CON_DUDAS", "NO_VALIDADO_AUTO", "NO_VALIDADAS_AUTO", "DISTINTO_DE_VALIDADO_AUTO"):
        return "OTROS_ESTADOS"
    if permitir_completa and k in ("", "C", "COMPLETA", "TODO", "TODOS"):
        return "COMPLETA"
    raise ErrorFicha("Modo no admitido: usa PENDIENTE_VALIDAR (ficha A) u OTROS_ESTADOS (ficha B)"
                     + ("." if not permitir_completa else "; sin modo, con una entidad, sale su ficha completa."))


def entra_en_modo(x, modo) -> bool:
    """El estado real decide (23/11/2026). A: PENDIENTE_VALIDAR. B: cualquier otro estado pendiente (incluidos nulo y desconocidos).
    VALIDADO nunca: solo lo pone una persona y ya no está pendiente."""
    e = legado(x.get("confianza"), x.get("confianza_motivos"))
    if modo == "COMPLETA":
        return True
    if e == "VALIDADO":
        return False
    return e == "PENDIENTE_VALIDAR" if modo == "PENDIENTE_VALIDAR" else e != "PENDIENTE_VALIDAR"


DECIDIDO = {"APROBADA", "CORREGIDA", "RECHAZADA"}


def decidido(ix, oid) -> bool:
    """Una persona ya decidió sobre este elemento (aprobó, corrigió o rechazó): no vuelve a revisión; se enseña como contexto."""
    return (ix.rev.get(oid) or {}).get("estado") in DECIDIDO


def firma(rel) -> str:
    """Lo revisado de una relación: puntas, tipo y citas. Si cambia, la respuesta ya no vale."""
    ev = sorted([str(e.get("cita") or ""), str(e.get("doc_id") or "")] for e in rel.get("evidencias") or [])
    base = json.dumps([rel.get("relacion_id"), rel.get("origen"), rel.get("tipo_id"), rel.get("destino"), ev], ensure_ascii=False)
    return hashlib.sha256(base.encode()).hexdigest()[:16]


def firma_ent(e) -> str:
    """Lo revisado de una entidad: identificador, nombre, tipo y alias."""
    base = json.dumps([e.get("entidad_id"), e.get("nombre"), e.get("tipo_id"), sorted(e.get("alias") or [])], ensure_ascii=False)
    return hashlib.sha256(base.encode()).hexdigest()[:16]


def firma_de(ix, obj, clase):
    x = (ix.ent if clase == "ENT" else ix.rel).get(obj)
    return None if x is None else (firma_ent(x) if clase == "ENT" else firma(x))


def limpio(v, n=MAX_TEXTO) -> str:
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(v or "")).strip()
    return t[:n]


# ====================================================================== índice de la KB servida
class Indice:
    def __init__(self, D, revisado=None):
        g = D.get("grafo") or {}
        self.D = D
        self.nodos = {n["id"]: n for n in g.get("nodos") or []}
        self.ent = {e["entidad_id"]: e for e in D.get("entidades") or []}
        self.rel = {r["relacion_id"]: r for r in D.get("relaciones") or []}
        self.doc = {d["doc_id"]: d for d in D.get("documentos") or []}
        self.amb = {n["id"]: n.get("etiqueta") or n["id"] for n in self.nodos.values() if n.get("clase") == "AMBITO"}
        self.amb_de = {}
        for a in g.get("aristas") or []:
            if a.get("clase") == "AMBITO_ENTIDAD":
                self.amb_de.setdefault(a["origen"], []).append(self.amb.get(a["destino"]) or a["destino"])
        self.rev = revisado or {}
        self.de = {}                                            # entidad → relaciones (entrantes y salientes)
        for r in self.rel.values():
            for k in dict.fromkeys((r["origen"], r["destino"])):
                self.de.setdefault(k, []).append(r["relacion_id"])
        self.dups = {}                                          # entidad → [(DUP|a|b, la otra)]
        for d in D.get("posibles_duplicados") or []:
            did = f"DUP|{d['entidad_a']}|{d['entidad_b']}"
            self.dups.setdefault(d["entidad_a"], []).append((did, d["entidad_b"]))
            self.dups.setdefault(d["entidad_b"], []).append((did, d["entidad_a"]))
        self.tipos = sorted({e.get("tipo_id") for e in self.ent.values() if e.get("tipo_id") and e.get("tipo_id") != "PROCESO_HPUM"})
        cat = ((D.get("catalogos") or {}).get("estados") or {}).get("estados") or []
        self.etiquetas = {**ESTADOS, **{x["id"]: x.get("etiqueta") or x["id"] for x in cat if isinstance(x, dict) and x.get("id")}}
        self.tipos_rel = sorted({r.get("tipo_id") for r in self.rel.values() if r.get("tipo_id")} | set(VERBOS))

    def estado_txt(self, v) -> str:
        return self.etiquetas.get(legado(v)) or str(v or "Sin estado")

    def es_hpum(self, oid) -> bool:
        return (self.nodos.get(oid) or {}).get("clase") == "HPUM" or str(oid).startswith("HPUM:")

    def nombre(self, oid) -> str:
        if oid in self.ent:
            p = ((self.rev.get(oid) or {}).get("parametros") or {})
            return p.get("nombre") or self.ent[oid].get("nombre") or oid
        n = self.nodos.get(oid) or {}
        if n.get("clase") == "HPUM":
            return str((n.get("propiedades") or {}).get("ruta") or n.get("etiqueta") or oid).split(" > ")[-1]
        return n.get("etiqueta") or oid

    def tipo(self, oid) -> str:
        if oid in self.ent:
            p = ((self.rev.get(oid) or {}).get("parametros") or {})
            return tipo_txt(p.get("tipo_id") or self.ent[oid].get("tipo_id"))
        n = self.nodos.get(oid) or {}
        if n.get("clase") == "HPUM":
            ruta = str((n.get("propiedades") or {}).get("ruta") or "").split(" > ")[:-1]
            return f"Proceso HPUM {n.get('nivel') or ''}".strip() + (" · " + " › ".join(ruta) if ruta else "")
        return bonito(n.get("clase") or "")

    def ambitos(self, oid) -> list:
        if oid in self.ent:
            return list(self.amb_de.get(oid) or [])
        n = self.nodos.get(oid) or {}
        return [self.amb.get(a) or a for a in n.get("ambitos") or []]

    def ambitos_rel(self, r) -> list:
        return list(dict.fromkeys(self.ambitos(r["origen"]) + self.ambitos(r["destino"])))

    def bloque_ent(self, oid) -> str:
        if oid not in self.ent:
            return "Procesos HPUM" if self.es_hpum(oid) else "Otras"
        f = self.ent[oid].get("familia")
        return FAMILIAS.get(f) or bonito(f or "OTRA")

    def doc_nombre(self, d) -> str:
        return (self.doc.get(d) or {}).get("nombre") or (self.nodos.get(d) or {}).get("etiqueta") or str(d)

    def describir(self, obj, clase) -> str:
        if clase == "ENT":
            return f"{self.nombre(obj)} ({self.tipo(obj)})" if obj in self.ent else obj
        r = self.rel.get(obj)
        return f"{self.nombre(r['origen'])} ─ {r.get('tipo_id')} ▸ {self.nombre(r['destino'])}" if r else obj


# ====================================================================== selección
def entidades_de_sistema(ix: Indice, sistema) -> list:
    """Entidades que encajan con el nombre o alias dado: igual, o el nombre empieza por él («SIRIO» → SIRIO, SIRIO 4P, SIRIO Balances)."""
    q = norm(sistema)
    if not q:
        return []
    out = []
    for eid, e in ix.ent.items():
        nombres = [norm(x) for x in [e.get("nombre"), ix.nombre(eid), *(e.get("alias") or [])] if x]
        if eid == sistema or any(n == q or n.startswith(q + " ") for n in nombres):
            out.append(eid)
    return out


def _ambito(ix, ambito):
    amb = next((v for v in ix.amb.values() if norm(v) == norm(ambito)), None) or next((v for v in ix.amb.values() if norm(ambito) in norm(v)), None)
    if not amb and norm(ambito) != norm(SIN_AMBITO):
        raise ErrorFicha(f"No hay ningún ámbito «{ambito}». Ámbitos de la KB: {', '.join(sorted(ix.amb.values()))}.")
    return amb or SIN_AMBITO


def seleccionar(ix: Indice, modo, ambito=None, entidad=None):
    """Lo que entra en revisión: (entidades, relaciones, filtro, entidades pedidas). Sin modo y con entidad: ficha completa."""
    modo = modo_de(modo, permitir_completa=bool(entidad))
    ents = {k for k, e in ix.ent.items() if entra_en_modo(e, modo) and (modo == "COMPLETA" or not decidido(ix, k))}
    rels = {k for k, r in ix.rel.items() if entra_en_modo(r, modo) and (modo == "COMPLETA" or not decidido(ix, k))}
    filtro, pedidas = {"modo": modo}, set()
    if ambito:
        amb = _ambito(ix, ambito)
        ents = {k for k in ents if amb in (ix.ambitos(k) or [SIN_AMBITO])}
        rels = {k for k in rels if amb in (ix.ambitos_rel(ix.rel[k]) or [SIN_AMBITO])}
        filtro["ambito"] = amb
    if entidad:
        ids = entidades_de_sistema(ix, entidad)
        if not ids:
            raise ErrorFicha(f"No encuentro ninguna entidad que se llame «{entidad}» (nombre o alias).")
        pedidas = set(ids)
        ents &= pedidas
        rels = {k for k in rels if ix.rel[k]["origen"] in pedidas or ix.rel[k]["destino"] in pedidas}
        filtro["entidad"] = entidad
        filtro["entidades"] = sorted(ix.nombre(x) for x in ids)
    return ents, rels, filtro, pedidas


# ====================================================================== tarjetas (entidad + relaciones) y reparto
def anclas(ix: Indice, ents, rels, pedidas=()):
    """Tarjeta canónica de cada relación en revisión: la punta en revisión; si no, la pedida; si no, la más conectada."""
    out = {}
    for rid in rels:
        r = ix.rel[rid]
        puntas = [x for x in dict.fromkeys((r["origen"], r["destino"])) if x in ix.ent] or [r["origen"]]
        cand = [x for x in puntas if x in ents] or [x for x in puntas if x in pedidas] or puntas
        out[rid] = max(cand, key=lambda x: (len(ix.de.get(x) or []), x == r["origen"], x))
    return out


def tarjetas(ix: Indice, ents, rels, pedidas=()):
    anc = anclas(ix, ents, rels, pedidas)
    ids = set(ents) | set(anc.values()) | set(pedidas)
    out = {}
    for eid in ids:
        propias = sorted((r for r in rels if anc[r] == eid), key=lambda r: _orden_rel(ix, eid, r))
        toca = ix.de.get(eid) or []
        out[eid] = {"id": eid, "revision": eid in ents, "rels": propias,
                    "ref": sorted((r for r in toca if r in rels and anc[r] != eid), key=lambda r: _orden_rel(ix, eid, r)),
                    "ctx": sorted((r for r in toca if r not in rels), key=lambda r: _orden_rel(ix, eid, r))}
        out[eid]["peso"] = int(out[eid]["revision"]) + len(propias)
    return out, anc


def _orden_rel(ix, eid, rid):
    r = ix.rel[rid]
    otro = r["destino"] if r["origen"] == eid else r["origen"]
    return (r["origen"] != eid, r.get("tipo_id") or "", clave_es(ix.nombre(otro)), rid)


def _partes(cards, maximo):
    """Reparte tarjetas enteras (nunca se parte una entidad) en el mínimo de partes y lo más parejas posible."""
    def empaquetar(t):
        partes, actual, n = [], [], 0
        for c in cards:
            if actual and n + c["peso"] > t:
                partes.append(actual)
                actual, n = [], 0
            actual.append(c)
            n += c["peso"]
        return partes + ([actual] if actual else [])
    total = sum(c["peso"] for c in cards)
    k = max(1, -(-total // maximo))
    return next((x for t in range(max(1, -(-total // k)), maximo + 1) if len(x := empaquetar(t)) <= k), None) or empaquetar(maximo)


def agrupar(ix: Indice, cards: dict, maximo=MAX_POR_FICHA, minimo=MIN_BLOQUE):
    """Ámbito → tema (familia del catálogo) → tarjetas por nombre. Temas pequeños de un ámbito se juntan en «Varios temas»."""
    por_amb = {}
    for c in cards.values():
        amb = (ix.ambitos(c["id"]) or [SIN_AMBITO])[0]
        por_amb.setdefault(amb, {}).setdefault(ix.bloque_ent(c["id"]), []).append(c)
    fichas = []
    for amb in sorted(por_amb, key=lambda a: (a == SIN_AMBITO, clave_es(a))):
        bloques = por_amb[amb]
        peso = {b: sum(c["peso"] for c in cs) for b, cs in bloques.items()}
        pequenos = sorted((b for b in bloques if peso[b] < minimo), key=lambda b: (-peso[b], clave_es(b)))
        varios = None
        if len(pequenos) > 1:
            varios = "Varios temas (" + (", ".join(pequenos) if len(pequenos) <= 3 else ", ".join(pequenos[:3]) + f" y {len(pequenos) - 3} más") + ")"
            bloques = {b: cs for b, cs in bloques.items() if b not in pequenos} | {varios: [c for b in pequenos for c in bloques[b]]}
        for b in sorted(bloques, key=lambda x: (x == varios, -sum(c["peso"] for c in bloques[x]), clave_es(x))):
            cs = sorted(bloques[b], key=lambda c: (not c["revision"] and not c["rels"], clave_es(ix.nombre(c["id"])), c["id"]))
            partes = _partes(cs, maximo)
            for i, p in enumerate(partes, 1):
                fichas.append({"ambito": amb, "bloque": b, "parte": i, "partes": len(partes), "tarjetas": p})
    return fichas


# ====================================================================== modelo de cada elemento
def frase(ix, r, modo=None) -> str:
    o, d, t = ix.nombre(r["origen"]), ix.nombre(r["destino"]), r.get("tipo_id")
    pres = VERBOS.get(t, (bonito(t).lower(),))[0]
    return f"{o} {pres} {d}."


def pregunta_rel(ix, r) -> str:
    o, d, t = ix.nombre(r["origen"]), ix.nombre(r["destino"]), r.get("tipo_id")
    pres = VERBOS.get(t, (bonito(t).lower(),))[0]
    return f"¿{o} {pres} {d}?"


def _ubicacion(e) -> str:
    if e.get("ubicacion"):
        return str(e["ubicacion"])
    return " · ".join(f"{k} {v}" for k, v in (e.get("locator") or {}).items())


def _revision(ix, oid):
    rv = ix.rev.get(oid) or {}
    return (f"{REVISION_TXT.get(rv.get('estado'), rv.get('estado'))} por {rv.get('autor')} el {str(rv.get('en') or '')[:10]}" if rv else "Sin decisión de ninguna persona"), rv.get("estado")


def item_rel(ix: Indice, r) -> dict:
    rid = r["relacion_id"]
    rev, rev_estado = _revision(ix, rid)
    return {
        "objeto": rid, "clase": "REL", "relacion_id": rid, "firma": firma(r), "tipo_id": r.get("tipo_id"), "verbo": bonito(r.get("tipo_id")).lower(),
        "o": {"id": r["origen"], "nombre": ix.nombre(r["origen"]), "tipo": ix.tipo(r["origen"])},
        "d": {"id": r["destino"], "nombre": ix.nombre(r["destino"]), "tipo": ix.tipo(r["destino"])},
        "linea": frase(ix, r), "pregunta": pregunta_rel(ix, r), "confianza": legado(r.get("confianza"), r.get("confianza_motivos")),
        "confianza_txt": ix.estado_txt(legado(r.get("confianza"), r.get("confianza_motivos"))),
        "motivos": list(r.get("confianza_motivos") or []), "por_que_no": [MOTIVO_TXT[m] for m in r.get("confianza_motivos") or [] if m in MOTIVO_TXT],
        "validacion": r.get("validacion"), "procedencia": PROCEDENCIA.get(r.get("origen_dato"), r.get("origen_dato") or "—"),
        "ambitos": ix.ambitos_rel(r) or [SIN_AMBITO], "avisos": [AVISOS_TXT.get(a, a) for a in r.get("avisos") or []],
        "revision": rev, "revision_estado": rev_estado,
        "evidencias": [{"cita": e.get("cita") or "", "doc": ix.doc_nombre(e.get("doc_id")) if e.get("doc_id") else "", "ubicacion": _ubicacion(e),
                        "coincidencia": e.get("coincidencia") or "", "justificacion": e.get("justificacion") or ""} for e in r.get("evidencias") or []],
    }


def item_ent(ix: Indice, eid, modo) -> dict:
    e = ix.ent[eid]
    rev, rev_estado = _revision(ix, eid)
    tipo = ix.tipo(eid)
    men = [m for m in e.get("menciones") or [] if (m.get("evidencia") or {}).get("cita")]
    return {
        "objeto": eid, "clase": "ENT", "firma": firma_ent(e), "nombre": ix.nombre(eid), "tipo": tipo, "tipo_id": e.get("tipo_id"),
        "familia": FAMILIAS.get(e.get("familia")) or bonito(e.get("familia") or ""), "confianza": legado(e.get("confianza"), e.get("confianza_motivos")),
        "confianza_txt": ix.estado_txt(legado(e.get("confianza"), e.get("confianza_motivos"))),
        "motivos": list(e.get("confianza_motivos") or []), "por_que_no": [MOTIVO_TXT[m] for m in e.get("confianza_motivos") or [] if m in MOTIVO_TXT],
        "estado_kb": e.get("estado"), "revision": rev, "revision_estado": rev_estado, "ambitos": ix.ambitos(eid) or [SIN_AMBITO],
        "alias": list(e.get("alias") or []), "procedencia": PROCEDENCIA.get(e.get("origen_dato"), e.get("origen_dato") or "—"),
        "descripciones": [{"texto": d.get("texto"), "doc": ix.doc_nombre(d["doc_id"]) if d.get("doc_id") else ""} for d in (e.get("descripciones") or [])[:3] if d.get("texto")],
        "menciones": [{"cita": m["evidencia"]["cita"], "doc": ix.doc_nombre(m.get("doc_id")), "ubicacion": _ubicacion(m["evidencia"]),
                       "nombre_en_documento": m.get("nombre_en_documento") or ""} for m in men[:4]],
        "n_menciones": len(men), "documentos": [ix.doc_nombre(x) for x in e.get("documentos") or []],
        "duplicados": [{"id": did, "otra": otra, "nombre": ix.nombre(otra), "tipo": ix.tipo(otra)} for did, otra in ix.dups.get(eid) or []],
        "pregunta": (f"¿Es correcto identificar «{ix.nombre(eid)}» como {tipo.lower()}?" if modo != "OTROS_ESTADOS"
                     else f"Kortex propone identificar «{ix.nombre(eid)}» como {tipo.lower()}. ¿Es correcto?"),
    }


# ====================================================================== sello y registro local
def _obj(i):
    return i.get("objeto") or i.get("relacion_id")


def items_registro(reg) -> list:
    """Elementos a revisar de una ficha registrada (las de la primera versión solo traían relaciones)."""
    return [{**i, "objeto": _obj(i), "clase": i.get("clase") or "REL"} for i in reg.get("items") or []]


def sello(clave: bytes, ficha_id, huella, modo, items) -> str:
    datos = json.dumps({"ficha": ficha_id, "huella": huella, "modo": modo, "items": sorted([_obj(i), i["firma"]] for i in items)},
                       sort_keys=True, ensure_ascii=False)
    return hmac.new(clave, datos.encode(), hashlib.sha256).hexdigest()[:32]


class Registro:
    """Lo generado y lo importado, en %USERPROFILE%\\.kortex\\fichas_revision (fuera del repositorio y del HTML)."""

    def __init__(self, base: Path):
        self.base = Path(base)
        for p in ("fichas", "importaciones"):
            (self.base / p).mkdir(parents=True, exist_ok=True)

    def clave(self) -> bytes:
        f = self.base / "clave.bin"
        if not f.exists():
            f.write_bytes(secrets.token_bytes(32))
        return f.read_bytes()

    def guardar_ficha(self, m):
        (self.base / "fichas" / f"{m['ficha_id']}.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")

    def ficha(self, fid):
        if not re.fullmatch(r"FR-[ABC]-\d{8}-[0-9a-f]{8}", str(fid or "")):
            return None
        f = self.base / "fichas" / f"{fid}.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None

    def fichas(self):
        return [json.loads(f.read_text(encoding="utf-8")) for f in sorted((self.base / "fichas").glob("FR-*.json"))]

    def guardar_importacion(self, imp):
        (self.base / "importaciones" / f"{imp['importacion_id']}.json").write_text(json.dumps(imp, ensure_ascii=False, indent=1), encoding="utf-8")

    def importacion(self, iid):
        if not re.fullmatch(r"IMP-[0-9a-f]{8}", str(iid or "")):
            return None
        f = self.base / "importaciones" / f"{iid}.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None

    def importaciones(self):
        return sorted((json.loads(f.read_text(encoding="utf-8")) for f in (self.base / "importaciones").glob("IMP-*.json")), key=lambda x: x["importada_en"])


# ====================================================================== generación
def generar(ix: Indice, modo, huella, campana, registro: Registro, destino: Path, ambito=None, entidad=None, maximo=MAX_POR_FICHA, fecha=None, sistema=None):
    """Genera el lote: un HTML por ficha (tarjetas de entidad con sus relaciones), un índice y la cobertura."""
    entidad = entidad or sistema
    ents, rels, filtro, pedidas = seleccionar(ix, modo, ambito, entidad)
    modo = filtro["modo"]
    if not ents and not rels:
        raise ErrorFicha("No hay entidades ni relaciones con ese criterio: no se genera ninguna ficha." + (f" (filtro {filtro})" if len(filtro) > 1 else ""))
    fecha = fecha or dt.datetime.now(dt.timezone.utc)
    cards, anc = tarjetas(ix, ents, rels, pedidas)
    grupos = agrupar(ix, cards, maximo)
    clave = registro.clave()
    lote = f"{CORTO[modo]}_{fecha:%Y%m%d_%H%M%S}"
    carpeta = Path(destino) / f"fichas_{lote}"
    carpeta.mkdir(parents=True, exist_ok=True)
    # 1) identificadores y nombre de fichero de cada ficha (las referencias cruzadas los necesitan antes de pintar)
    for g in grupos:
        objetos = sorted([c["id"] for c in g["tarjetas"] if c["revision"]] + [r for c in g["tarjetas"] for r in c["rels"]])
        g["ficha_id"] = f"FR-{CORTO[modo]}-{fecha:%Y%m%d}-" + hashlib.sha256(json.dumps([huella, modo, objetos, [c['id'] for c in g['tarjetas']], fecha.isoformat()]).encode()).hexdigest()[:8]
        g["titulo"] = g["ambito"] + " · " + g["bloque"] + (f" (parte {g['parte']} de {g['partes']})" if g["partes"] > 1 else "")
        if filtro.get("entidad"):
            g["titulo"] = f"{', '.join(filtro['entidades'][:3])}" + (f" y {len(filtro['entidades']) - 3} más" if len(filtro["entidades"]) > 3 else "") + (f" · parte {g['parte']} de {g['partes']}" if g["partes"] > 1 else "")
        g["fichero"] = carpeta / f"{g['ficha_id']}_{_fichero(g['titulo'])}.html"
    donde = {c["id"]: g for g in grupos for c in g["tarjetas"]}
    fichas, vistos_e, vistos_r = [], [], []
    for g in grupos:
        tjs = []
        for c in g["tarjetas"]:
            t = {"id": c["id"], "revision": c["revision"], "nombre": ix.nombre(c["id"]), "tipo": ix.tipo(c["id"]),
                 "ent": item_ent(ix, c["id"], modo) if c["id"] in ix.ent else None,
                 "rels": [item_rel(ix, ix.rel[r]) for r in c["rels"]],
                 "ref": [{**item_rel(ix, ix.rel[r]), "en_tarjeta": anc[r], "en_tarjeta_nombre": ix.nombre(anc[r]),
                          "en_ficha": donde[anc[r]]["ficha_id"], "en_fichero": donde[anc[r]]["fichero"].name, "misma_ficha": donde[anc[r]] is g} for r in c["ref"]],
                 "ctx": [item_rel(ix, ix.rel[r]) for r in c["ctx"]]}
            tjs.append(t)
        items = [{**t["ent"], "tarjeta": t["id"]} for t in tjs if t["revision"]] + [{**i, "tarjeta": t["id"]} for t in tjs for i in t["rels"]]
        contexto = sorted({t["id"] for t in tjs if not t["revision"] and t["ent"]} | {i["objeto"] for t in tjs for i in t["ctx"]})
        m = {"formato": FORMATO_FICHA, "ficha_id": g["ficha_id"], "lote": lote, "modo": modo, "modo_txt": MODOS[modo], "campana": campana, "huella": huella,
             "generada": fecha.strftime("%Y-%m-%dT%H:%M:%SZ"), "titulo": g["titulo"], "ambito": g["ambito"], "bloque": g["bloque"], "parte": g["parte"],
             "partes": g["partes"], "filtro": filtro, "tarjetas": tjs, "items": items, "contexto": contexto,
             "tipos": [[t, tipo_txt(t)] for t in ix.tipos], "tipos_rel": [[t, VERBOS.get(t, (bonito(t).lower(),))[0]] for t in ix.tipos_rel]}
        m["sello"] = sello(clave, m["ficha_id"], huella, modo, items)
        g["fichero"].write_text(html(m), encoding="utf-8")
        m["fichero"] = str(g["fichero"])
        registro.guardar_ficha({k: v for k, v in m.items() if k not in ("tarjetas", "items", "tipos", "tipos_rel")}
                               | {"items": [{"objeto": i["objeto"], "clase": i["clase"], "firma": i["firma"], "confianza": i["confianza"], "ambitos": i["ambitos"],
                                             "revision_estado": i["revision_estado"]} for i in items],
                                  "secciones": [{"id": t["id"], "titulo": t["nombre"], "tipo": t["tipo"]} for t in tjs]})
        fichas.append(m)
        vistos_e += [i["objeto"] for i in items if i["clase"] == "ENT"]
        vistos_r += [i["objeto"] for i in items if i["clase"] == "REL"]
    cob = cobertura(ix, ents, rels, vistos_e, vistos_r, fichas)
    if cob["entidades"]["perdidas"] or cob["entidades"]["repetidas"] or cob["relaciones"]["perdidas"] or cob["relaciones"]["repetidas"]:
        raise ErrorFicha(f"Reparto incoherente: {cob['entidades']} / {cob['relaciones']}. No se dan por buenas estas fichas.")
    cob.update({"lote": lote, "modo": modo, "huella": huella, "campana": campana, "generada": fecha.strftime("%Y-%m-%dT%H:%M:%SZ"), "filtro": filtro,
                "fichas": [{"ficha_id": m["ficha_id"], "titulo": m["titulo"], "entidades": sum(1 for i in m["items"] if i["clase"] == "ENT"),
                            "relaciones": sum(1 for i in m["items"] if i["clase"] == "REL"), "tarjetas": len(m["tarjetas"]),
                            "fichero": Path(m["fichero"]).name} for m in fichas]})
    (carpeta / "cobertura.json").write_text(json.dumps(cob, ensure_ascii=False, indent=1), encoding="utf-8")
    (carpeta / "indice.html").write_text(html_indice(cob, fichas), encoding="utf-8")
    return carpeta, cob, fichas


def cobertura(ix, ents, rels, vistos_e, vistos_r, fichas) -> dict:
    def rep(esperadas, vistos):
        return {"seleccionadas": len(esperadas), "a_revisar": len(vistos), "perdidas": sorted(set(esperadas) - set(vistos)),
                "repetidas": sorted({x for x in vistos if vistos.count(x) > 1})}
    ctx_e = {t["id"] for m in fichas for t in m["tarjetas"] if not t["revision"]}
    ctx_r = {i["objeto"] for m in fichas for t in m["tarjetas"] for i in t["ctx"]}
    refs = sum(len(t["ref"]) for m in fichas for t in m["tarjetas"])
    est = lambda x: legado(x.get("confianza"), x.get("confianza_motivos"))  # noqa: E731
    conf = lambda xs, src: {k: sum(1 for x in xs if est(src[x]) == k) for k in sorted({est(src[x]) for x in xs})}  # noqa: E731
    return {"entidades": {**rep(ents, vistos_e), "solo_contexto": len(ctx_e), "por_confianza": conf(ents, ix.ent), "total_kb": len(ix.ent),
                          "fuera_del_lote": len(ix.ent) - len(set(ents) | ctx_e)},
            "relaciones": {**rep(rels, vistos_r), "solo_contexto": len(ctx_r), "referencias_a_otra_tarjeta": refs, "por_confianza": conf(rels, ix.rel),
                           "total_kb": len(ix.rel), "fuera_del_lote": len(ix.rel) - len(set(rels) | ctx_r)},
            "entidades_sin_relaciones_a_revisar": sum(1 for m in fichas for t in m["tarjetas"] if t["revision"] and not t["rels"])}


def _fichero(s) -> str:
    s = unicodedata.normalize("NFKD", str(s))
    s = re.sub(r"[̀-ͯ]", "", s)
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:70] or "ficha"


# ====================================================================== importación (no toca la KB)
def leer_respuestas(texto: str) -> dict:
    try:
        j = json.loads(texto)
    except ValueError:
        raise ErrorFicha("El fichero no es un JSON válido: tiene que ser el que descarga la ficha («Descargar respuestas»).") from None
    if not isinstance(j, dict) or j.get("formato") not in (FORMATO_RESPUESTAS, FORMATO_RESPUESTAS_V1):
        raise ErrorFicha(f"No es un fichero de respuestas de ficha de Kortex (formato esperado {FORMATO_RESPUESTAS}).")
    return j


_CAMPOS = ("observaciones", "motivo", "correccion", "aportacion", "nombre_nuevo", "tipo_nuevo", "duplicado_de")


def importar(texto: str, registro: Registro, ix_actual: Indice, huella_actual: str, usuario: str, nombre_fichero="", reloj=ahora_iso) -> dict:
    """Valida un fichero de respuestas y devuelve la importación (no la guarda ni escribe en la KB). Lanza ErrorFicha si no es fiable."""
    j = leer_respuestas(texto)
    huella_fichero = hashlib.sha256(texto.encode("utf-8")).hexdigest()
    previa = next((x for x in registro.importaciones() if x.get("huella_fichero") == huella_fichero), None)
    if previa:
        raise ErrorFicha(f"Este fichero ya se importó como {previa['importacion_id']} el {previa['importada_en']}: no se cuenta dos veces.")
    fid = j.get("ficha_id")
    reg = registro.ficha(fid)
    if not reg:
        raise ErrorFicha(f"La ficha «{fid}» no la generó este MCP (no está en su registro): no se puede comprobar que sea auténtica.")
    problemas = []
    esperadas = {i["objeto"]: i for i in items_registro(reg)}
    if j.get("sello") != reg["sello"] or not hmac.compare_digest(sello(registro.clave(), fid, reg["huella"], reg["modo"], list(esperadas.values())), reg["sello"]):
        problemas.append("el sello de la ficha no coincide")
    for k in ("huella", "modo"):
        if j.get(k) != reg.get(k):
            problemas.append(f"«{k}» no es el de la ficha generada")
    if j["formato"] == FORMATO_RESPUESTAS:
        if not isinstance(j.get("entidades"), list) or not isinstance(j.get("relaciones"), list):
            raise ErrorFicha("El fichero no trae las listas de entidades y relaciones.")
        entradas = [("ENT", x, (x or {}).get("entidad_id") if isinstance(x, dict) else None) for x in j["entidades"]] + \
                   [("REL", x, (x or {}).get("relacion_id") if isinstance(x, dict) else None) for x in j["relaciones"]]
    else:
        if not isinstance(j.get("respuestas"), list):
            raise ErrorFicha("El fichero no trae la lista de respuestas.")
        entradas = [("REL", x, x.get("relacion_id") if isinstance(x, dict) else None) for x in j["respuestas"]]
    vistas = {}
    for clase, x, obj in entradas:
        if not isinstance(x, dict):
            problemas.append("hay una respuesta que no es un objeto")
            continue
        if obj not in esperadas or esperadas[obj]["clase"] != clase:
            problemas.append(f"{obj} no se revisa en esta ficha")
        elif x.get("firma") != esperadas[obj]["firma"]:
            problemas.append(f"la firma de {obj} no coincide: la respuesta no es de ese elemento")
        elif obj in vistas:
            problemas.append(f"{obj} aparece dos veces")
        if x.get("respuesta") not in RESP[clase]:
            problemas.append(f"respuesta no válida en {obj}: {str(x.get('respuesta'))[:40]}")
        vistas[obj] = x
    contexto = []
    permitidos = set(reg.get("contexto") or [])
    for c in j.get("contexto") or []:
        if not isinstance(c, dict) or c.get("objeto") not in permitidos:
            problemas.append("hay una observación de contexto sobre algo que no está en la ficha")
            continue
        if limpio(c.get("texto")):
            contexto.append({"objeto": c["objeto"], "clase": "ENT" if c["objeto"] in ix_actual.ent else "REL", "texto": limpio(c.get("texto"))})
    conjuntos = []
    secciones = {x["id"]: x for x in reg.get("secciones") or [] if isinstance(x, dict)}
    for c in j.get("conjuntos") or []:                       # solo la primera versión (respuesta por conjunto)
        if not isinstance(c, dict) or c.get("seccion") not in secciones or c.get("respuesta") not in RESPUESTAS_CONJUNTO:
            problemas.append("hay un conjunto que no es de esta ficha o con una respuesta no válida")
            continue
        conjuntos.append({"seccion": c["seccion"], "titulo": secciones[c["seccion"]].get("titulo"), "respuesta": c["respuesta"],
                          "comentario": limpio(c.get("comentario")), "aportacion": limpio(c.get("aportacion"))})
    if problemas:
        raise ErrorFicha("Fichero rechazado, parece manipulado o no es de esta ficha: " + "; ".join(dict.fromkeys(problemas))[:1500])
    rev = j.get("revisor") if isinstance(j.get("revisor"), dict) else {}
    revisor = {k: limpio(rev.get(k), 200) for k in ("nombre", "correo", "ambito")}
    avisos = []
    faltan = [o for o in esperadas if o not in vistas]
    if faltan:
        avisos.append(f"Ficha incompleta: {len(faltan)} elementos no vienen en el fichero (cuentan como sin revisar).")
    if not revisor["nombre"] and not revisor["correo"]:
        avisos.append("El fichero no identifica al revisor (nombre o correo).")
    gen = reg["generada"]
    previas = [x for x in registro.importaciones() if x.get("estado") != "ANULADA"]
    items = []
    for obj, e in esperadas.items():
        x = vistas.get(obj) or {"respuesta": "SIN_REVISAR"}
        clase = e["clase"]
        it = {"objeto": obj, "clase": clase, "relacion_id": obj if clase == "REL" else None, "firma": e["firma"], "respuesta": x["respuesta"],
              **{k: limpio(x.get(k), 200 if k in ("nombre_nuevo", "tipo_nuevo", "duplicado_de") else MAX_TEXTO) for k in _CAMPOS},
              "via": "grupo" if x.get("via") == "grupo" else "individual", "ambitos": e.get("ambitos") or [], "en_fichero": obj in vistas,
              "estado": "OK", "notas": []}
        actual = (ix_actual.ent if clase == "ENT" else ix_actual.rel).get(obj)
        if actual is None:
            it["estado"], it["notas"] = "DESAPARECIDA", ["ya no está en la KB actual"]
        elif firma_de(ix_actual, obj, clase) != e["firma"]:
            it["estado"], it["notas"] = "OBSOLETA", ["ha cambiado en la KB desde que se generó la ficha"
                                                     + (" (puntas, tipo o citas)" if clase == "REL" else " (nombre, tipo o alias)")]
        else:
            if huella_actual != reg["huella"]:
                it["notas"].append("la KB ha cambiado desde la ficha, pero este elemento sigue igual")
            antes, ahora = legado(e.get("confianza")), legado(actual.get("confianza"), actual.get("confianza_motivos"))
            if antes != ahora:
                it["notas"].append(f"su estado ha cambiado: {estado_txt(antes)} → {estado_txt(ahora)}")
            dec = ix_actual.rev.get(obj)
            if dec and str(dec.get("en") or "") > gen:
                it["estado"] = "CONFLICTO"
                it["notas"].append(f"una persona lo decidió después de generar la ficha ({REVISION_TXT.get(dec.get('estado'), dec.get('estado'))}, {dec.get('autor')}, {str(dec.get('en'))[:16]})")
            elif dec and ((dec.get("estado") == "RECHAZADA" and it["respuesta"] == "CORRECTA") or (dec.get("estado") == "APROBADA" and it["respuesta"] == "INCORRECTA")):
                it["estado"] = "CONFLICTO"
                it["notas"].append(f"contradice la decisión ya guardada ({REVISION_TXT.get(dec.get('estado'))}, {dec.get('autor')})")
        if it["respuesta"] in PIDE_MOTIVO and not it["motivo"]:
            it["notas"].append("falta el motivo del revisor")
        if it["respuesta"] == "CORRECTA" or it["respuesta"] in CON_CAMBIO:
            for p in previas:
                otra = next((y for y in p["items"] if (y.get("objeto") or y.get("relacion_id")) == obj
                             and (y["respuesta"] == "CORRECTA" or y["respuesta"] in CON_CAMBIO)), None)
                if not otra:
                    continue
                quien = p["revisor_declarado"].get("nombre") or p["revisor_declarado"].get("correo") or "otro revisor"
                txt = RESP[clase].get(otra["respuesta"], otra["respuesta"])
                if (otra["respuesta"] == "CORRECTA") != (it["respuesta"] == "CORRECTA"):
                    it["estado"] = "CONFLICTO" if it["estado"] == "OK" else it["estado"]
                    it["notas"].append(f"choca con la revisión {p['importacion_id']} de {quien}: «{txt}»")
                else:
                    it["notas"].append(f"coincide con la revisión {p['importacion_id']} de {quien}")
        items.append(it)
    iid = "IMP-" + hashlib.sha256((huella_fichero + reloj()).encode()).hexdigest()[:8]
    return {"importacion_id": iid, "estado": "IMPORTADA", "importada_en": reloj(), "importada_por": usuario, "fichero": nombre_fichero, "huella_fichero": huella_fichero,
            "formato": j["formato"], "ficha_id": fid, "ficha_titulo": reg["titulo"], "modo": reg["modo"], "huella_ficha": reg["huella"],
            "huella_kb_al_importar": huella_actual, "revisor_declarado": revisor, "exportado_en": limpio(j.get("exportado_en"), 40), "avisos": avisos,
            "items": items, "contexto": contexto, "conjuntos": conjuntos}


def _norm_imp(imp):
    for i in imp["items"]:
        i.setdefault("objeto", i.get("relacion_id"))
        i.setdefault("clase", "REL")
        for k in _CAMPOS:
            i.setdefault(k, "")
    imp.setdefault("contexto", [])
    return imp


def resumen_importacion(imp: dict) -> dict:
    imp = _norm_imp(imp)
    out = {}
    for clase in ("ENT", "REL"):
        c = {k: 0 for k in RESP[clase]}
        for i in imp["items"]:
            if i["clase"] == clase:
                c[i["respuesta"]] = c.get(i["respuesta"], 0) + 1
        out[clase] = c
    est = {}
    for i in imp["items"]:
        est[i["estado"]] = est.get(i["estado"], 0) + 1
    return {"ENT": out["ENT"], "REL": out["REL"], "respuestas": out["REL"], "estados": est,
            "aportaciones": sum(1 for i in imp["items"] if i["aportacion"]) + sum(1 for x in imp.get("conjuntos") or [] if x["aportacion"]),
            "en_grupo": sum(1 for i in imp["items"] if i["via"] == "grupo" and i["respuesta"] == "CORRECTA"), "contexto": len(imp["contexto"])}


# ====================================================================== previsualización de cambios (no escribe)
def plan(imp: dict, ix: Indice, acreditacion=None, ambito_acreditado=None) -> dict:
    """Qué decisiones habría que guardar y su impacto. Sin acreditación del revisor no se propone ninguna escritura: el equipo Kortex
    administra el procedimiento, pero no valida el conocimiento funcional de otros equipos. Cada elemento, su propia decisión."""
    imp = _norm_imp(imp)
    acreditado = len(limpio(acreditacion)) >= 10
    amb = ambito_acreditado.strip() if isinstance(ambito_acreditado, str) and ambito_acreditado.strip() else None
    rd = imp["revisor_declarado"]
    quien = rd.get("nombre") or rd.get("correo") or "revisor sin identificar"
    base = f"Ficha {imp['ficha_id']} · {imp['importacion_id']} · revisor declarado: {quien}" + (f" <{rd['correo']}>" if rd.get("correo") and rd.get("nombre") else "")
    base += f" · acreditado por {imp['importada_por']}: {limpio(acreditacion, 120)}" if acreditado else ""
    claves = ("aprobar", "rechazar", "corregir_nombre", "corregir_tipo", "invertir", "corregir_relacion", "fusionar", "por_interpretar", "corregir",
              "sin_cambio", "fuera_ambito", "excluidas", "aportaciones", "pendiente_acreditar", "observaciones_contexto", "impactos")
    filas = {k: [] for k in claves}
    juntas, decisiones, extra_ops = {"ENT": [], "REL": []}, [], []

    def impacto(obj, accion):
        rs = ix.de.get(obj) or []
        filas["impactos"].append({"objeto": obj, "entidad": ix.describir(obj, "ENT"), "accion": accion, "n": len(rs),
                                  "relaciones": [ix.describir(r, "REL") for r in rs[:8]]})

    for i in imp["items"]:
        obj, clase, resp = i["objeto"], i["clase"], i["respuesta"]
        fila = {"objeto": obj, "clase": clase, "relacion_id": obj, "relacion": ix.describir(obj, clase), "descripcion": ix.describir(obj, clase),
                "respuesta": RESP[clase].get(resp, resp), "notas": i["notas"], **{k: i[k] for k in _CAMPOS}}
        if i["aportacion"]:
            filas["aportaciones"].append(fila)
        if resp in ("SIN_REVISAR", "SIN_INFORMACION"):
            filas["sin_cambio"].append(fila)
            continue
        if resp == "FUERA_DE_AMBITO":
            filas["fuera_ambito"].append(fila)
            continue
        if firma_de(ix, obj, clase) != i["firma"]:
            filas["excluidas"].append({**fila, "motivo_exclusion": "ya no está o ha cambiado en la KB actual"})
            continue
        if i["estado"] != "OK":
            filas["excluidas"].append({**fila, "motivo_exclusion": f"{i['estado'].lower()}: " + "; ".join(i["notas"])})
            continue
        if amb and amb not in (i.get("ambitos") or []):
            filas["excluidas"].append({**fila, "motivo_exclusion": f"fuera del ámbito acreditado ({amb})"})
            continue
        if not acreditado:
            filas["pendiente_acreditar"].append(fila)
            continue
        rv = (ix.rev.get(obj) or {}).get("estado")
        if resp in MANUALES:                   # 23/11/2026: dirección, otro tipo y duplicado se aplican; los matices, por interpretar
            nota = i["motivo"] or i["observaciones"]
            if resp == "DIRECCION" and clase == "REL":
                filas["invertir"].append(fila)
                extra_ops.append({"op": "INVERTIR_RELACION", "relacion": obj, "motivo": limpio(f"{base} · la dirección está al revés" + (f": {nota}" if nota else ""), 500)})
                continue
            t = i["tipo_nuevo"].strip().upper()
            if resp == "OTRO_TIPO" and clase == "REL" and t in (set(VERBOS) | set(ix.tipos_rel)) and t != (ix.rel.get(obj) or {}).get("tipo_id"):
                filas["corregir_relacion"].append({**fila, "nuevo": t})
                extra_ops.append({"op": "CORREGIR_RELACION", "relacion": obj, "tipo_id": t, "motivo": limpio(f"{base} · otro tipo de relación según el revisor"
                                                                                                          + (f": {nota}" if nota else ""), 500)})
                continue
            if resp == "DUPLICADO" and clase == "ENT":
                dd = i["duplicado_de"]
                dup = next((d for d, otra in ix.dups.get(obj) or [] if dd in (otra, d) or norm(ix.nombre(otra)) == norm(dd)), None)
                otra = dd if dd in ix.ent else next((o for _, o in ix.dups.get(obj) or [] if norm(ix.nombre(o)) == norm(dd)), None) \
                    or (lambda xs: xs[0] if len(xs) == 1 else None)([e for e in ix.ent if e != obj and norm(ix.nombre(e)) == norm(dd)])
                if otra and otra != obj:
                    filas["fusionar"].append({**fila, "dup_id": dup, "otra": ix.nombre(otra), "otra_id": otra})
                    impacto(obj, f"se fusiona en «{ix.nombre(otra)}»")
                    extra_ops.append({"op": "FUSIONAR_ENTIDADES", "conservar": otra, "absorber": [obj],
                                      "motivo": limpio(f"{base} · es la misma entidad que «{ix.nombre(otra)}» según el revisor" + (f": {nota}" if nota else ""), 500)})
                    continue
            filas["por_interpretar"].append(por_interpretar(ix, i, fila))
            continue
        if resp == "CORRECTA":
            if rv == "APROBADA":
                filas["sin_cambio"].append({**fila, "notas": [*i["notas"], "ya estaba aprobada"]})
                continue
            filas["aprobar"].append(fila)
            if i["observaciones"]:
                decisiones.append({"accion": "APROBAR", "bloque": {"criterio": "ids", "valor": [obj]}, "parametros": {},
                                   "motivo": limpio(f"{base} · observaciones: {i['observaciones']}", 500)})
            else:
                juntas[clase].append(obj)
        elif resp == "INCORRECTA":
            if not i["motivo"]:
                filas["excluidas"].append({**fila, "motivo_exclusion": "sin motivo del revisor: hay que pedírselo antes de rechazar"})
                continue
            if rv == "RECHAZADA":
                filas["sin_cambio"].append({**fila, "notas": [*i["notas"], "ya estaba rechazada"]})
                continue
            filas["rechazar"].append(fila)
            if clase == "ENT":
                impacto(obj, "rechazo de la entidad (sus relaciones NO se rechazan)")
            decisiones.append({"accion": "RECHAZAR", "bloque": {"criterio": "ids", "valor": [obj]}, "parametros": {},
                               "motivo": limpio(f"{base} · motivo: {i['motivo']}" + (f" · corrección propuesta: {i['correccion']}" if i["correccion"] else ""), 500)})
            if clase == "REL" or i["correccion"]:           # 23/11/2026: rechazar lo falso va junto con proponer lo verdadero
                pi = por_interpretar(ix, i, fila)
                if pi["sugerencias"] or i["correccion"] or len(i["motivo"]) > 25:
                    filas["por_interpretar"].append({**pi, "ya_se_rechaza": True})
        elif resp == "CORREGIR_NOMBRE":
            n = i["nombre_nuevo"].strip()
            if not 2 <= len(n) <= 160:
                filas["excluidas"].append({**fila, "motivo_exclusion": "falta el nombre correcto (2–160 caracteres)"})
                continue
            filas["corregir_nombre"].append({**fila, "nuevo": n})
            impacto(obj, f"nombre «{ix.nombre(obj)}» → «{n}»")
            decisiones.append({"accion": "CORREGIR_NOMBRE", "bloque": {"criterio": "ids", "valor": [obj]}, "parametros": {"nombre": n},
                               "motivo": limpio(f"{base} · nombre correcto según el revisor" + (f": {i['motivo']}" if i["motivo"] else ""), 500)})
        elif resp == "CORREGIR_TIPO":
            t = i["tipo_nuevo"].strip()
            if t not in ix.tipos:
                filas["excluidas"].append({**fila, "motivo_exclusion": f"tipo «{t or '—'}» no es del catálogo en uso"})
                continue
            filas["corregir_tipo"].append({**fila, "nuevo": t})
            impacto(obj, f"tipo {ix.ent[obj].get('tipo_id')} → {t}")
            decisiones.append({"accion": "CORREGIR_TIPO", "bloque": {"criterio": "ids", "valor": [obj]}, "parametros": {"tipo_id": t},
                               "motivo": limpio(f"{base} · tipo correcto según el revisor" + (f": {i['motivo']}" if i["motivo"] else ""), 500)})
    for c in imp.get("conjuntos") or []:
        if c["aportacion"]:
            filas["aportaciones"].append({"objeto": "conjunto", "clase": "", "relacion_id": "conjunto", "relacion": f"Conjunto «{c['titulo']}»",
                                          "descripcion": f"Conjunto «{c['titulo']}»", "respuesta": RESPUESTAS_CONJUNTO[c["respuesta"]], "notas": [],
                                          **{k: "" for k in _CAMPOS}, "observaciones": c["comentario"], "aportacion": c["aportacion"]})
    for c in imp["contexto"]:
        filas["observaciones_contexto"].append({"objeto": c["objeto"], "clase": c["clase"], "descripcion": ix.describir(c["objeto"], c["clase"]), "texto": c["texto"]})
    for clase in ("REL", "ENT"):
        for k in range(0, len(juntas[clase]), 2000):
            decisiones.insert(0, {"accion": "APROBAR", "bloque": {"criterio": "ids", "valor": juntas[clase][k:k + 2000]}, "parametros": {},
                                  "motivo": limpio(f"{base} · {'entidades' if clase == 'ENT' else 'relaciones'} confirmadas en la ficha", 500)})
    ops = [a_operacion(d) for d in decisiones] + extra_ops
    return {"importacion_id": imp["importacion_id"], "ficha_id": imp["ficha_id"], "acreditado": acreditado, "ambito_acreditado": amb,
            "revisor_declarado": rd, "importada_por": imp["importada_por"], "filas": filas, "decisiones": decisiones, "operaciones": ops,
            "base": base}


def a_operacion(d: dict) -> dict:
    """Decisión de la ficha → operación de la API de operaciones (kbweb_operaciones)."""
    ids, par, m = d["bloque"]["valor"], d.get("parametros") or {}, d.get("motivo") or ""
    if d["accion"] == "APROBAR":
        return {"op": "VALIDAR", "ids": ids, "motivo": m}
    if d["accion"] == "RECHAZAR":
        return {"op": "RECHAZAR", "ids": ids, "motivo": m}
    if d["accion"] == "CORREGIR_NOMBRE":
        return {"op": "CORREGIR_NOMBRE", "entidad": ids[0], "nombre": par["nombre"], "motivo": m}
    if d["accion"] == "CORREGIR_TIPO":
        return {"op": "CORREGIR_TIPO", "ids": ids, "tipo_id": par["tipo_id"], "motivo": m}
    raise ValueError(d["accion"])


_REVES = re.compile(r"al reves|invers|sentido contrario|direccion contraria|es al contrario|justo lo contrario|de forma inversa")


def por_interpretar(ix: Indice, i: dict, fila: dict) -> dict:
    """Respuesta con matiz (o rechazo con la corrección escrita): todo lo que Claude necesita para proponer la operación buena, y sugerencias
    deterministas (entidades y tipos de relación que el revisor nombra en su comentario). Nada se aplica sin que alguien lo traduzca."""
    obj, clase = i["objeto"], i["clase"]
    texto = " · ".join(x for x in (i["motivo"], i["correccion"], i["observaciones"], i["aportacion"]) if x)
    t = norm(texto)
    out = {**fila, "comentario": texto, "sugerencias": []}
    if clase == "REL" and obj in ix.rel:
        r = ix.rel[obj]
        out.update({"origen": {"id": r["origen"], "nombre": ix.nombre(r["origen"])}, "tipo_id": r.get("tipo_id"),
                    "destino": {"id": r["destino"], "nombre": ix.nombre(r["destino"])}})
    elif clase == "ENT" and obj in ix.ent:
        out["relaciones"] = [{"id": rid, "texto": ix.describir(rid, "REL")} for rid in (ix.de.get(obj) or [])[:15]]
    if not t:
        return out
    tipos = [k for k, (v, inf) in VERBOS.items() if f" {norm(v)} " in f" {t} " or f" {norm(inf)} " in f" {t} "]
    ya = {obj} | ({ix.rel[obj]["origen"], ix.rel[obj]["destino"]} if obj in ix.rel else set())
    nombradas = sorted({eid for eid, e in ix.ent.items() if eid not in ya and len(norm(e.get("nombre"))) >= 4 and f" {norm(e.get('nombre'))} " in f" {t} "},
                       key=lambda e: -len(norm(ix.nombre(e))))[:5]
    out["entidades_nombradas"] = [{"id": e, "nombre": ix.nombre(e), "tipo": ix.tipo(e)} for e in nombradas]
    out["tipos_nombrados"] = tipos
    if clase == "REL" and obj in ix.rel:
        r = ix.rel[obj]
        if _REVES.search(t):
            out["sugerencias"].append({"op": "INVERTIR_RELACION", "relacion": obj, "motivo": texto})
        for e in nombradas[:2]:
            for tp in (tipos[:1] or [r.get("tipo_id")]):
                out["sugerencias"].append({"op": "CORREGIR_RELACION", "relacion": obj, "destino": e, "tipo_id": tp, "motivo": texto,
                                           "_lectura": f"{ix.nombre(r['origen'])} ─ {tp} ▸ {ix.nombre(e)}"})
                out["sugerencias"].append({"op": "CORREGIR_RELACION", "relacion": obj, "origen": e, "tipo_id": tp, "motivo": texto,
                                           "_lectura": f"{ix.nombre(e)} ─ {tp} ▸ {ix.nombre(r['destino'])}"})
        if tipos and not nombradas and tipos[0] != r.get("tipo_id"):
            out["sugerencias"].append({"op": "CORREGIR_RELACION", "relacion": obj, "tipo_id": tipos[0], "motivo": texto,
                                       "_lectura": f"{ix.nombre(r['origen'])} ─ {tipos[0]} ▸ {ix.nombre(r['destino'])}"})
    return out


# ====================================================================== HTML de la ficha (formato sencillo: una pregunta por entidad)
# La persona responde UNA pregunta por tarjeta («¿Es correcta esta representación?»). Lo que no encaje se marca como excepción en la
# línea concreta. Al descargar, cada entidad y cada relación lleva su propia respuesta: la de la tarjeta, salvo sus excepciones.
EXC = {"ENT": {"CORRECTA": "Esta sí es correcta", "CORREGIR_NOMBRE": "El nombre no es correcto", "CORREGIR_TIPO": "El tipo no es correcto",
               "DUPLICADO": "Es la misma que otra entidad", "INCORRECTA": "No es una entidad válida", "PARCIAL": "Hay que matizarla",
               "SIN_INFORMACION": "No lo sé", "FUERA_DE_AMBITO": "No es de mi ámbito"},
       "REL": {"CORRECTA": "Esta sí es correcta", "INCORRECTA": "No es cierta", "PARCIAL": "Hay que matizarla", "OTRO_TIPO": "Es otro tipo de relación",
               "DIRECCION": "La dirección está al revés", "SIN_INFORMACION": "No lo sé", "FUERA_DE_AMBITO": "No es de mi ámbito"}}
EXC_TXT = {**EXC["ENT"], **EXC["REL"]}

CSS = r"""
:root{--ink:#17101d;--ink2:#4a4152;--muted:#6b6272;--line:#e7e1ec;--line2:#f1edf4;--bg:#faf8fb;--card:#fff;--p:#7500c0;--p-ink:#5c0097;--p-soft:#f5ecfb;
--amber:#8a5300;--amber-soft:#fff3df;--green:#17714a;--green-soft:#e8f5ee;--red:#a3241b;--red-soft:#fdecea;--ctx:#8a8292;--focus:#7500c0}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 "Segoe UI",system-ui,-apple-system,"Helvetica Neue",Arial,sans-serif}
.page{max-width:860px;margin:0 auto;padding:28px 20px 80px}
.marca{font:600 12px/1 "Segoe UI",system-ui,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:var(--p)}
h1{font-size:24px;line-height:1.25;margin:8px 0 6px;letter-spacing:-.01em}
.meta{font-size:13px;color:var(--muted);margin:0 0 14px}.meta b{color:var(--ink2);font-weight:600}
.intro{margin:0 0 16px;color:var(--ink2);padding-left:10px;border-left:3px solid var(--p)}.intro.b{border-left-color:var(--amber)}
.revisor{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px;margin:0 0 6px}
input[type=text],input[type=email],input[type=search],textarea,select{font:inherit;color:var(--ink);border:1px solid #cfc6d6;border-radius:8px;padding:7px 9px;background:#fff;width:100%}
textarea{min-height:56px;resize:vertical}select{width:auto;max-width:100%}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
.nota{font-size:12.5px;color:var(--muted);margin:0 0 16px}
.barra{position:sticky;top:0;z-index:5;background:rgba(250,248,251,.96);backdrop-filter:blur(4px);border-bottom:1px solid var(--line);margin:0 -20px 8px;padding:10px 20px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.barra .estado{flex:1 1 240px;font-size:13px;color:var(--ink2)}.barra input[type=search]{flex:0 1 200px;width:auto}
.btn{font:600 14px/1 "Segoe UI",system-ui,sans-serif;border:1px solid var(--p);background:var(--p);color:#fff;border-radius:8px;padding:9px 13px;cursor:pointer}
.btn.sec{background:#fff;color:var(--p-ink)}.btn:hover{filter:brightness(1.07)}
.mini{font:inherit;font-size:12.5px;border:0;background:none;color:var(--p-ink);cursor:pointer;padding:0 2px;text-decoration:underline;text-underline-offset:2px}
.msg{font-size:13px;color:var(--ink2);flex-basis:100%}.msg:empty{display:none}.msg.mal{color:var(--red)}
.conj{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:16px 0}
.conj[hidden]{display:none}
.conj[data-r=SI]{border-color:#bfe0cd}.conj[data-r=PARCIAL]{border-color:#f0d29a}.conj[data-r=NO]{border-color:#f1bcb6}
.cab{display:flex;gap:10px;align-items:baseline;justify-content:space-between;flex-wrap:wrap}
.cab h2{font-size:17px;margin:0}.cab .tipo{font-size:12.5px;color:var(--muted);font-weight:400}
.marca-r{font-size:12px;font-weight:600;border-radius:999px;padding:2px 10px;background:var(--line2);color:var(--ink2)}
.conj[data-r=SI] .marca-r{background:var(--green-soft);color:var(--green)}.conj[data-r=PARCIAL] .marca-r{background:var(--amber-soft);color:var(--amber)}
.conj[data-r=NO] .marca-r{background:var(--red-soft);color:var(--red)}
.desc{margin:4px 0 0;font-size:13.5px;color:var(--ink2)}
.lead{font-weight:600;margin:12px 0 6px}
ul.lineas{list-style:none;margin:0 0 6px;padding:0}
.linea{padding:7px 0;border-bottom:1px solid var(--line2)}.linea:last-child{border-bottom:0}
.fila{display:flex;gap:10px;align-items:flex-start;flex-wrap:wrap}
.ico{flex:0 0 18px;width:18px;height:18px;margin-top:2px;color:var(--ink2)}
.linea[data-x] .ico{color:var(--red)}.linea[data-x=CORRECTA] .ico{color:var(--green)}
.txt{flex:1 1 260px;min-width:0}
.linea.ctx .txt{color:var(--ctx)}
.etq{font-size:11.5px;border-radius:999px;padding:1px 7px;margin-left:6px;white-space:nowrap}
.sin{color:var(--amber);background:var(--amber-soft)}.ctxe{color:var(--ctx);border:1px dashed var(--ctx)}
.exc-tag{color:var(--red);background:var(--red-soft)}.exc-tag.ok{color:var(--green);background:var(--green-soft)}.exc-tag[hidden]{display:none}
.acc{white-space:nowrap;font-size:12.5px;color:var(--muted)}
.ev,.exc,.det,.ctx-err{margin:6px 0 2px 28px;font-size:13px;color:var(--ink2)}
.ev q,.det q{display:block;quotes:"«" "»";background:#fbf9fc;border-left:3px solid #d9c2ec;padding:4px 9px;border-radius:0 6px 6px 0;color:var(--ink);margin-bottom:3px}
.ev small,.det small{display:block;color:var(--muted);margin:0 0 5px}
.exc{padding:8px 10px;border:1px dashed #e3b9b3;border-radius:8px;background:#fffafa}
.exc .ops{display:flex;flex-wrap:wrap;gap:4px 14px;margin-bottom:6px}
.exc .ops label{display:flex;align-items:center;gap:5px;cursor:pointer}.exc .ops input{accent-color:var(--p)}
.exc .campos{display:flex;flex-wrap:wrap;gap:6px}.exc .campos input{flex:1 1 220px}
.ev[hidden],.exc[hidden],.det[hidden],.ctx-err[hidden],.exc select[hidden]{display:none}
.pregunta{border:0;padding:0;margin:14px 0 0}
.pregunta legend{font-weight:700;margin-bottom:6px;font-size:14.5px;padding:0}
.op{display:flex;align-items:center;gap:10px;padding:4px 0;font-size:15px;cursor:pointer}
.op input{width:18px;height:18px;accent-color:var(--p);margin:0}
.ops2{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:13px;color:var(--ink2);margin:2px 0 0 28px}
.ops2 label{display:flex;align-items:center;gap:6px;cursor:pointer}.ops2 input{accent-color:var(--p)}
.comentario{margin-top:10px}
.falta{display:none;color:var(--red);font-size:12.5px;margin:4px 0 0}.conj.sin-comentario .falta{display:block}
details.aporta summary,details.tambien summary{cursor:pointer;font-size:13px;color:var(--p-ink);margin-top:8px}
details.aporta textarea{margin-top:6px}
details.tambien .linea{font-size:13.5px}
.rid{font:11.5px/1.4 ui-monospace,Consolas,monospace;color:var(--muted)}
.vacio{padding:24px;text-align:center;color:var(--muted)}
.pie{margin-top:28px;font-size:12.5px;color:var(--muted);border-top:1px solid var(--line);padding-top:12px}
@media (max-width:640px){.page{padding:18px 16px 60px}.barra{position:static;margin:0 -16px 8px;padding:10px 16px}h1{font-size:21px}.conj{padding:14px}.ev,.exc,.det,.ctx-err,.ops2{margin-left:0}}
@media print{.barra,.mini,details.aporta{display:none}.conj{break-inside:avoid}body{background:#fff}}
"""

SCRIPT = r"""
(function(){
'use strict';
var D=JSON.parse(document.getElementById('kx-datos').textContent),CLAVE='kortex-ficha-'+D.ficha_id;
var est={revisor:{nombre:'',correo:'',ambito:''},c:{},x:{},ctx:{}};
D.tarjetas.forEach(function(t){est.c[t]={respuesta:'',comentario:'',aportacion:'',en:''};});
D.items.forEach(function(i){est.x[i.objeto]={respuesta:'',nota:'',tipo:''};});
var CL={};D.items.forEach(function(i){CL[i.objeto]=i.clase;});
function $(s,c){return (c||document).querySelector(s);}
function $$(s,c){return Array.prototype.slice.call((c||document).querySelectorAll(s));}
function guardar(){try{localStorage.setItem(CLAVE,JSON.stringify(est));}catch(e){}}
function mezclar(o){if(!o)return 0;var n=0;
  if(o.revisor)['nombre','correo','ambito'].forEach(function(k){est.revisor[k]=String(o.revisor[k]||'');});
  Object.keys(o.c||{}).forEach(function(k){var v=o.c[k];if(est.c[k]&&v&&D.respuestas_tarjeta.indexOf(v.respuesta)>=0){
    est.c[k]={respuesta:v.respuesta,comentario:String(v.comentario||''),aportacion:String(v.aportacion||''),en:String(v.en||'')};if(v.respuesta)n++;}});
  Object.keys(o.x||{}).forEach(function(k){var v=o.x[k];if(est.x[k]&&v&&(v.respuesta===''||D.excepciones[CL[k]].indexOf(v.respuesta)>=0))
    est.x[k]={respuesta:v.respuesta,nota:String(v.nota||''),tipo:String(v.tipo||'')};});
  Object.keys(o.ctx||{}).forEach(function(k){if(D.contexto.indexOf(k)>=0)est.ctx[k]=String(o.ctx[k]||'');});
  return n;}
try{var t0=localStorage.getItem(CLAVE);if(t0)mezclar(JSON.parse(t0));}catch(e){}
var CON_NOTA={INCORRECTA:1,PARCIAL:1,CORREGIR_NOMBRE:1,DUPLICADO:1},CON_TIPO={CORREGIR_TIPO:1,OTRO_TIPO:1};
function faltaX(id){var x=est.x[id];return (CON_NOTA[x.respuesta]&&!x.nota.trim())||(CON_TIPO[x.respuesta]&&!x.tipo);}
function sinComentario(c){var e=est.c[c.getAttribute('data-sec')];return (e.respuesta==='PARCIAL'||e.respuesta==='NO')&&!e.comentario.trim()&&!$$('.linea[data-x]',c).length;}
function pintar(){
  ['nombre','correo','ambito'].forEach(function(k){var t=$('#rv-'+k);if(t.value!==est.revisor[k])t.value=est.revisor[k];});
  var hechas=0,cuenta={},nx=0;D.respuestas_tarjeta.forEach(function(k){cuenta[k]=0;});
  $$('.conj').forEach(function(c){var id=c.getAttribute('data-sec'),e=est.c[id];c.setAttribute('data-r',e.respuesta);
    $$('input[name="c-'+id+'"]',c).forEach(function(r){r.checked=(r.value===e.respuesta);});
    var ta=$('[data-c=comentario]',c);if(ta.value!==e.comentario)ta.value=e.comentario;
    var ap=$('[data-c=aportacion]',c);if(ap.value!==e.aportacion)ap.value=e.aportacion;if(e.aportacion)$('details.aporta',c).open=true;
    $$('.linea[data-obj]',c).forEach(function(l){var id2=l.getAttribute('data-obj'),x=est.x[id2];
      if(x.respuesta){l.setAttribute('data-x',x.respuesta);nx++;}else l.removeAttribute('data-x');
      var tag=$('.exc-tag',l);tag.hidden=!x.respuesta;tag.textContent=x.respuesta?D.excepciones_txt[x.respuesta]:'';tag.classList.toggle('ok',x.respuesta==='CORRECTA');
      $$('input[type=radio]',l).forEach(function(r){r.checked=(r.value===x.respuesta);});
      var nt=$('[data-x=nota]',l);if(nt.value!==x.nota)nt.value=x.nota;var sl=$('select[data-x=tipo]',l);if(sl){sl.value=x.tipo;sl.hidden=!CON_TIPO[x.respuesta];}});
    $('.marca-r',c).textContent=D.respuestas_tarjeta_txt[e.respuesta];
    c.classList.toggle('sin-comentario',sinComentario(c));if(e.respuesta)hechas++;cuenta[e.respuesta]++;});
  $$('[data-ctx]').forEach(function(el){var v=est.ctx[el.getAttribute('data-ctx')]||'',t=$('textarea',el);if(t.value!==v)t.value=v;if(v)$('.ctx-err',el).hidden=false;});
  $('#estado').textContent=hechas+' de '+D.tarjetas.length+' respondidas · Sí '+cuenta.SI+' · Parcialmente '+cuenta.PARCIAL+' · No '+cuenta.NO
    +' · Sin valorar '+(cuenta.SIN_INFORMACION+cuenta.FUERA_DE_AMBITO)+(nx?' · '+nx+' excepciones':'');
  filtrar();}
function filtrar(){var f=$('#f-ver').value,q=$('#f-q').value.toLowerCase().trim(),vis=0;
  $$('.conj').forEach(function(c){var r=est.c[c.getAttribute('data-sec')].respuesta;var ok=(!f||(f==='pend'&&!r)||(f==='hechos'&&!!r))&&(!q||c.textContent.toLowerCase().indexOf(q)>=0);c.hidden=!ok;if(ok)vis++;});
  $('#f-vacio').hidden=vis>0;}
document.addEventListener('change',function(ev){var t=ev.target;
  if(t.id==='f-ver'){filtrar();return;}
  if(t.name&&t.name.indexOf('c-')===0&&t.type==='radio'){var e=est.c[t.name.slice(2)];e.respuesta=t.value;e.en=new Date().toISOString();}
  else if(t.name&&t.name.indexOf('x-')===0&&t.type==='radio'){est.x[t.name.slice(2)].respuesta=t.value;}
  else if(t.getAttribute('data-x')==='tipo'){est.x[t.closest('.linea').getAttribute('data-obj')].tipo=t.value;}
  else return;
  guardar();pintar();});
document.addEventListener('input',function(ev){var t=ev.target;
  if(t.id==='f-q'){filtrar();return;}
  if(t.id&&t.id.indexOf('rv-')===0){est.revisor[t.id.slice(3)]=t.value;guardar();return;}
  var cx=t.closest&&t.closest('[data-ctx]');if(cx&&t.tagName==='TEXTAREA'){est.ctx[cx.getAttribute('data-ctx')]=t.value;guardar();return;}
  var l=t.closest&&t.closest('.linea[data-obj]');if(l&&t.getAttribute('data-x')==='nota'){est.x[l.getAttribute('data-obj')].nota=t.value;guardar();return;}
  var c=t.closest&&t.closest('.conj');if(c&&t.getAttribute('data-c')){est.c[c.getAttribute('data-sec')][t.getAttribute('data-c')]=t.value;guardar();c.classList.toggle('sin-comentario',sinComentario(c));}});
document.addEventListener('click',function(ev){var b=ev.target.closest&&ev.target.closest('[data-abre]');if(!b)return;
  var p=$('.'+b.getAttribute('data-abre'),b.closest('.linea,.conj'));if(p){p.hidden=!p.hidden;b.setAttribute('aria-expanded',String(!p.hidden));}});
var DE={SI:'CORRECTA',PARCIAL:'PARCIAL',NO:'INCORRECTA',SIN_INFORMACION:'SIN_INFORMACION',FUERA_DE_AMBITO:'FUERA_DE_AMBITO','':'SIN_REVISAR'};
function salida(){var ents=[],rels=[];
  D.items.forEach(function(i){var c=est.c[i.tarjeta],x=est.x[i.objeto];
    var r={firma:i.firma,respuesta:'SIN_REVISAR',via:'grupo',en:c.en,nombre_nuevo:'',tipo_nuevo:'',duplicado_de:'',motivo:'',correccion:'',observaciones:'',aportacion:''};
    if(x.respuesta){r.respuesta=x.respuesta;r.via='individual';
      if(x.respuesta==='CORREGIR_NOMBRE')r.nombre_nuevo=x.nota;else if(x.respuesta==='DUPLICADO')r.duplicado_de=x.nota;
      else if(CON_TIPO[x.respuesta]){r.tipo_nuevo=x.tipo;r.motivo=x.nota;}else if(x.respuesta==='INCORRECTA'||x.respuesta==='PARCIAL'||x.respuesta==='DIRECCION')r.motivo=x.nota;else r.observaciones=x.nota;}
    else{r.respuesta=DE[c.respuesta];if(c.respuesta==='PARCIAL'||c.respuesta==='NO')r.motivo=c.comentario;else r.observaciones=c.comentario;if(!c.respuesta)r.via='individual';}
    if(i.clase==='ENT'){r.entidad_id=i.objeto;ents.push(r);}else{r.relacion_id=i.objeto;rels.push(r);}});
  return {formato:D.formato_respuestas,ficha_id:D.ficha_id,modo:D.modo,huella:D.huella,sello:D.sello,campana:D.campana,exportado_en:new Date().toISOString(),
    revisor:{nombre:est.revisor.nombre,correo:est.revisor.correo,ambito:est.revisor.ambito},entidades:ents,relaciones:rels,
    conjuntos:D.tarjetas.map(function(t){var c=est.c[t];return {seccion:t,respuesta:c.respuesta,comentario:c.comentario,aportacion:c.aportacion};}),
    contexto:Object.keys(est.ctx).filter(function(k){return est.ctx[k].trim();}).map(function(k){return {objeto:k,texto:est.ctx[k]};}),estado_ficha:est};}
$('#b-export').addEventListener('click',function(){var o=salida(),m=$('#msg'),av=[];
  if(!o.revisor.nombre.trim()&&!o.revisor.correo.trim())av.push('no has indicado tu nombre ni tu correo');
  var sc=$$('.conj').filter(sinComentario).length;if(sc)av.push(sc+' con «Parcialmente» o «No» no dicen qué cambiar');
  var fx=Object.keys(est.x).filter(faltaX).length;if(fx)av.push(fx+' excepciones necesitan un dato (qué cambiar o el tipo correcto)');
  var b=new Blob([JSON.stringify(o,null,1)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='respuestas_'+D.ficha_id+'.json';
  document.body.appendChild(a);a.click();setTimeout(function(){URL.revokeObjectURL(a.href);a.remove();},1000);
  m.className='msg'+(av.length?' mal':'');m.textContent='Descargado respuestas_'+D.ficha_id+'.json'+(av.length?'. Atención: '+av.join('; ')+'.':'. Envíalo al equipo Kortex.');});
$('#b-cargar').addEventListener('click',function(){$('#f-cargar').click();});
$('#f-cargar').addEventListener('change',function(){var f=this.files&&this.files[0],m=$('#msg');if(!f)return;var rd=new FileReader();
  rd.onload=function(){try{var o=JSON.parse(rd.result);if(o.ficha_id!==D.ficha_id){m.className='msg mal';m.textContent='Ese fichero es de otra ficha ('+o.ficha_id+').';return;}
    var n=mezclar(o.estado_ficha);guardar();pintar();m.className='msg';m.textContent='Cargadas '+n+' respuestas de '+f.name+'.';}catch(e){m.className='msg mal';m.textContent='No se ha podido leer el fichero.';}};
  rd.readAsText(f);this.value='';});
pintar();window.kortexFicha={estado:est,salida:salida};
})();
"""

ICO = ('<svg class="ico" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8.2" fill="none" stroke="currentColor" stroke-width="1.5"/>'
       '<path d="M6.3 10.2l2.4 2.4 5-5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>')
ICO_B = ('<svg class="ico" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8.2" fill="none" stroke="currentColor" stroke-width="1.5" '
         'stroke-dasharray="2.6 2.2"/><circle cx="10" cy="10" r="1.6" fill="currentColor"/></svg>')


def _sin(i):
    return "" if i.get("confianza") == "PENDIENTE_VALIDAR" else f'<span class="etq sin">{esc(i["confianza_txt"].lower())}</span>'


def _exc(obj, clase, tipos):
    oid = esc(obj)
    ops = "".join(f'<label><input type="radio" name="x-{oid}" value="{k}">{esc(t)}</label>' for k, t in EXC[clase].items())
    ops += f'<label><input type="radio" name="x-{oid}" value="">Quitar excepción</label>'
    sel = "".join(f'<option value="{esc(k)}">{esc(v)}</option>' for k, v in tipos)
    return (f'<div class="exc" hidden><div class="ops">{ops}</div><div class="campos"><select data-x="tipo" hidden aria-label="Tipo correcto">'
            f'<option value="">— tipo correcto —</option>{sel}</select><input type="text" data-x="nota" maxlength="{MAX_TEXTO}" '
            'placeholder="Qué cambiarías (el nombre correcto, con qué entidad es la misma, qué no es cierto…)" aria-label="Qué cambiarías"></div></div>')


def _acciones(obj, revisable):
    return ('<span class="acc"><button type="button" class="mini" data-abre="ev" aria-expanded="false">Evidencia</button>'
            + (' · <button type="button" class="mini" data-abre="exc" aria-expanded="false">Señalar excepción</button>' if revisable
               else ' · <button type="button" class="mini" data-abre="ctx-err" aria-expanded="false">Señalar un error</button>') + "</span>")


def _ctx_err(obj):
    return (f'<div class="ctx-err" hidden><textarea maxlength="{MAX_TEXTO}" placeholder="Qué está mal (no cambia nada por sí solo: el equipo Kortex lo revisará)" '
            f'aria-label="Error en {esc(obj)}"></textarea></div>')


def _linea_ent(e, revisable, modo, m):
    oid = esc(e["objeto"])
    txt = f'«{esc(e["nombre"])}» se identifica como {esc(e["tipo"].lower())}.'
    det = ("".join(f'<q>{esc(x["cita"])}</q><small>{esc(" · ".join(y for y in (x["doc"], x["ubicacion"]) if y))}</small>' for x in e["menciones"][:3])
           or "<small>Sin cita literal</small>")
    extra = " · ".join(x for x in [f"También llamado: {', '.join(e['alias'])}" if e["alias"] else "",
                                   f"Posible duplicado de: {', '.join(d['nombre'] for d in e['duplicados'])}" if e["duplicados"] else "",
                                   f"Documentos: {', '.join(e['documentos'][:4])}" + (f" (+{len(e['documentos']) - 4})" if len(e["documentos"]) > 4 else ""),
                                   e["confianza_txt"] + (f" ({'; '.join(e['por_que_no'])})" if e["por_que_no"] else ""), e["revision"]] if x)
    ico = ICO if e.get("confianza") == "PENDIENTE_VALIDAR" else ICO_B
    attrs = f'data-obj="{oid}"' if revisable else f'data-ctx="{oid}"'
    etq = "" if revisable else '<span class="etq ctxe">contexto</span>'
    return (f'<li class="linea{"" if revisable else " ctx"}" {attrs}><div class="fila">{ico}<span class="txt">{txt}{_sin(e)}{etq}<span class="etq exc-tag" hidden></span></span>'
            f'{_acciones(e["objeto"], revisable)}</div><div class="ev" hidden>{det}<small>{esc(extra)}</small><small class="rid">{oid}</small></div>'
            + (_exc(e["objeto"], "ENT", m["tipos"]) if revisable else _ctx_err(e["objeto"])) + "</li>")


def _linea_rel(i, eid, revisable, m, nota=""):
    oid = esc(i["objeto"])
    det = "".join((f'<q>{esc(e["cita"])}</q>' if e["cita"] else "") + f'<small>{esc(" · ".join(x for x in (e["doc"], e["ubicacion"]) if x) or "Documento sin identificar")}</small>'
                  for e in i["evidencias"][:3]) or "<small>Sin cita literal</small>"
    extra = " · ".join(x for x in [i["confianza_txt"] + (f" ({'; '.join(i['por_que_no'])})" if i["por_que_no"] else ""), i["revision"],
                                   f"Procedencia: {i['procedencia']}"] if x)
    ico = ICO if i.get("confianza") == "PENDIENTE_VALIDAR" else ICO_B
    ref = nota.startswith("se revisa")
    attrs = f'data-obj="{oid}"' if revisable else (f'data-ref="{oid}"' if ref else f'data-ctx="{oid}"')
    return (f'<li class="linea{"" if revisable else " ctx"}" {attrs}><div class="fila">{ico}<span class="txt">{esc(i["linea"])}{_sin(i)}'
            + (f' <span class="etq ctxe">{esc(nota)}</span>' if nota else "") + '<span class="etq exc-tag" hidden></span></span>'
            + (_acciones(i["objeto"], revisable) if revisable or not nota.startswith("se revisa") else "")
            + f'</div><div class="ev" hidden>{det}<small>{esc(extra)}</small><small class="rid">{oid}</small></div>'
            + (_exc(i["objeto"], "REL", m["tipos_rel"]) if revisable else ("" if nota.startswith("se revisa") else _ctx_err(i["objeto"]))) + "</li>")


def _tarjeta(t, m):
    eid, e, A = t["id"], t["ent"], m["modo"] != "OTROS_ESTADOS"
    sid = esc(eid)
    lineas = []
    if e:
        lineas.append(_linea_ent(e, t["revision"], m["modo"], m))
    lineas += [_linea_rel(i, eid, True, m) for i in t["rels"]]
    tambien = [_linea_rel(i, eid, False, m, nota=f"se revisa en {i['en_tarjeta_nombre']}") for i in t["ref"]]
    tambien += [_linea_rel(i, eid, False, m, nota="contexto") for i in t["ctx"]]
    lead = "Kortex ha identificado lo siguiente:"
    principales = [("SI", "Sí, es correcta"), ("PARCIAL", "Parcialmente, hay que corregir algo"), ("NO", "No es correcta")]
    desc = (e or {}).get("descripciones") or []
    return (f'<section class="conj" id="e-{sid}" data-sec="{sid}" data-r="" aria-labelledby="h-{sid}"><div class="cab"><h2 id="h-{sid}">Validación funcional · {esc(t["nombre"])}'
            f' <span class="tipo">· {esc(t["tipo"])}</span></h2><span class="marca-r">Sin responder</span></div>'
            + (f'<p class="desc">{esc(desc[0]["texto"])}</p>' if desc else "")
            + f'<p class="lead">{lead}</p><ul class="lineas">{"".join(lineas)}</ul>'
            + (f'<details class="tambien"><summary>Ver también {_pl(len(tambien), "relación", "relaciones")} (contexto: no se responde aquí)</summary><ul class="lineas">{"".join(tambien)}</ul></details>' if tambien else "")
            + '<fieldset class="pregunta"><legend>¿Es correcta esta representación?</legend>'
            + "".join(f'<label class="op"><input type="radio" name="c-{sid}" value="{k}">{esc(x)}</label>' for k, x in principales)
            + f'<div class="ops2"><label><input type="radio" name="c-{sid}" value="SIN_INFORMACION">No tengo información suficiente</label>'
            f'<label><input type="radio" name="c-{sid}" value="FUERA_DE_AMBITO">No es de mi ámbito</label></div></fieldset>'
            f'<div class="comentario"><textarea data-c="comentario" maxlength="{MAX_TEXTO}" placeholder="Indica qué relación cambiarías o qué falta…" '
            'aria-label="Comentario"></textarea><p class="falta">Cuéntanos qué hay que corregir, o señala la excepción en la línea concreta.</p></div>'
            f'<details class="aporta"><summary>Añadir conocimiento que no está en los documentos</summary><textarea data-c="aportacion" maxlength="{MAX_TEXTO}" '
            'placeholder="Se registra como aportación tuya, no como evidencia documental" aria-label="Aportación"></textarea></details></section>')


def html(m) -> str:
    modo = m["modo"]
    datos = {"formato_respuestas": FORMATO_RESPUESTAS, "ficha_id": m["ficha_id"], "modo": modo, "huella": m["huella"], "sello": m["sello"], "campana": m["campana"],
             "respuestas_tarjeta": list(RESPUESTAS_CONJUNTO), "respuestas_tarjeta_txt": {**RESPUESTAS_CONJUNTO, "SI": "Sí, es correcta", "PARCIAL": "Parcialmente",
                                                                                        "NO": "No es correcta"},
             "excepciones": {k: list(v) for k, v in EXC.items()}, "excepciones_txt": EXC_TXT, "contexto": m["contexto"],
             "tarjetas": [t["id"] for t in m["tarjetas"]],
             "items": [{"objeto": i["objeto"], "clase": i["clase"], "firma": i["firma"], "tarjeta": i["tarjeta"]} for i in m["items"]]}
    datos_js = json.dumps(datos, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")
    ne, nr = sum(1 for i in m["items"] if i["clase"] == "ENT"), sum(1 for i in m["items"] if i["clase"] == "REL")
    if modo == "PENDIENTE_VALIDAR":
        intro = ('<p class="intro">Kortex ha interpretado estas entidades y relaciones y cumplen todos los controles automáticos, pero están '
                 '<b>pendientes de validar</b>: nadie las ha confirmado todavía. Responde una pregunta por entidad; si una línea concreta no es '
                 'correcta, señálala como excepción.</p>')
    elif modo == "OTROS_ESTADOS":
        intro = ('<p class="intro b">Esto está pendiente y <b>no cumple todos los controles automáticos</b>: cada línea dice qué le falta (sin '
                 'corroborar, sin cita literal, fuera del catálogo…). Responde una pregunta por entidad; si una línea concreta no es correcta, '
                 'señálala como excepción.</p>')
    else:
        intro = '<p class="intro">Todo lo que Kortex sabe de esta entidad. Responde la pregunta; si una línea concreta no es correcta, señálala como excepción.</p>'
    filtro = m.get("filtro") or {}
    alcance = " · ".join(x for x in [f"ámbito {filtro['ambito']}" if filtro.get("ambito") else "", f"entidad {filtro['entidad']}" if filtro.get("entidad") else ""] if x)
    meta = (f'<b>Ficha {CORTO[modo]}</b> · {esc(MODOS[modo].lower())} · {_pl(len(m["tarjetas"]), "tarjeta", "tarjetas")} · a revisar: '
            f'{_pl(ne, "entidad", "entidades")} y {_pl(nr, "relación", "relaciones")}' + (f" · {esc(alcance)}" if alcance else "")
            + f' · generada {esc(_fecha(m["generada"]))} · KB {esc(m["campana"])} versión {esc(m["huella"])} · <span class="rid">{esc(m["ficha_id"])}</span>')
    return ('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">'
            f'<title>Validación funcional · {esc(m["titulo"])}</title><style>{CSS}</style></head><body><main class="page">'
            f'<span class="marca">Kortex · Validación funcional</span><h1>{esc(m["titulo"])}</h1><p class="meta">{meta}</p>{intro}'
            '<div class="revisor"><input type="text" id="rv-nombre" autocomplete="name" placeholder="Tu nombre" aria-label="Tu nombre">'
            '<input type="email" id="rv-correo" autocomplete="email" placeholder="Tu correo" aria-label="Tu correo">'
            '<input type="text" id="rv-ambito" placeholder="Tu equipo o ámbito" aria-label="Tu equipo o ámbito"></div>'
            '<p class="nota">Es la identidad que declaras; el equipo Kortex la comprobará antes de registrar tu validación.</p>'
            '<div class="barra" role="region" aria-label="Herramientas"><span class="estado" id="estado" role="status"></span>'
            '<input type="search" id="f-q" placeholder="Buscar…" aria-label="Buscar">'
            '<select id="f-ver" aria-label="Ver"><option value="">Todas</option><option value="pend">Pendientes</option><option value="hechos">Respondidas</option></select>'
            '<button type="button" class="btn" id="b-export">Descargar respuestas</button><button type="button" class="btn sec" id="b-cargar">Cargar respuestas</button>'
            '<input type="file" id="f-cargar" accept=".json,application/json" hidden><span id="msg" class="msg" role="status"></span></div>'
            + "".join(_tarjeta(t, m) for t in m["tarjetas"]) + '<p class="vacio" id="f-vacio" hidden>No hay entidades con ese filtro.</p>'
            '<div class="pie"><p>Tus respuestas se guardan en este navegador mientras trabajas. Al terminar, pulsa <b>Descargar respuestas</b> y envía el fichero al '
            'equipo Kortex sin modificarlo. «Parcialmente» no aprueba nada: queda pendiente de corregir. Cada línea se valida una sola vez; lo que aparece en '
            '«Ver también» se revisa en otra entidad o es contexto.</p></div>'
            f'</main><script type="application/json" id="kx-datos">{datos_js}</script><script>{SCRIPT}</script></body></html>')


def _pl(n, s, p):
    return f"{num(n)} {s if n == 1 else p}"


def _fecha(iso) -> str:
    try:
        d = dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
        return f"{d:%d/%m/%Y %H:%M} UTC"
    except ValueError:
        return iso


def html_indice(cob, fichas) -> str:
    filas = "".join(f'<tr><td><a href="{esc(Path(m["fichero"]).name)}">{esc(m["titulo"])}</a></td><td>{len(m["tarjetas"])}</td>'
                    f'<td>{sum(1 for i in m["items"] if i["clase"] == "ENT")}</td><td>{sum(1 for i in m["items"] if i["clase"] == "REL")}</td>'
                    f'<td class="rid">{esc(m["ficha_id"])}</td></tr>' for m in fichas)
    modo, E, R = cob["modo"], cob["entidades"], cob["relaciones"]
    return ('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Fichas {CORTO[modo]} · índice</title><style>{CSS}table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line)}}'
            'th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line2)}th{font-size:13px;color:var(--muted)}td:nth-child(n+2){font-variant-numeric:tabular-nums}</style></head>'
            f'<body><main class="page"><span class="marca">Kortex · Validación funcional</span><h1>{esc(MODOS[modo])}</h1>'
            f'<p class="meta">{num(E["a_revisar"])} entidades y {num(R["a_revisar"])} relaciones a revisar en {len(fichas)} fichas · KB {esc(cob["campana"])} versión {esc(cob["huella"])} · generado {_fecha(cob["generada"])}</p>'
            f'<p class="intro{"" if CORTO[modo] == "A" else " b"}">Cobertura: ninguna entidad ni relación se pierde ni se repite. Como contexto se enseñan además '
            f'{num(E["solo_contexto"])} entidades y {num(R["solo_contexto"])} relaciones; {num(R["referencias_a_otra_tarjeta"])} relaciones aparecen también como referencia en la otra entidad.</p>'
            f'<table><thead><tr><th>Ficha</th><th>Tarjetas</th><th>Entidades</th><th>Relaciones</th><th>Identificador</th></tr></thead><tbody>{filas}</tbody></table></main></body></html>')
