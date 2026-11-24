"""KB servida sintética para las pruebas de fichas: entidades y relaciones con TODAS las confianzas (VALIDADO_AUTO, PROPUESTO,
EN_CONFLICTO, nula y una desconocida), relaciones entrantes y salientes, una entidad sin relaciones, un posible duplicado y un proceso
HPUM. Casos del procedimiento (los números son los del encargo):
 1. SIRIO (VALIDADO_AUTO) con todas sus relaciones VALIDADO_AUTO.
 2. SIGMA (VALIDADO_AUTO) con relaciones PROPUESTO (REL-004 entrante, REL-011 saliente hacia SICO, también VALIDADO_AUTO).
 3. SIRIO 4P (PROPUESTO) con una relación VALIDADO_AUTO.
 4. «Entidad huérfana» (PROPUESTO) sin relaciones.
 5. SIGMA tiene relaciones entrantes y salientes.
 6. REL-001 (SIGMA → SIRIO) la comparten dos entidades en revisión.
 7. SAP y «SAP ERP» son un posible duplicado.
Nada sale de la KB real."""
import copy


def _rel(rid, o, t, d, conf, cita, doc="D1", **k):
    return {"relacion_id": rid, "origen": o, "destino": d, "tipo_id": t, "estado": "JUSTIFICADA_POR_CONTENIDO", "documentos": [doc], "validacion": "CANDIDATA",
            "origen_dato": k.pop("origen_dato", "INGESTA"), "confianza": conf, "avisos": k.pop("avisos", []),
            "confianza_motivos": k.pop("motivos", ["relación y tipos del catálogo", "justificada por el contenido",
                                                   "cita literal localizada" if conf == "VALIDADO_AUTO" else "sin cita literal exacta"]),
            "evidencias": [{"fuente": "CONTENIDO", "cita": cita, "doc_id": doc, "ubicacion": k.pop("ubicacion", "página 3"), "coincidencia": "EXACTA",
                            "justificacion": k.pop("just", "El modelo lo lee así.")}], **k}


ENTIDADES = [  # id, nombre, tipo, familia, ámbito, confianza
    ("E-SIGMA", "SIGMA", "SISTEMA", "TECNO", "A-RED", "VALIDADO_AUTO"), ("E-SIRIO", "SIRIO", "SISTEMA", "TECNO", "A-RED", "VALIDADO_AUTO"),
    ("E-SIRIO4P", "SIRIO 4P", "MODULO", "TECNO", "A-RED", "PROPUESTO"), ("E-SAP", "SAP", "SISTEMA", "TECNO", "A-RED", "VALIDADO_AUTO"),
    ("E-SAP2", "SAP ERP", "SISTEMA", "TECNO", "A-RED", "PROPUESTO"), ("E-SICO", "SICO", "SISTEMA", "TECNO", "A-RED", "VALIDADO_AUTO"),
    ("E-CONTR", "Contratista <b>", "PROVEEDOR", "EXT", "A-RED", "PROPUESTO"), ("E-EQ", "Equipo de obras", "EQUIPO", "ORG", "A-RED", "VALIDADO_AUTO"),
    ("E-OT", "Orden de trabajo", "OBJETO_NEGOCIO", "OBJ", "A-RED", "PROPUESTO"), ("E-GAS", "Contador de gas", "ACTIVO_FISICO", "ACTIVO", "A-GAS", "EN_CONFLICTO"),
    ("E-KPI", "Plazo medio", "INDICADOR", "KPI", "A-GAS", None), ("E-SUELTA", "Iniciativa suelta", "INICIATIVA", "INI", None, "RARO_FUTURO"),
    ("E-HUERFANA", "Entidad huérfana", "ENTREGABLE", "OBJ", "A-RED", "PROPUESTO"),
]


def servida(extra_va=0):
    D = {"campana_id": "KORTEX", "estado": "PROCESADA", "fecha": "2026-11-20T08:00:00Z",
         "entidades": [{"entidad_id": i, "nombre": n, "tipo_id": t, "familia": f, "confianza": c, "estado": "PROPUESTA",
                        "confianza_motivos": ["tipo del catálogo", "cita literal localizada" if c == "VALIDADO_AUTO" else "sin cita literal exacta"],
                        "alias": ["Sistema de obras"] if i == "E-SIGMA" else [], "documentos": ["D1"],
                        "descripciones": [{"doc_id": "D1", "texto": f"Descripción de {n} en el manual."}],
                        "menciones": [{"doc_id": "D1", "nombre_en_documento": n, "evidencia": {"cita": f"{n} aparece en el manual", "doc_id": "D1", "ubicacion": "página 1"}}]}
                       for i, n, t, f, _, c in ENTIDADES],
         "documentos": [{"doc_id": "D1", "nombre": "Manual de obras.docx"}, {"doc_id": "D2", "nombre": "Inventario.xlsx"}],
         "posibles_duplicados": [{"entidad_a": "E-SAP", "nombre_a": "SAP", "tipo_a": "SISTEMA", "entidad_b": "E-SAP2", "nombre_b": "SAP ERP", "tipo_b": "SISTEMA",
                                  "clase": "CANDIDATO_DUPLICADO", "decision": "NO_FUSIONADAS_REVISAR"}],
         "relaciones": [
             _rel("REL-001", "E-SIGMA", "INTEGRA_CON", "E-SIRIO", "VALIDADO_AUTO", "SIGMA envía las obras a SIRIO"),
             _rel("REL-002", "E-SIGMA", "INTEGRA_CON", "E-SAP", "VALIDADO_AUTO", "SIGMA vuelca los costes en SAP"),
             _rel("REL-003", "E-SIRIO4P", "FORMA_PARTE_DE", "E-SIRIO", "VALIDADO_AUTO", "SIRIO 4P es un módulo de SIRIO", origen_dato="BASE_EXCEL", doc="D2", ubicacion="celda 01_Redes!M27"),
             _rel("REL-004", "E-CONTR", "UTILIZA", "E-SIGMA", "PROPUESTO", "Los contratistas trabajan con la herramienta de obras"),
             _rel("REL-005", "E-EQ", "GESTIONA", "E-OT", "VALIDADO_AUTO", "El equipo gestiona las órdenes de trabajo"),
             _rel("REL-006", "HPUM:Redes > Obras", "PRODUCE", "E-OT", "VALIDADO_AUTO", "El proceso de obras genera la OT", origen_dato="BASE_EXCEL"),
             _rel("REL-007", "E-KPI", "MIDE", "E-GAS", "EN_CONFLICTO", "El plazo medio mide la instalación de contadores"),
             _rel("REL-008", "E-SUELTA", "AFECTA_A", "E-EQ", None, "La iniciativa cambia el equipo"),
             _rel("REL-009", "E-GAS", "DEPENDE_DE", "E-SAP", "RARO_FUTURO", "El contador depende de SAP <script>alert(1)</script>"),
             _rel("REL-010", "E-SIRIO", "INTEGRA_CON", "E-SAP", "VALIDADO_AUTO", "SIRIO intercambia datos con SAP", avisos=["DE_UNA_PASADA_ANTERIOR"]),
             _rel("REL-011", "E-SIGMA", "INTEGRA_CON", "E-SICO", "PROPUESTO", "SIGMA podría pasar datos al SICO"),
         ],
         "grafo": {"nodos": [*({"id": i, "clase": "ENTIDAD", "etiqueta": n, "tipo_id": t} for i, n, t, _, _, _ in ENTIDADES),
                             {"id": "A-RED", "clase": "AMBITO", "etiqueta": "Redes"}, {"id": "A-GAS", "clase": "AMBITO", "etiqueta": "Gas"},
                             {"id": "HPUM:Redes > Obras", "clase": "HPUM", "etiqueta": "Obras", "nivel": "N2", "ambitos": ["A-RED"], "propiedades": {"ruta": "Redes > Obras"}}],
                   "aristas": [{"id": f"am-{i}", "clase": "AMBITO_ENTIDAD", "origen": i, "destino": a} for i, _, _, _, a, _ in ENTIDADES if a]}}
    for k in range(extra_va):                       # relleno para probar el reparto en varias fichas: entidades nuevas con sus relaciones
        eid = f"E-X{k:03d}"
        D["entidades"].append({"entidad_id": eid, "nombre": f"Sistema {k:03d}", "tipo_id": "SISTEMA", "familia": "TECNO", "confianza": "VALIDADO_AUTO" if k % 3 else "PROPUESTO",
                               "alias": [], "documentos": ["D1"], "descripciones": [], "menciones": []})
        D["grafo"]["nodos"].append({"id": eid, "clase": "ENTIDAD", "etiqueta": f"Sistema {k:03d}", "tipo_id": "SISTEMA"})
        D["grafo"]["aristas"].append({"id": f"am-{eid}", "clase": "AMBITO_ENTIDAD", "origen": eid, "destino": "A-RED"})
        for j, dst in enumerate(("E-SAP", "E-OT")[: 1 + k % 2]):
            D["relaciones"].append(_rel(f"REL-X{k:03d}{j}", eid, "UTILIZA", dst, "VALIDADO_AUTO" if (k + j) % 4 else "PROPUESTO", f"Cita de relleno {k}-{j}"))
    return copy.deepcopy(D)
