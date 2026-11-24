"""Herramientas de conocimiento de Kortex que el servidor MCP oficial (mcps/kortex_mcp/server.py) añade a list_collections y
retrieve. Dependen de la sesión de `kortex-mcp login` (perfil leído del token, sin red):
- sin sesión: solo `estado_sesion`, que explica cómo hacer login;
- consulta (7): lo que ve el usuario en la ingesta (su documentación + conocimiento transversal de la KB);
- admin (grupo kb-admin): lo anterior y la administración de la KB (lectura, decisiones auditables, consolidación, fuentes).
La autorización real de cada llamada la hace la API; el perfil solo decide qué herramientas se enseñan.
Nada se escribe en stdout salvo el protocolo; los errores llegan a Claude como texto en español."""
import functools
import sys
import traceback

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import config
from . import ingesta as I
from .kb import KB
from .sesion import ErrorKortex, Sesion, perfil_actual

LECTURA = ToolAnnotations(read_only_hint=True, open_world_hint=True)
ESCRITURA = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True)
DESTRUCTIVA = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=True)

INSTRUCCIONES = {
    "consulta": ("Kortex (consulta): responde con la documentación del equipo del usuario y, a modo de información, con el conocimiento "
                 "transversal de la KB. Usa primero «consultar»; cita los fragmentos como [n] con su documento; si hace falta más contexto, "
                 "«leer_documento» por páginas. Lo transversal de la KB se parafrasea: no es un documento del equipo."),
    "admin": ("Kortex (admin): administra la KB servida de la campaña KORTEX. Lee con estado_kb, buscar_entidades, entidad, relaciones, "
              "por_que, documento_en_kb, ambito. TODA escritura es una decisión auditable con autor; lo masivo, lo destructivo y lo que cuesta "
              "dinero va en dos pasos: primero se previsualiza y se devuelve un código; NO confirmes por tu cuenta: enseña la "
              "previsualización y espera a que la persona diga que sí antes de llamar con confirmar=<código>. Revisión por fichas: "
              "generar_fichas_revision (PENDIENTE_VALIDAR u OTROS_ESTADOS) → la persona responde el HTML → importar_respuestas_ficha → "
              "previsualizar_correcciones_ficha (lo que el revisor matiza queda POR INTERPRETAR: tradúcelo tú a operaciones y pásalas en "
              "operaciones_adicionales; si dice «no forma parte de A sino de B», la operación es corregir la relación, no solo rechazarla) → "
              "aplicar_correcciones_ficha. Acceso completo a la KB con operar_kb (crear/corregir/invertir relaciones, crear/fusionar "
              "entidades, HPUM, ámbitos, descripción, ampliar el catálogo): lo que afirma una persona entra VALIDADO. Ids con "
              "buscar_entidades, relaciones, buscar_hpum y catalogo_kb. Estados de la KB: VALIDADO solo lo pone una persona; "
              "PENDIENTE_VALIDAR = la IA lo interpretó y cumple todos los controles; los demás (SIN_CORROBORAR, SIN_CITA_LITERAL, SIN_EVIDENCIA, "
              "FUERA_DE_CATALOGO, SIN_VINCULAR, EN_CONFLICTO) dicen qué le falta."),
}


class Contexto:
    """Sesiones perezosas: no se toca la red hasta la primera herramienta."""

    def __init__(self, perfil, fabrica=None):
        self.perfil = perfil
        self.fabrica = fabrica or Sesion                          # Sesion(cuenta): «ingesta» (/knowledge/v1) o «kb» (/kb/v1)
        self._s, self._kb = {}, None

    def sesion(self, cuenta):
        if cuenta not in self._s:
            self._s[cuenta] = self.fabrica(cuenta)
        return self._s[cuenta]

    @property
    def ing(self):
        return self.sesion("ingesta")

    @property
    def kb(self):
        if self._kb is None:
            self._kb = KB(self.sesion("kb"))
        return self._kb


def _seguro(f):
    @functools.wraps(f)
    def envuelta(*a, **k):
        try:
            return f(*a, **k)
        except (ErrorKortex, config.ConfigIncompleta) as e:   # ToolError: el SDK pasa el mensaje a Claude (cualquier otra excepción la oculta)
            raise ToolError(str(e)) from None
        except Exception as e:  # noqa: BLE001 — nada de trazas ni secretos hacia el cliente; la traza va a stderr
            traceback.print_exc(file=sys.stderr)
            raise ToolError(f"Error inesperado en {f.__name__} ({type(e).__name__}). Revisa el registro del servidor MCP.") from None
    return envuelta


SIN_SESION = ("No hay sesión de Kortex en este equipo (o ha caducado: dura 30 días desde el login). Para usar las herramientas de "
              "conocimiento, la persona debe ejecutar en SU terminal «kortex-mcp login» (usuario, contraseña y el código de 6 dígitos de su "
              "aplicación de autenticación) y después reiniciar este servidor MCP. No pidas ni escribas contraseñas ni códigos en el chat. "
              "list_collections y retrieve no dependen del login: usan la clave personal KORTEX_API_KEY.")


def crear(perfil: str, fabrica=None) -> MCPServer:
    """Un servidor solo con las herramientas de conocimiento del perfil (pruebas); el MCP oficial usa registrar()."""
    if perfil not in ("consulta", "admin"):
        raise ValueError("Perfil desconocido: usa consulta o admin")
    return registrar(MCPServer(name="kortex", instructions=INSTRUCCIONES[perfil]), perfil, fabrica)


def registrar_sin_sesion(srv: MCPServer) -> MCPServer:
    """Sin sesión: una herramienta que dice cómo hacer login (y si falta configuración, cuál)."""
    @srv.tool(name="estado_sesion", annotations=LECTURA, structured_output=False,
              description="Estado de la sesión de conocimiento de Kortex y cómo hacer login para tener sus herramientas (consulta de la "
                          "documentación y, para el equipo de Kortex, administración de la KB). Llámala si el usuario pregunta por su "
                          "documentación de Kortex y no ves esas herramientas.")
    def estado_sesion() -> str:
        try:
            cfg = config.cargar()
        except config.ConfigIncompleta as e:
            return str(e)
        if cfg.faltan():
            return (f"Las herramientas de conocimiento no están configuradas (entorno «{cfg.entorno}»): falta {', '.join(cfg.faltan())}. "
                    f"Pide al equipo de Kortex el config.json y déjalo en {config.fichero_config()}, o define esas variables. "
                    "Después: «kortex-mcp login» en la terminal y reiniciar el servidor MCP.")
        perfil = perfil_actual()
        if perfil:
            return (f"Ya hay sesión de Kortex (perfil {perfil}, entorno «{cfg.entorno}»), pero este servidor arrancó antes del login: "
                    "reinícialo (o abre una sesión nueva del cliente) para ver las herramientas.")
        return SIN_SESION + f" Entorno: «{cfg.entorno}»."
    return srv


def registrar(srv: MCPServer, perfil: str, fabrica=None) -> MCPServer:
    """Añade a `srv` las herramientas y prompts de conocimiento del perfil («consulta» o «admin»)."""
    if perfil not in ("consulta", "admin"):
        raise ValueError("Perfil desconocido: usa consulta o admin")
    c = Contexto(perfil, fabrica)

    def herramienta(anot=LECTURA, nombre=None):
        def deco(f):
            return srv.tool(name=nombre or f.__name__, description=(f.__doc__ or "").strip(), annotations=anot, structured_output=False)(_seguro(f))
        return deco

    # ================================================================== consulta (los dos perfiles)
    @herramienta()
    def quien_soy() -> str:
        """Qué MCP es (perfil), con qué usuario ha entrado y en qué entorno, y sus equipos y roles."""
        s = c.ing
        return I.quien_soy(s, c.perfil, {"kortex": f"{s.usuario() or '—'} · entorno {s.cfg.entorno}"})

    @herramienta()
    def equipos_y_carpetas(equipo: str | None = None) -> str:
        """Equipos que ves y su árbol de carpetas (con el proceso HPUM de cada carpeta si lo tiene). equipo: team_id para uno solo."""
        return I.equipos_y_carpetas(c.ing, equipo)

    @herramienta()
    def documentos(equipo: str | None = None, carpeta: str | None = None, texto: str | None = None, estado: str | None = None,
                   limite: int = 50, cursor: str | None = None) -> str:
        """Documentos de un equipo (si solo ves uno, no hace falta indicarlo). carpeta: collection_id (incluye subcarpetas); texto: busca
        en el nombre; estado: filtro de la web; cursor: para la página siguiente."""
        return I.documentos(c.ing, equipo, carpeta, texto, estado, limite, cursor)

    @herramienta()
    def consultar(pregunta: str, colecciones: list[str] | None = None, k: int | None = None, kb: bool = True) -> str:
        """Pregunta a Kortex SIN gastar modelo: devuelve los fragmentos relevantes de la documentación que el usuario puede leer
        (RAG, numerados [n] con doc_id) y lo que la KB sabe de lo preguntado (conocimiento transversal, a modo de información).
        colecciones: limitar a carpetas (collection_id); k: nº de fragmentos; kb=false: solo documentación.
        Es UNA búsqueda: si los fragmentos no contienen la respuesta (portadas, índices, otro tema), vuelve a llamar con otras palabras
        del contenido que buscas (sinónimos, términos del documento) en vez de concluir que no está; o lee la parte con leer_documento."""
        return I.consultar(c.ing, pregunta, colecciones, k, kb)

    @herramienta()
    def leer_documento(doc_id: str, desde: int = 0, max: int | None = None) -> str:  # noqa: A002
        """Texto de un documento por segmentos (paginado): desde = primer segmento; max = cuántos (1–200). Indica cómo seguir."""
        return I.leer_documento(c.ing, doc_id, desde, max)

    @herramienta(ESCRITURA)
    def descargar_original(doc_id: str, version: int | None = None, carpeta: str | None = None) -> str:
        """Descarga el fichero original (versión aprobada actual o la indicada) a Descargas\\kortex o a la carpeta dada."""
        return I.descargar_original(c.ing, doc_id, version, carpeta)

    @srv.prompt(name="contrastar_con_mi_contexto", description="Contrasta lo que dice tu documentación con el conocimiento transversal de la KB.")
    def contrastar(tema: str) -> str:
        return (f"Tema: «{tema}».\n1. Llama a consultar(pregunta=…) con el tema. 2. Resume lo que dice la documentación del equipo citando [n] y "
                "documento; si un fragmento es corto, usa leer_documento para el contexto. 3. Aparte, resume lo que aporta la KB transversal "
                "(parafraseado, sin atribuirlo a documentos del equipo) y señala coincidencias, huecos y contradicciones. Termina con qué "
                "falta documentar.")

    if perfil == "consulta":
        return srv

    # ================================================================== admin: lectura de la KB
    @herramienta()
    def estado_kb() -> str:
        """Estado de la KB: huella (versión), contenido, revisión, fuentes (base Excel e ingesta) y observaciones."""
        return c.kb.estado_kb()

    @herramienta()
    def buscar_entidades(texto: str = "", tipo: str | None = None, ambito: str | None = None, estado: str | None = None, limite: int = 25) -> str:
        """Busca entidades en la KB servida (nombre, alias y nombres observados; sin acentos). Filtros: tipo (tipo_id o familia),
        ámbito, estado de revisión (pendiente, aprobada, corregida, rechazada)."""
        return c.kb.buscar_entidades(texto, tipo, ambito, estado, limite)

    @herramienta()
    def entidad(id: str) -> str:  # noqa: A002
        """Todo de una entidad: tipo, ámbitos, descripciones, HPUM, documentos, menciones, revisión y sus relaciones."""
        return c.kb.entidad(id)

    @herramienta()
    def relaciones(entidad: str | None = None, tipo: str | None = None, estado: str | None = None, documento: str | None = None, limite: int = 40) -> str:
        """Relaciones entre entidades con filtros: entidad (id), tipo (UTILIZA, SOPORTA…), estado de revisión, documento (id o nombre)."""
        return c.kb.relaciones(entidad, tipo, estado, documento, limite)

    @herramienta()
    def por_que(id: str) -> str:  # noqa: A002
        """Por qué está en la KB una entidad, relación (REL-…) o correspondencia HPUM (HPUM|entidad|nodo): citas, reglas, motivos y decisiones."""
        return c.kb.por_que(id)

    @herramienta()
    def documento_en_kb(documento: str) -> str:
        """Lo que la KB extrajo de un documento (doc_id o parte del nombre): clasificación, entidades, relaciones y advertencias."""
        return c.kb.documento_en_kb(documento)

    @herramienta()
    def ambito(ambito: str) -> str:
        """Un ámbito de negocio: sus entidades por tipo y sus documentos. Sin coincidencia, lista los ámbitos."""
        return c.kb.ambito(ambito)

    @herramienta()
    def contexto(entidad: str | None = None, ambito: str | None = None, formato: str = "json", carpeta: str | None = None) -> str:
        """Contexto de una entidad o ámbito tal como lo da la web (el mismo que usa el asistente). formato=csv lo guarda para Excel."""
        return c.kb.contexto(entidad, ambito, formato, carpeta)

    @herramienta()
    def metricas() -> str:
        """Métricas y salud: avance de la revisión, salud de los agentes de consolidación, calibración y evolución."""
        return c.kb.metricas()

    @herramienta()
    def lo_nuevo_desde(fecha: str | None = None) -> str:
        """Qué ha cambiado en la KB (documentos, entidades, relaciones) y qué se ha decidido desde una fecha ISO (2026-11-19) o desde la
        última marcar_revision. Se basa en fotos que este puesto guarda cada vez que lee una versión nueva."""
        return c.kb.lo_nuevo_desde(fecha)

    @herramienta(ESCRITURA)
    def marcar_revision() -> str:
        """Marca la versión actual de la KB como revisada (solo en este puesto) para que lo_nuevo_desde compare con ella."""
        return c.kb.marcar_revision()

    @herramienta(ESCRITURA)
    def ficha_html(id: str, saltos: int = 1, carpeta: str | None = None) -> str:  # noqa: A002
        """Descarga la ficha de relaciones de un elemento (entidad, proceso HPUM, documento o ámbito): el mismo HTML autocontenido que
        la web. saltos=2 añade el segundo nivel. Se guarda en Descargas\\kortex o en la carpeta dada."""
        return c.kb.ficha_html(id, saltos, carpeta)

    # ------------------------------------------------------------------ admin: fichas de revisión (generar → responder → importar → previsualizar → aplicar)
    @herramienta(ESCRITURA)
    def generar_fichas_revision(modo: str | None = None, ambito: str | None = None, entidad: str | None = None, carpeta: str | None = None,
                                sistema: str | None = None) -> str:
        """Genera las fichas HTML de conocimiento: una tarjeta por ENTIDAD con sus relaciones (entrantes y salientes) debajo, agrupadas
        por ámbito y tema y repartidas en fichas manejables. modo: PENDIENTE_VALIDAR (ficha A: lo que la IA interpretó y cumple todos
        los controles; falta que una persona lo valide) u OTROS_ESTADOS (ficha B: el resto de estados pendientes: sin corroborar, sin
        cita literal, sin evidencia, fuera del catálogo, sin vincular, en conflicto). Lo VALIDADO o ya decidido por una persona nunca
        entra: se enseña como CONTEXTO, igual que lo de la otra ficha. Cada relación se revisa en una sola tarjeta del lote.
        ambito: p. ej. Redes; entidad (o sistema): nombre o alias (SIGMA…); con entidad y sin modo, su ficha completa. Lee la KB actual y
        escribe solo ficheros locales (Descargas\\kortex\\fichas_revision o la carpeta dada); no usa el modelo. Devuelve ficheros y cobertura."""
        return c.kb.generar_fichas_revision(modo, ambito, entidad or sistema, carpeta)

    @herramienta(ESCRITURA)
    def importar_respuestas_ficha(ficheros: list[str]) -> str:
        """Importa los JSON de respuestas descargados de las fichas (rutas de ficheros o de una carpeta). Comprueba que la ficha la
        generó este MCP (sello), que identificadores y firmas no se han tocado, que la KB no ha cambiado esos elementos (entidades y
        relaciones, cada uno con su respuesta) y que no choca con otras revisiones. NO modifica la KB: solo guarda la importación local y devuelve el informe (confirmadas, rechazadas, con
        correcciones, sin revisar, fuera de ámbito, conflictos y cambios necesarios). El revisor del fichero es DECLARADO, no acreditado."""
        return c.kb.importar_respuestas_ficha(ficheros)

    @herramienta()
    def previsualizar_correcciones_ficha(importacion: str | list[str], acreditacion: str | None = None, ambito_acreditado: str | None = None,
                                         operaciones_adicionales: list[dict] | None = None) -> str:
        """Traduce las respuestas de una o varias importaciones (IMP-…) a operaciones sobre la KB y las previsualiza con la KB servida
        real antes/después. Sin acreditacion no se escribe nada (acreditacion = cómo se comprobó la identidad y competencia del revisor,
        p. ej. «correo de maria@… del 20/11, responsable de SIGMA»); ambito_acreditado limita a ese ámbito. Correcta → VALIDAR; no es
        cierta / no es válida con motivo → RECHAZAR (reversible); nombre o tipo de entidad → CORREGIR_NOMBRE / CORREGIR_TIPO;
        dirección al revés → INVERTIR_RELACION; otro tipo de relación → CORREGIR_RELACION; misma entidad que otra → FUSIONAR_ENTIDADES.
        Los matices («parcialmente», o un rechazo que dice qué es lo correcto) salen POR INTERPRETAR, con su comentario, las entidades
        que nombra y sugerencias: decide tú la operación buena (CREAR_RELACION, CORREGIR_RELACION, CREAR_ENTIDAD, …, como en operar_kb)
        y vuelve a llamar con operaciones_adicionales; si el comentario no da para una operación concreta, déjalo pendiente y dilo.
        Devuelve un código: NO lo confirmes sin que la persona lo diga."""
        return c.kb.previsualizar_correcciones_ficha(importacion, acreditacion, ambito_acreditado, operaciones_adicionales)

    @herramienta(ESCRITURA)
    def operar_kb(operaciones: list[dict] | None = None, motivo: str = "", confirmar: str | None = None) -> str:
        """Acceso COMPLETO a la KB, como tocarla en AWS pero auditable: cada operación queda como una decisión (autor = tu login, mismo
        lote) y se puede deshacer. Dos pasos: sin confirmar previsualiza con la KB servida real antes/después y devuelve un código; NO
        lo confirmes sin que la persona diga que sí. Lo que afirma una persona entra VALIDADO. Valida TODO el lote antes de escribir.
        motivo: por qué (p. ej. «Ficha de la revisora del 24/11, acreditada por correo»). Operaciones ({"op": …}); entidades y procesos por
        id (buscar_entidades / buscar_hpum); una entidad creada en el mismo lote se cita como "@<ref>":
          VALIDAR {ids}  ·  RECHAZAR {ids, motivo}  ·  CORREGIR_NOMBRE {entidad, nombre}  ·  CORREGIR_TIPO {entidad|ids, tipo_id}
          CORREGIR_DESCRIPCION {entidad, descripcion}  ·  CREAR_ENTIDAD {nombre, tipo_id, descripcion?, ambitos?, ref?}
          CREAR_RELACION {origen, tipo_id, destino, justificacion}  (si ya existe tal cual, la valida)
          CORREGIR_RELACION {relacion, tipo_id?, origen?, destino?, motivo}  (conserva sus evidencias; «no forma parte de A sino de B»)
          INVERTIR_RELACION {relacion, motivo}  ·  FUSIONAR_ENTIDADES {conservar, absorber:[ids], tipo_id?}
          MANTENER_SEPARADAS {ids:[DUP|a|b]}  ·  ENLAZAR_HPUM {entidad, proceso}  ·  QUITAR_HPUM {entidad, proceso}
          MAPEAR_A_HPUM {entidad, proceso}  (solo PROCESO_DOCUMENTO: lo une al proceso oficial)  ·  ASIGNAR_AMBITO {entidad, ambito}
          AMPLIAR_CATALOGO {clase: ENTIDAD|RELACION, id, etiqueta, familia (entidad), descripcion}  (nuevo tipo; úsalo después en el lote)
        Dividir una entidad: CREAR_ENTIDAD con ref + CORREGIR_RELACION de las relaciones que pasan a la nueva + CORREGIR_NOMBRE."""
        return c.kb.operar(operaciones, motivo, None, confirmar)

    @herramienta()
    def catalogo_kb() -> str:
        """Catálogo efectivo de la KB: tipos de relación (con su criterio), tipos de entidad por familia, ampliaciones hechas por
        decisión, estados y ámbitos. Para elegir tipo_id, familia y ámbito en operar_kb."""
        return c.kb.catalogo()

    @herramienta()
    def buscar_hpum(texto: str = "", limite: int = 20) -> str:
        """Procesos HPUM del Excel (nodos de la KB servida) por texto en su nombre o ruta: devuelve su id para ENLAZAR_HPUM o MAPEAR_A_HPUM."""
        return c.kb.buscar_hpum(texto, limite)

    @herramienta(ESCRITURA)
    def aplicar_correcciones_ficha(confirmar: str) -> str:
        """Guarda como decisiones auditables (autor = usuario del login) lo previsualizado con previsualizar_correcciones_ficha.
        Solo con el código que devolvió y después de que la persona lo apruebe. Cada decisión se puede deshacer."""
        return c.kb.aplicar_correcciones_ficha(confirmar)

    @herramienta()
    def fichas_revision() -> str:
        """Lotes de fichas de revisión generados en este puesto e importaciones de respuestas, con su estado."""
        return c.kb.fichas_revision()

    @herramienta()
    def historial(limite: int = 30, autor: str | None = None, accion: str | None = None) -> str:
        """Historial de decisiones (más recientes primero), con su sk para deshacer."""
        return c.kb.historial(limite, autor, accion)

    # ================================================================== admin: decisiones
    @herramienta(ESCRITURA)
    def validar(ids: list[str], motivo: str = "", confirmar: str | None = None) -> str:
        """Aprueba entidades, relaciones (REL-…) o correspondencias HPUM (HPUM|…). Un id: se guarda; varios: previsualiza y pide confirmar."""
        return c.kb.decidir("APROBAR", ids, {}, motivo, confirmar=confirmar)

    @herramienta(ESCRITURA)
    def rechazar(ids: list[str], motivo: str, confirmar: str | None = None) -> str:
        """Rechaza entidades, relaciones o correspondencias HPUM (motivo obligatorio). Varios ids: en dos pasos."""
        return c.kb.decidir("RECHAZAR", ids, {}, motivo, confirmar=confirmar)

    @herramienta(ESCRITURA)
    def corregir_tipo(ids: list[str], tipo_id: str, motivo: str, confirmar: str | None = None) -> str:
        """Cambia el tipo de entidades (tipo_id del catálogo; no PROCESO_HPUM). Motivo obligatorio. Varios ids: en dos pasos."""
        return c.kb.decidir("CORREGIR_TIPO", ids, {"tipo_id": tipo_id}, motivo, confirmar=confirmar)

    @herramienta(ESCRITURA)
    def corregir_nombre(id: str, nombre: str, motivo: str) -> str:  # noqa: A002
        """Corrige el nombre de UNA entidad (2–160 caracteres). Motivo obligatorio."""
        return c.kb.decidir("CORREGIR_NOMBRE", [id], {"nombre": nombre}, motivo)

    @herramienta(ESCRITURA)
    def fusionar(ids: list[str], conservar: str, motivo: str, confirmar: str | None = None) -> str:
        """Fusiona posibles duplicados (ids DUP|…); conservar = A o B (cuál queda). Motivo obligatorio. Varios: en dos pasos."""
        return c.kb.decidir("FUSIONAR", ids, {"conservar": conservar.upper()}, motivo, confirmar=confirmar)

    @herramienta(ESCRITURA)
    def mantener_separadas(ids: list[str], motivo: str = "", confirmar: str | None = None) -> str:
        """Marca posibles duplicados (DUP|…) como entidades distintas. Varios: en dos pasos."""
        return c.kb.decidir("MANTENER_SEPARADAS", ids, {}, motivo, confirmar=confirmar)

    @herramienta(ESCRITURA)
    def decidir_en_bloque(accion: str, criterio: str, valor: str | list[str], parametros: dict | None = None, motivo: str = "",
                          confirmar: str | None = None) -> str:
        """Decisión sobre un bloque, como en la web: criterio = proceso_hpum | tipo | familia | documento | grupo_duplicados |
        relaciones_tipo | ids; accion = APROBAR | RECHAZAR | CORREGIR_TIPO | CORREGIR_NOMBRE | FUSIONAR | MANTENER_SEPARADAS.
        Siempre en dos pasos (previsualiza; luego confirmar=<código>). Tope 2000 objetos."""
        return c.kb.decidir(accion, None, parametros, motivo, criterio=criterio, valor=valor, confirmar=confirmar)

    @herramienta(ESCRITURA)
    def deshacer(sk: str) -> str:
        """Deshace una decisión por su sk (fecha#dec_…, sale en historial). Queda registrada como DESHECHA."""
        return c.kb.deshacer(sk)

    @herramienta(ESCRITURA)
    def exportar_decisiones(formato: str = "csv", carpeta: str | None = None) -> str:
        """Exporta las decisiones activas (csv para Excel o json) a Descargas\\kortex o a la carpeta dada."""
        return c.kb.exportar_decisiones(formato, carpeta)

    # ================================================================== admin: consolidación
    @herramienta()
    def consolidaciones() -> str:
        """Lista las consolidaciones (eventos de revisión) y cuál está abierta."""
        return c.kb.consolidaciones()

    @herramienta(ESCRITURA)
    def abrir_consolidacion(nombre: str, objetivo: str = "") -> str:
        """Abre una consolidación (solo una abierta a la vez): las propuestas que se apliquen quedan asociadas a ella."""
        return c.kb.abrir_consolidacion(nombre, objetivo)

    @herramienta()
    def consolidacion(id: str) -> str:  # noqa: A002
        """Detalle de una consolidación (CONS-NNNN): estado, pendientes y decisiones."""
        return c.kb.consolidacion(id)

    @herramienta(ESCRITURA)
    def cerrar_consolidacion(id: str, nota: str = "") -> str:  # noqa: A002
        """Cierra una consolidación con una nota."""
        return c.kb.cerrar_consolidacion(id, nota)

    @herramienta()
    def propuestas(caso: str | None = None, limite: int = 30) -> str:
        """Propuestas de los agentes de consolidación sobre la KB actual (fusiones, relaciones, ámbitos, HPUM…), filtrables por caso."""
        return c.kb.propuestas(caso, limite)

    @herramienta()
    def explicar_propuesta(id: str) -> str:  # noqa: A002
        """Explica una propuesta: qué cambia (antes/después), señales con sus puntos, evidencias y objetos."""
        return c.kb.explicar_propuesta(id)

    @herramienta(ESCRITURA)
    def analizar_consolidacion() -> str:
        """Vuelve a ejecutar los agentes de consolidación y guarda la foto de salud (sin modelo)."""
        return c.kb.analizar()

    @herramienta(ESCRITURA)
    def aplicar_propuestas(ids: list[str], seleccion: dict | None = None, confirmar: str | None = None) -> str:
        """Aplica propuestas como decisiones en la consolidación abierta. Dos pasos. seleccion: {propuesta: [objetos]} para aplicar solo una parte."""
        return c.kb.aplicar_propuestas(ids, seleccion, confirmar)

    @herramienta(ESCRITURA)
    def descartar_propuestas(ids: list[str], motivo: str, confirmar: str | None = None) -> str:
        """Descarta propuestas (queda como decisión con su motivo). Dos pasos."""
        return c.kb.descartar_propuestas(ids, motivo, confirmar)

    # ================================================================== admin: fuentes
    @herramienta()
    def fuentes() -> str:
        """Estado de las fuentes de la KB (base Excel, ingesta, trabajos en curso)."""
        return c.kb.fuentes()

    @herramienta()
    def ingesta_pendiente(forzar: bool = False) -> str:
        """Lo analizado en la ingesta que la KB todavía no tiene (y lo que habría que quitar)."""
        return c.kb.ingesta_pendiente(forzar)

    @herramienta(DESTRUCTIVA)
    def actualizar_desde_ingesta(forzar: bool = False, confirmar: str | None = None) -> str:
        """Reconstruye la KB con lo analizado en la ingesta. Dos pasos (enseña lo pendiente y pide confirmar)."""
        return c.kb.actualizar_desde_ingesta(forzar, confirmar)

    @herramienta(DESTRUCTIVA)
    def quitar_o_incorporar_documentos(quitar: list[str] | None = None, incorporar: list[str] | None = None, confirmar: str | None = None) -> str:
        """Actualización dirigida: quita de la KB o incorpora documentos concretos (doc_id). Dos pasos."""
        return c.kb.documentos_kb(quitar, incorporar, confirmar)

    @herramienta()
    def estado_reanalisis() -> str:
        """Documentos por reanalizar, reanálisis en curso y estimación de coste."""
        return c.kb.reanalisis()

    @herramienta(DESTRUCTIVA)
    def reanalizar(documentos: list[str], confirmar: str | None = None) -> str:
        """Pide reanalizar documentos con el modelo (cuesta dinero). Dos pasos."""
        return c.kb.reanalizar(documentos, confirmar)

    @herramienta()
    def asistente_web(mensaje: str, historial: list[dict] | None = None, contexto: dict | None = None) -> str:
        """El asistente de la web de la KB, tal cual (para comparar con tus respuestas)."""
        return c.kb.asistente_web(mensaje, historial, contexto)

    # ================================================================== admin: prompts
    @srv.prompt(name="revision_de_carga", description="Revisa lo que ha entrado en la KB desde la última revisión y prepara las decisiones.")
    def revision_de_carga(desde: str = "") -> str:
        return ("Revisión de carga de la KB KORTEX" + (f" desde {desde}" if desde else "") + ".\n"
                f"1. lo_nuevo_desde({'fecha=' + repr(desde) if desde else ''}) y estado_kb. 2. ingesta_pendiente: ¿falta algo por incorporar? "
                "3. Para los documentos nuevos, documento_en_kb: entidades y relaciones extraídas, advertencias y descartes. "
                "4. propuestas y explicar_propuesta de las de más confianza. 5. Devuélveme una tabla: qué validar, qué rechazar (con motivo), "
                "qué fusionar y qué dudas hay, con la cita que lo justifica. NO ejecutes ninguna decisión: espera a que te diga cuáles. "
                "6. Al terminar, si te lo confirmo, marcar_revision.")

    @srv.prompt(name="informe_de_siempre", description="El informe periódico del estado de la KB.")
    def informe_de_siempre() -> str:
        return ("Informe de la KB KORTEX: 1. estado_kb y metricas. 2. historial (últimas 30) y consolidaciones. 3. lo_nuevo_desde. "
                "Redacta en español, breve: versión y fecha; contenido (documentos, entidades, relaciones); avance de la revisión (pendiente, "
                "aprobado, rechazado) y su evolución; salud según los agentes; qué ha cambiado y quién ha decidido qué; tres siguientes pasos "
                "recomendados. Sin inventar cifras: solo las que devuelven las herramientas.")

    @srv.prompt(name="contrastar_kb", description="Contrasta un tema en la KB con su contexto y con la documentación que ve el usuario.")
    def contrastar_kb(tema: str) -> str:
        return (f"Tema: «{tema}». 1. buscar_entidades y entidad de las más relevantes; contexto(entidad=…). 2. por_que de las relaciones "
                "clave. 3. consultar(pregunta=…) para ver lo que dice la documentación. 4. Señala lo que la KB "
                "tiene sin respaldo suficiente, lo que falta y las contradicciones; propón decisiones sin ejecutarlas.")

    return srv
