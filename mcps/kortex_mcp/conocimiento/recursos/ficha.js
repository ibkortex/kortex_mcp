/* Ficha de relaciones de un elemento (19/11/2026): desde Explorar se elige cualquier elemento (entidad, ámbito, proceso HPUM,
   documento) y se descarga UN HTML autocontenido con todo lo relacionado con él, para validarlo en local o compartirlo.
   Formato del catálogo funcional base (ámbito → tipo → elemento, mismas tarjetas y estados) y las relaciones en línea,
   «origen ── RELACIÓN ▸ ── destino», como en Consolidar. Todo sale de la KB SERVIDA (la que ven la web, el Excel y la IA)
   y del estado de revisión del momento; el HTML no llama a nada: abre sin conexión y se puede imprimir. */

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const FAMILIA = { PROC: 'Procesos y capacidades', TECNO: 'Tecnología y sistemas', OBJ: 'Objetos y datos', PERSONA: 'Personas y roles', INI: 'Iniciativas',
  ORG: 'Organización', EXT: 'Entidades externas', NOR: 'Normativa y requisitos', KPI: 'Indicadores', ACTIVO: 'Activos físicos', CONO: 'Conocimiento', OTRA: 'Otras' };
// Estados de la KB (kbweb_estados, 23/11/2026): «Validado» solo lo pone una persona; lo demás está pendiente y dice qué le falta.
const CONF = { VALIDADO: 'Validado', PENDIENTE_VALIDAR: 'Pendiente de validar', SIN_CORROBORAR: 'Sin corroborar', SIN_CITA_LITERAL: 'Sin cita literal', SIN_EVIDENCIA: 'Deducido sin evidencia', FUERA_DE_CATALOGO: 'Fuera del catálogo', SIN_VINCULAR: 'Sin vincular', EN_CONFLICTO: 'En conflicto', VALIDADO_PERSONA: 'Validado', VALIDADO_AUTO: 'Pendiente de validar', PROPUESTO: 'Sin corroborar' };
const GRUPO = { APLICACION_SISTEMA: 'g-app', COMPONENTE_TECNICO: 'g-comp', CAPACIDAD_ACTIVIDAD: 'g-cap', OTRA: 'g-otra', HPUM: 'g-hpum', AMBITO: 'g-amb',
  DOCUMENTO: 'g-doc', SIN_ENCAJE_CATALOGO: 'g-sin' };
const SECCION = { RELACION_KB: 'rel', CORRESPONDENCIA_HPUM: 'hpum', DOCUMENTO_HPUM: 'hpum', JERARQUIA_HPUM: 'hpum', AMBITO_ENTIDAD: 'amb', CLASIFICACION_AMBITO: 'amb',
  MENCION: 'doc', SIN_ENCAJE: 'doc', RELACION_ENTRE_DOCUMENTOS: 'doc' };
const SECCIONES = [
  ['rel', 'Relaciones con otras entidades', 'Lo que la KB ha extraído del contenido de los documentos: qué usa, qué soporta, de qué forma parte… con la cita que lo justifica.'],
  ['hpum', 'Procesos HPUM', 'Correspondencias con el catálogo de procesos HPUM y, en los procesos, su posición en la jerarquía.'],
  ['amb', 'Ámbitos de negocio', 'Ámbitos a los que pertenece, deducidos de los documentos en los que aparece.'],
  ['doc', 'Documentos', 'Documentos en los que aparece, con la cita literal de cada mención.'],
  ['n2', 'Segundo nivel', 'Relaciones de las entidades conectadas con otras entidades: el contexto alrededor del elemento.'],
];
const ESTADO = { ok: 'Aprobada', corr: 'Corregida', pending: 'Pendiente de revisar', doubt: 'Hipótesis por confirmar', rej: 'Rechazada', cat: 'Del catálogo' };
const DUDOSAS = new Set(['HIPOTESIS_RUTA_NOMBRE', 'DEDUCIDA_POR_COINCIDENCIA_ENTRE_DOCUMENTOS']);
const MAX_CITAS = 3;

const bonito = (v) => String(v || '').replace(/_/g, ' ').toLowerCase().replace(/^./, (c) => c.toUpperCase()).replace(/hpum/gi, 'HPUM')
  .replace(/^Proceso documento$/i, 'Proceso citado (sin mapear a HPUM)');
const verbo = (v) => String(v || '').replace(/_/g, ' ').toLowerCase().replace(/hpum/gi, 'HPUM');
const ultimo = (ruta) => { const p = String(ruta || '').split(' > '); return [p[p.length - 1], p.slice(0, -1)]; };

/** Modelo de la ficha. saltos = 1 (solo lo directo) o 2 (también las relaciones de las entidades conectadas). */
export function construirFicha(D, estado, id, { saltos = 1, huella = '' } = {}) {
  const nodos = new Map(D.grafo.nodos.map((n) => [n.id, n]));
  const raiz = nodos.get(id);
  if (!raiz) throw new Error('Ese elemento ya no está en la KB');
  const ENT = new Map((D.entidades || []).map((e) => [e.entidad_id, e]));
  const REL = new Map((D.relaciones || []).map((r) => [r.relacion_id, r]));
  const DOC = new Map((D.documentos || []).map((d) => [d.doc_id, d]));
  const amb = new Map(D.grafo.nodos.filter((n) => n.clase === 'AMBITO').map((n) => [n.id, n.etiqueta]));
  const adj = new Map();
  for (const a of D.grafo.aristas) if (nodos.has(a.origen) && nodos.has(a.destino)) for (const k of [a.origen, a.destino]) (adj.get(k) || adj.set(k, []).get(k)).push(a);
  const rv = (oid) => (oid && estado[oid]) || null;

  const nombreDe = (n) => {
    const r = rv(n.id), p = (r && r.parametros) || {};
    if (n.clase === 'ENTIDAD') return p.nombre || (ENT.get(n.id) || {}).nombre || n.etiqueta;
    if (n.clase === 'HPUM') return ultimo((n.propiedades || {}).ruta || n.etiqueta)[0];
    return n.etiqueta || n.id;
  };
  const tipoDe = (n) => {
    if (n.clase === 'ENTIDAD') { const r = rv(n.id); return bonito((r && r.parametros && r.parametros.tipo_id) || n.tipo_id); }
    if (n.clase === 'HPUM') { const [, arriba] = ultimo((n.propiedades || {}).ruta || ''); return `Proceso HPUM ${n.nivel || ''}`.trim() + (arriba.length ? ' · ' + arriba.join(' › ') : ''); }
    if (n.clase === 'AMBITO') return 'Ámbito de negocio';
    if (n.clase === 'DOCUMENTO') { const f = (n.propiedades || {}).formato; return 'Documento' + (f ? ' ' + f : ''); }
    if (n.clase === 'SIN_ENCAJE') return 'Concepto sin encaje en el catálogo';
    return bonito(n.clase);
  };
  const chip = (n) => ({ id: n.id, nombre: nombreDe(n), tipo: tipoDe(n), grupo: GRUPO[n.grupo] || 'g-otra', ent: n.clase === 'ENTIDAD' });
  const docNombre = (d) => { const x = DOC.get(d); return x ? x.nombre : (nodos.get(d) || {}).etiqueta || d; };

  const objeto = (a) => a.clase === 'RELACION_KB' ? (a.relacion_id || a.id) : a.clase === 'CORRESPONDENCIA_HPUM' ? `HPUM|${a.origen}|${a.destino}` : null;
  const estadoDe = (a) => {
    const r = rv(objeto(a));
    if (r) return { APROBADA: 'ok', CORREGIDA: 'corr', RECHAZADA: 'rej' }[r.estado] || 'pending';
    if (a.estado === 'CATALOGO') return 'cat';
    return DUDOSAS.has(a.estado) ? 'doubt' : 'pending';
  };
  const notas = (a) => {
    const r = a.clase === 'RELACION_KB' ? REL.get(a.relacion_id) || a : a;
    const out = [];
    for (const e of (r.evidencias || a.evidencias || [])) {
      if (!e || !e.cita) continue;
      const loc = e.ubicacion || (e.locator ? Object.entries(e.locator).map(([k, v]) => `${k} ${v}`).join(' · ') : '');
      out.push({ cita: e.cita, doc: e.doc_id ? docNombre(e.doc_id) : '', loc, just: e.justificacion || '' });
    }
    for (const j of (a.justificaciones || [])) out.push({ cita: '', doc: j.doc_id ? docNombre(j.doc_id) : '', loc: '', just: j.texto || '' });
    if (!out.length && (a.confianza_motivos || []).length) out.push({ cita: '', doc: '', loc: '', just: a.confianza_motivos.join(' · ') });
    if (!out.length && a.estado === 'DEDUCIDA_DEL_DOCUMENTO') out.push({ cita: '', doc: '', loc: '', just: 'Deducido: aparece en documentos de este ámbito.' });
    return out;
  };
  const flujo = (a, seccion) => {
    const o = nodos.get(a.origen), d = nodos.get(a.destino), r = rv(objeto(a));
    return { seccion, tipo: a.tipo_id, rel: verbo(a.tipo_id), o: chip(o), d: chip(d), estado: estadoDe(a), notas: notas(a),
      autor: r ? `${r.autor} · ${String(r.en || '').slice(0, 16).replace('T', ' ')}${r.motivo ? ' · ' + r.motivo : ''}` : '',
      docs: [...new Set([...(a.documentos || []).map(docNombre), ...notas(a).map((x) => x.doc).filter(Boolean)])] };
  };

  // ---------------------------------------------------------------- primer nivel: todo lo que toca al elemento
  const directas = (adj.get(id) || []).filter((a) => SECCION[a.clase]);
  const flujos = directas.map((a) => flujo(a, SECCION[a.clase]));
  const vecinos = new Set(directas.map((a) => (a.origen === id ? a.destino : a.origen)));
  // ---------------------------------------------------------------- segundo nivel: relaciones entre entidades de cada entidad conectada
  const segundo = [];
  if (saltos > 1) {
    const vistas = new Set(directas.map((a) => a.id || a.relacion_id));
    for (const v of vecinos) {
      const nv = nodos.get(v);
      if (!nv || nv.clase !== 'ENTIDAD') continue;
      const fs = (adj.get(v) || []).filter((a) => a.clase === 'RELACION_KB' && a.origen !== id && a.destino !== id && !vistas.has(a.id || a.relacion_id))
        .map((a) => flujo(a, 'n2'));
      if (fs.length) segundo.push({ via: chip(nv), flujos: fs });
    }
    segundo.sort((x, y) => y.flujos.length - x.flujos.length || x.via.nombre.localeCompare(y.via.nombre, 'es'));
  }

  // ---------------------------------------------------------------- entidades relacionadas, como en el catálogo (ámbito → tipo → entidad)
  const ids = new Set([...vecinos, ...segundo.flatMap((g) => g.flujos.flatMap((f) => [f.o.id, f.d.id]))]); ids.delete(id);
  const ambDe = new Map();
  for (const a of D.grafo.aristas) if (a.clase === 'AMBITO_ENTIDAD') (ambDe.get(a.origen) || ambDe.set(a.origen, []).get(a.origen)).push(amb.get(a.destino) || a.destino);
  const tarjeta = (eid) => {
    const n = nodos.get(eid), e = ENT.get(eid) || {}, r = rv(eid), men = (e.menciones || []).find((m) => m.evidencia && m.evidencia.cita);
    return { id: eid, nombre: nombreDe(n), tipo: tipoDe(n), familia: FAMILIA[e.familia] || bonito(e.familia || 'OTRA'), grupo: GRUPO[n.grupo] || 'g-otra',
      estado: r ? ({ APROBADA: 'ok', CORREGIDA: 'corr', RECHAZADA: 'rej' }[r.estado] || 'pending') : 'pending',
      desc: ((e.descripciones || [])[0] || {}).texto || '', alias: e.alias || [], conf: CONF[e.confianza || n.confianza] || '',
      hpum: (e.correspondencias_hpum || []).map((c) => c.ruta || c.nodo_id), docs: (e.documentos || []).map(docNombre),
      cita: men ? men.evidencia.cita : '', ambitos: ambDe.get(eid) || ['Sin ámbito asignado'] };
  };
  const porAmb = new Map();
  for (const eid of ids) {
    const n = nodos.get(eid);
    if (!n || n.clase !== 'ENTIDAD') continue;
    const t = tarjeta(eid);
    for (const a of t.ambitos) (porAmb.get(a) || porAmb.set(a, []).get(a)).push(t);
  }
  const catalogo = [...porAmb.entries()].map(([nombre, ts]) => {
    const tipos = new Map(); ts.forEach((t) => (tipos.get(t.tipo) || tipos.set(t.tipo, []).get(t.tipo)).push(t));
    return { nombre, total: ts.length, tipos: [...tipos.entries()].map(([tipo, x]) => ({ tipo, items: x.sort((p, q) => p.nombre.localeCompare(q.nombre, 'es')) }))
      .sort((p, q) => q.items.length - p.items.length) };
  }).sort((p, q) => q.total - p.total);

  // ---------------------------------------------------------------- cabecera: la ficha del propio elemento
  const e = ENT.get(id) || {}, rr = rv(id), props = raiz.propiedades || {};
  const ficha = [];
  if (raiz.clase === 'ENTIDAD') {
    ficha.push(['Tipo', tipoDe(raiz)], ['Familia', FAMILIA[e.familia] || bonito(e.familia || '')], ['Ámbitos', (ambDe.get(id) || ['Sin ámbito asignado']).join(' · ')],
      ['Estado', CONF[e.confianza || raiz.confianza] || '—'], ['Revisión', rr ? `${ESTADO[{ APROBADA: 'ok', CORREGIDA: 'corr', RECHAZADA: 'rej' }[rr.estado] || 'pending']} · ${rr.autor}` : ESTADO.pending]);
    if ((e.alias || []).length) ficha.push(['También llamado', e.alias.join(' · ')]);
    if ((e.correspondencias_hpum || []).length) ficha.push(['Procesos HPUM', e.correspondencias_hpum.map((c) => c.ruta || c.nodo_id).join('\n')]);
    ficha.push(['Documentos', (e.documentos || []).map(docNombre).join('\n') || '—']);
  } else if (raiz.clase === 'HPUM') {
    ficha.push(['Nivel', raiz.nivel || '—'], ['Ruta en el catálogo', String(props.ruta || raiz.etiqueta).split(' > ').join(' › ')], ['Ámbitos', (raiz.ambitos || []).map((a) => amb.get(a) || a).join(' · ') || '—']);
    if (props.descripcion) ficha.push(['Descripción', props.descripcion]);
  } else if (raiz.clase === 'DOCUMENTO') {
    const d = DOC.get(id) || {};
    ficha.push(['Ruta documental', props.ruta_documental || d.nombre || '—'], ['Lectura', props.estado || d.estado || '—'], ['Ámbitos', (raiz.ambitos || []).map((a) => amb.get(a) || a).join(' · ') || '—']);
    if (props.tipo_documental) ficha.push(['Qué es', props.tipo_documental]);
  } else if (raiz.clase === 'AMBITO') {
    if (props.descripcion) ficha.push(['Descripción', props.descripcion]);
    ficha.push(['Documentos clasificados', String((raiz.documentos || []).length)]);
  }
  const descripciones = (e.descripciones || []).slice(0, 3).map((x) => ({ texto: x.texto, doc: x.doc_id ? docNombre(x.doc_id) : '' })).filter((x) => x.texto);

  const docsFuente = new Set([...flujos, ...segundo.flatMap((g) => g.flujos)].flatMap((f) => f.docs));
  return {
    campana: D.campana_id, huella, fecha: new Date(), saltos, raiz: chip(raiz), clase: raiz.clase, ficha, descripciones,
    secciones: SECCIONES.filter(([k]) => k !== 'n2').map(([k, t, p]) => {
      const fs = flujos.filter((f) => f.seccion === k), tipos = new Map();
      fs.forEach((f) => (tipos.get(f.rel) || tipos.set(f.rel, []).get(f.rel)).push(f));
      return { k, titulo: t, texto: p, total: fs.length, tipos: [...tipos.entries()].map(([rel, x]) => ({ rel, flujos: x })).sort((a, b) => b.flujos.length - a.flujos.length) };
    }).filter((s) => s.total),
    segundo, n2: SECCIONES.find(([k]) => k === 'n2'), catalogo,
    kpis: { directas: flujos.length, entidades: [...ids].filter((x) => (nodos.get(x) || {}).clase === 'ENTIDAD').length,
      hpum: new Set(flujos.filter((f) => f.seccion === 'hpum').flatMap((f) => [f.o, f.d]).filter((c) => c.grupo === 'g-hpum' && c.id !== id).map((c) => c.id)).size,
      documentos: docsFuente.size, pendientes: [...flujos, ...segundo.flatMap((g) => g.flujos)].filter((f) => f.estado === 'pending' || f.estado === 'doubt').length },
  };
}

// ==================================================================== HTML autocontenido
const nodoHtml = (c, raizId) => {
  const cuerpo = `<span class="nd-dot ${c.grupo}" aria-hidden="true"></span><span class="nd-t"><b>${esc(c.nombre)}</b><small>${esc(c.tipo)}</small></span>`;
  if (c.id === raizId) return `<span class="nd yo" title="El elemento de esta ficha">${cuerpo}</span>`;
  return c.ent ? `<a class="nd" href="#e-${esc(c.id)}" title="Ver su ficha más abajo">${cuerpo}</a>` : `<span class="nd">${cuerpo}</span>`;
};
const flujoHtml = (f, raizId) => {
  const q = [f.o.nombre, f.rel, f.d.nombre, ...f.notas.map((n) => n.cita + ' ' + n.doc + ' ' + n.just)].join(' ').toLowerCase();
  const citas = f.notas.slice(0, MAX_CITAS).map((n) => `<li>${n.cita ? `<q>${esc(n.cita)}</q>` : ''}${n.just ? `<span class="just">${esc(n.just)}</span>` : ''}${n.doc || n.loc ? `<span class="src">${esc([n.doc, n.loc].filter(Boolean).join(' · '))}</span>` : ''}</li>`).join('');
  const mas = f.notas.length > MAX_CITAS ? `<li class="src">y ${f.notas.length - MAX_CITAS} citas más en los mismos documentos</li>` : '';
  return `<article class="flujo ${f.estado}" data-q="${esc(q)}" data-estado="${f.estado}">
    <div class="fl-linea">${nodoHtml(f.o, raizId)}<span class="fl-rel" aria-label="${esc(f.rel)}"><span class="fl-l"></span><span class="fl-tag">${esc(f.rel)}</span><span class="fl-l fl-punta"></span></span>${nodoHtml(f.d, raizId)}</div>
    <div class="fl-pie"><span class="review-state ${f.estado}">${ESTADO[f.estado]}</span>${f.autor ? `<span class="src">${esc(f.autor)}</span>` : ''}</div>
    ${citas || mas ? `<ul class="fl-citas">${citas}${mas}</ul>` : ''}</article>`;
};
const plural = (n, s, p) => `${n.toLocaleString('es-ES')} ${n === 1 ? s : p}`;

export function htmlFicha(m) {
  const R = m.raiz.id;
  const kp = (v, t) => `<div class="review-kpi"><b>${esc(v.toLocaleString('es-ES'))}</b><small>${esc(t)}</small></div>`;
  const secciones = m.secciones.map((s, i) => `<details class="review-scope" data-seccion="${s.k}"${i < 2 ? ' open' : ''}>
    <summary><span><strong>${esc(s.titulo)}</strong><span class="caption">${esc(s.texto)}</span></span><span class="meta" data-cuenta>${plural(s.total, 'relación', 'relaciones')}</span></summary>
    <div class="review-scope-body">${s.tipos.map((t) => `<details class="review-type" open><summary><b>${esc(t.rel.replace(/^./, (c) => c.toUpperCase()))}</b><span class="review-num" data-cuenta>${t.flujos.length}</span></summary>
      <div class="flujos">${t.flujos.map((f) => flujoHtml(f, R)).join('')}</div></details>`).join('')}</div></details>`).join('');
  const segundo = m.segundo.length ? `<details class="review-scope" data-seccion="n2">
    <summary><span><strong>${esc(m.n2[1])}</strong><span class="caption">${esc(m.n2[2])}</span></span><span class="meta" data-cuenta>${plural(m.segundo.reduce((a, g) => a + g.flujos.length, 0), 'relación', 'relaciones')}</span></summary>
    <div class="review-scope-body">${m.segundo.map((g) => `<details class="review-family"><summary><span class="via">A través de ${nodoHtml(g.via, R)}</span><small data-cuenta>${plural(g.flujos.length, 'relación', 'relaciones')}</small></summary>
      <div class="review-family-body flujos">${g.flujos.map((f) => flujoHtml(f, R)).join('')}</div></details>`).join('')}</div></details>` : '';
  const item = (t) => `<article class="review-item ${t.estado}" id="e-${esc(t.id)}" data-q="${esc((t.nombre + ' ' + t.tipo + ' ' + t.alias.join(' ') + ' ' + t.hpum.join(' ') + ' ' + t.docs.join(' ')).toLowerCase())}" data-estado="${t.estado}">
    <span class="it-cab"><span class="nd-dot ${t.grupo}" aria-hidden="true"></span><strong>${esc(t.nombre)}</strong><span class="review-state ${t.estado}">${ESTADO[t.estado]}</span></span>
    ${t.desc ? `<span class="desc">${esc(t.desc)}</span>` : ''}
    <span class="links"><b>Tipo:</b> ${esc(t.tipo)} · <b>Familia:</b> ${esc(t.familia)}${t.conf ? ` · <b>Estado:</b> ${esc(t.conf)}` : ''}${t.alias.length ? ` · <b>Alias:</b> ${esc(t.alias.slice(0, 3).join(', '))}` : ''}</span>
    ${t.hpum.length ? `<span class="links"><b>Proceso HPUM:</b> ${esc(t.hpum.slice(0, 3).join(' · '))}${t.hpum.length > 3 ? ` (+${t.hpum.length - 3})` : ''}</span>` : ''}
    ${t.cita ? `<q class="cita">${esc(t.cita.slice(0, 260))}${t.cita.length > 260 ? '…' : ''}</q>` : ''}
    <span class="source">Fuente: ${esc(t.docs.slice(0, 3).join(' · ') || '—')}${t.docs.length > 3 ? ` (+${t.docs.length - 3})` : ''}</span></article>`;
  const catalogo = m.catalogo.length ? `<details class="review-scope" data-seccion="cat">
    <summary><span><strong>Entidades relacionadas</strong><span class="caption">Cada entidad que aparece arriba, ordenada como en el catálogo: ámbito, tipo y entidad. Una entidad aparece en todos sus ámbitos.</span></span><span class="meta" data-cuenta>${plural(m.kpis.entidades, 'entidad', 'entidades')}</span></summary>
    <div class="review-scope-body">${m.catalogo.map((a) => `<details class="review-family"><summary><strong>${esc(a.nombre)}</strong><small data-cuenta>${plural(a.total, 'entidad', 'entidades')} · ${plural(a.tipos.length, 'tipo', 'tipos')}</small></summary>
      <div class="review-family-body">${a.tipos.map((t) => `<details class="review-type"><summary><b>${esc(t.tipo)}</b><span class="review-num" data-cuenta>${t.items.length}</span></summary><div class="review-items">${t.items.map(item).join('')}</div></details>`).join('')}</div></details>`).join('')}</div></details>` : '';
  const ficha = m.ficha.length || m.descripciones.length ? `<section class="ficha" aria-label="Ficha del elemento"><dl>${m.ficha.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v).replace(/\n/g, '<br>')}</dd></div>`).join('')}</dl>
    ${m.descripciones.length ? `<div class="descs">${m.descripciones.map((d) => `<p>${esc(d.texto)}${d.doc ? `<span class="src">${esc(d.doc)}</span>` : ''}</p>`).join('')}</div>` : ''}</section>` : '';
  const vacio = !m.secciones.length && !m.segundo.length ? '<p class="review-empty">Este elemento no tiene relaciones en la KB servida.</p>' : '';
  const fecha = m.fecha.toLocaleString('es-ES', { dateStyle: 'long', timeStyle: 'short' });
  return `<header class="hero">
    <div class="hero-cab"><span class="nd-dot grande ${m.raiz.grupo}" aria-hidden="true"></span><div><h1>${esc(m.raiz.nombre)}</h1><p class="hero-tipo">${esc(m.raiz.tipo)}</p></div></div>
    <p>Ficha de relaciones de la KB ${esc(m.campana)}${m.huella ? `, versión ${esc(m.huella)}` : ''}. Generada el ${esc(fecha)} con ${m.saltos > 1 ? 'las relaciones directas y las de segundo nivel' : 'las relaciones directas'}.</p>
  </header>
  <div class="review-app">
    ${ficha}
    <div class="review-tools" role="search">
      <input id="f-q" type="search" placeholder="Buscar en las relaciones, citas y documentos…" aria-label="Buscar" autocomplete="off">
      <select id="f-sec" aria-label="Sección"><option value="">Todas las secciones</option>${[...m.secciones.map((s) => [s.k, s.titulo]), ...(m.segundo.length ? [['n2', m.n2[1]]] : []), ...(m.catalogo.length ? [['cat', 'Entidades relacionadas']] : [])].map(([k, t]) => `<option value="${k}">${esc(t)}</option>`).join('')}</select>
      <select id="f-est" aria-label="Estado de revisión"><option value="">Cualquier estado</option>${['pending', 'doubt', 'ok', 'corr', 'rej'].map((k) => `<option value="${k}">${ESTADO[k]}</option>`).join('')}</select>
      <button type="button" id="f-abrir">Desplegar todo</button><button type="button" id="f-imp">Imprimir o PDF</button>
    </div>
    <div class="review-kpis">${kp(m.kpis.directas, 'relaciones directas')}${kp(m.kpis.entidades, 'entidades conectadas')}${kp(m.kpis.hpum, 'procesos HPUM')}${kp(m.kpis.documentos, 'documentos que lo sustentan')}</div>
    <div class="review-legend"><span class="ok">Aprobada o corregida</span><span class="pending">Pendiente de revisar</span><span class="doubt">Hipótesis por confirmar</span><span class="rej">Rechazada</span><span class="cat">Del catálogo HPUM</span>
      <span class="estado-n" id="f-n" role="status">${plural(m.kpis.pendientes, 'relación por revisar', 'relaciones por revisar')} en esta ficha</span></div>
    ${vacio}${secciones}${segundo}${catalogo}
    <p class="review-disclaimer">Es una foto de la KB en el momento de la descarga: no se actualiza sola. Lo pendiente y las hipótesis todavía no están validados; para decidir, vuelve a la web de la KB. Las citas son literales del documento que se indica.</p>
  </div>`;
}

export const CSS = `
:root{--rv-ink:#24304a;--rv-ink2:#51637c;--rv-muted:#56647d;--rv-purple:#7351c4;--rv-purple-ink:#5947ab;--rv-purple-soft:#f1eefe;--rv-purple-line:#e2d9fa;--rv-border:#e3e8f1;--rv-line2:#eef1f7;--rv-bg:#f8faff;--rv-green:#147d61;--rv-amber:#8a5a12;--rv-blue:#3f6a9e;--rv-red:#a8281f}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:#f6f8fc;color:var(--rv-ink);font:14px/1.5 Inter,'Segoe UI',system-ui,Arial,sans-serif;font-variant-numeric:tabular-nums}
::selection{background:var(--rv-purple-soft);color:var(--rv-purple-ink)}
:focus-visible{outline:2px solid var(--rv-purple);outline-offset:2px;border-radius:4px}
a{color:var(--rv-purple-ink);text-underline-offset:3px}
.page{max-width:1240px;margin:auto;padding:32px 28px 48px}
.hero{margin:0 0 20px}.hero-cab{display:flex;align-items:center;gap:14px}.hero h1{font-size:30px;line-height:1.15;letter-spacing:-.025em;margin:0;text-wrap:balance}
.hero-tipo{margin:3px 0 0;color:var(--rv-purple-ink);font-weight:600;font-size:13.5px}.hero>p{color:var(--rv-muted);margin:12px 0 0;max-width:75ch}
.review-app{background:var(--rv-bg);border:1px solid var(--rv-border);padding:20px;border-radius:14px}
.ficha{background:#fff;border:1px solid var(--rv-border);border-radius:12px;padding:16px 18px;margin:0 0 16px;display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:8px 28px}
.ficha dl{margin:0;display:grid;gap:8px}.ficha dl>div{display:grid;grid-template-columns:150px minmax(0,1fr);gap:10px}.ficha dt{color:var(--rv-muted);font-size:12.5px}.ficha dd{margin:0;font-size:13px}
.descs p{margin:0 0 8px;font-size:13px;color:var(--rv-ink2);max-width:70ch}.descs .src{display:block;margin:2px 0 0}
.review-tools{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin:0 0 16px}.review-tools input,.review-tools select{background:#fff;color:var(--rv-ink);border:1px solid #d8dfec;border-radius:9px;padding:9px 12px;font:inherit;min-width:150px}
.review-tools input{flex:1;min-width:240px}.review-tools input::placeholder{color:#66738b}
.review-tools button{background:var(--rv-purple-soft);color:var(--rv-purple-ink);border:1px solid var(--rv-purple-line);border-radius:8px;padding:9px 13px;font:inherit;font-weight:500;cursor:pointer}.review-tools button:hover{background:#e8e2fc}
.review-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:0 0 12px}.review-kpi{border:1px solid var(--rv-border);border-radius:11px;background:#fff;padding:12px 14px}.review-kpi b{font-size:22px;display:block;line-height:1.2}.review-kpi small{font-size:12px;color:var(--rv-muted)}
.review-legend{display:flex;flex-wrap:wrap;align-items:center;gap:6px 16px;color:var(--rv-muted);font-size:12px;margin:0 0 14px}.review-legend span:not(.estado-n):before{content:'';display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:1px}
.review-legend .ok:before{background:#36a785}.review-legend .doubt:before{background:#dc9b43}.review-legend .pending:before{background:#80a6d7}.review-legend .rej:before{background:#d06a62}.review-legend .cat:before{background:#a9a6c7}
.estado-n{margin-left:auto;font-weight:600;color:var(--rv-ink2)}
.review-scope{border:1px solid var(--rv-border);background:#fff;border-radius:12px;margin:10px 0;overflow:hidden}
.review-scope>summary,.review-family>summary,.review-type>summary{list-style:none;cursor:pointer}
.review-scope>summary::-webkit-details-marker,.review-family>summary::-webkit-details-marker,.review-type>summary::-webkit-details-marker{display:none}
.review-scope>summary{padding:15px 16px;display:flex;gap:14px;align-items:center;justify-content:space-between}.review-scope>summary>span:first-child{display:grid;gap:2px;min-width:0}
.review-scope>summary strong{font-size:17px;letter-spacing:-.01em}.caption{font-size:12px;color:var(--rv-muted);line-height:1.45;max-width:80ch}
.review-scope[open]>summary{background:#f4f1fd;border-bottom:1px solid #e5ddf8}.review-scope>summary .meta{color:#56647d;font-size:12px;white-space:nowrap}
.review-scope>summary:hover{background:#faf8ff}.review-scope-body{padding:12px 16px 18px}
.review-family{border:1px solid #e5e9f2;border-radius:10px;overflow:hidden;margin:10px 0}.review-family>summary{background:#fafbfe;padding:11px 14px;display:flex;justify-content:space-between;align-items:center;gap:10px}
.review-family>summary strong{font-size:14px}.review-family>summary small{color:var(--rv-muted);white-space:nowrap}.review-family[open]>summary{background:#f4f1fd}.review-family-body{padding:8px 12px 12px}
.via{display:flex;align-items:center;gap:10px;font-size:12.5px;color:var(--rv-muted);min-width:0}
.review-type{margin:8px 0;border:1px solid #edf0f6;border-radius:9px;overflow:hidden;background:#fff}.review-type>summary{display:flex;align-items:center;justify-content:space-between;padding:9px 13px;gap:10px}
.review-type>summary b{font-size:13px}.review-num{font-weight:800;color:#6a48b3}.review-type[open]>summary{background:#f9f7ff}
.flujos{display:grid;gap:8px;padding:8px 10px 10px}.review-family-body.flujos{padding:8px 12px 12px}
.flujo{padding:10px 12px;border:1px solid var(--rv-line2);border-radius:10px;background:var(--rv-bg);display:grid;gap:7px}
.fl-linea{display:flex;align-items:center;flex-wrap:wrap;row-gap:6px;min-width:0}
.nd{display:inline-flex;align-items:center;gap:8px;max-width:44%;padding:6px 10px;border:1px solid var(--rv-border);border-radius:10px;background:#fff;color:var(--rv-ink);text-decoration:none}
a.nd:hover{border-color:var(--rv-purple);box-shadow:0 1px 6px rgba(89,71,171,.16)}.nd.yo{border-color:var(--rv-purple);background:var(--rv-purple-soft)}
.nd-t{display:grid;min-width:0}.nd-t b{font-size:13px;font-weight:600;line-height:1.3}.nd-t small{font-size:12px;color:var(--rv-muted);line-height:1.3}
.nd-dot{flex:none;width:11px;height:11px;border-radius:50%;background:#898781}.nd-dot.grande{width:18px;height:18px}
.g-app{background:#2a78d6}.g-comp{background:#eb6834}.g-cap{background:#1baf7a}.g-otra{background:#898781}
.g-hpum{background:transparent;border:2px solid #52514e;border-radius:2px;transform:rotate(45deg);width:9px;height:9px}.nd-dot.grande.g-hpum{width:14px;height:14px}
.g-amb{background:transparent;border:2px solid var(--rv-ink)}.g-doc{border-radius:2px;background:#52514e}.g-sin{background:transparent;border:2px dashed #898781}
.fl-rel{flex:1;min-width:120px;display:flex;align-items:center;padding:0 2px}.fl-l{flex:1;height:2px;background:#b9aee0}.fl-punta{position:relative}
.fl-punta::after{content:"";position:absolute;right:-1px;top:-4px;border:5px solid transparent;border-left:7px solid #b9aee0;border-right:0}
.fl-tag{flex:none;padding:3px 10px;border-radius:999px;background:#fff;border:1.5px solid var(--rv-purple);color:var(--rv-purple-ink);font-size:12px;font-weight:700;letter-spacing:.02em;white-space:nowrap}
.fl-pie{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center}
.fl-citas{margin:0;padding:0 0 0 2px;list-style:none;display:grid;gap:5px}.fl-citas li{font-size:12.5px;color:var(--rv-ink2);max-width:95ch}
q{quotes:"«" "»"}.fl-citas q,.cita{font-style:normal;color:var(--rv-ink)}.src{display:inline-block;margin-left:8px;font-size:12px;color:var(--rv-muted)}.just{display:block;color:var(--rv-ink2)}.fl-citas q+.just{margin-top:2px}.fl-citas .src:first-child,.just+.src{margin-left:0}
.flujo.doubt{background:#fffaf0;border-color:#f1e2c2}.flujo.rej{opacity:.7}
.review-state{display:inline-block;font-weight:700;border-radius:16px;font-size:11px;padding:3px 9px;background:#e2f6ee;color:var(--rv-green)}
.review-state.pending{background:#e9f1fc;color:var(--rv-blue)}.review-state.doubt{background:#fff0d2;color:var(--rv-amber)}.review-state.rej{background:#fde8e6;color:var(--rv-red)}
.review-state.corr{background:#e6effb;color:var(--rv-blue)}.review-state.cat{background:#eeedf6;color:#56537a}
.review-items{padding:8px 12px 12px;display:grid;gap:8px}
.review-item{padding:10px 12px;border:1px solid #cdeadf;border-radius:8px;background:#f6fcf9;display:grid;gap:4px;scroll-margin-top:16px}
.review-item.pending{border-color:#dbe6f5;background:#f7faff}.review-item.doubt{border-color:#f1e2c2;background:#fffaf0}.review-item.rej{border-color:#f3d4d0;background:#fff8f7}.review-item.corr{border-color:#d6e3f5;background:#f7faff}
.review-item:target{box-shadow:0 0 0 2px #ad8bde}.it-cab{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.review-item strong{font-size:13px}
.review-item .desc{font-size:12.5px;color:#51637c}.review-item .links{font-size:12px;color:#566983}.review-item .source{font-size:12px;color:var(--rv-muted)}.review-item .cita{font-size:12px}
.review-empty{font-size:13px;color:#56647d;padding:12px}
.review-disclaimer{padding:11px 13px;background:#f0f5fb;border:1px solid #dfeaf6;border-radius:8px;font-size:12px;color:#4b6789;margin:16px 0 0}
[hidden]{display:none!important}
@media(max-width:860px){.page{padding:20px 16px 32px}.hero h1{font-size:24px}.ficha{grid-template-columns:1fr}.ficha dl>div{grid-template-columns:120px minmax(0,1fr)}.review-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}
  .review-app{padding:12px}.review-scope-body{padding:8px}.flujos{padding:6px}.review-family-body,.review-items{padding:6px}.nd{max-width:100%}.fl-rel{min-width:80px}.review-tools input{min-width:100%}.estado-n{margin-left:0}}
@media print{body{background:#fff}.page{padding:0;max-width:none}.review-tools{display:none}.review-app{border:0;padding:0;background:#fff}.review-scope,.review-type,.flujo,.review-item{break-inside:avoid}a.nd{color:inherit}}
`;

// Filtro en la propia descarga: sin dependencias, funciona sin conexión.
const SCRIPT = `(function(){var q=document.getElementById('f-q'),sec=document.getElementById('f-sec'),est=document.getElementById('f-est'),n=document.getElementById('f-n');
function aplicar(){var t=q.value.trim().toLowerCase(),s=sec.value,e=est.value,act=!!(t||e),vis=0;
document.querySelectorAll('[data-seccion]').forEach(function(sc){var on=!s||sc.dataset.seccion===s;sc.hidden=!on;if(!on)return;
sc.querySelectorAll('[data-q]').forEach(function(x){var ok=(!t||x.dataset.q.indexOf(t)>=0)&&(!e||x.dataset.estado===e||(e==='ok'&&x.dataset.estado==='corr'));x.hidden=!ok;if(ok)vis++;});
sc.querySelectorAll('details').forEach(function(d){var c=d.querySelectorAll('[data-q]:not([hidden])').length;d.hidden=!c&&d!==sc;if(act&&c)d.open=true;});
if(act)sc.open=sc.querySelectorAll('[data-q]:not([hidden])').length>0;});
if(act)n.textContent=vis+(vis===1?' elemento coincide':' elementos coinciden');else n.textContent=n.dataset.base;}
n.dataset.base=n.textContent;var tm;q.addEventListener('input',function(){clearTimeout(tm);tm=setTimeout(aplicar,150);});sec.onchange=aplicar;est.onchange=aplicar;
var ab=document.getElementById('f-abrir');ab.onclick=function(){var l=[].slice.call(document.querySelectorAll('details')),todo=l.every(function(d){return d.open;});l.forEach(function(d){d.open=!todo;});ab.textContent=todo?'Desplegar todo':'Plegar todo';};
document.getElementById('f-imp').onclick=function(){window.print();};window.addEventListener('beforeprint',function(){document.querySelectorAll('details').forEach(function(d){d.open=true;});});
document.querySelectorAll('a.nd[href^="#e-"]').forEach(function(a){a.addEventListener('click',function(){var x=document.getElementById(a.getAttribute('href').slice(1));if(!x)return;var p=x.parentElement;while(p){if(p.tagName==='DETAILS')p.open=true;p=p.parentElement;}});});})();`;

/** Documento HTML autónomo: el CSS y un filtro mínimo dentro; sin llamadas externas. */
export function documentoFicha(m) {
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">`
    + `<title>${esc(m.raiz.nombre)} · relaciones en la KB</title><style>${CSS}</style></head><body><main class="page">${htmlFicha(m)}</main><script>${SCRIPT}</script></body></html>`;
}

export const nombreFichero = (m) => `relaciones_${String(m.raiz.nombre).normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/[^A-Za-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 60) || 'elemento'}_${m.campana}.html`;
