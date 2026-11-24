// Genera con kbweb/web/ficha.js (lo que descarga la web) el HTML de varias fichas, para compararlo con el port de Python.
// Uso: node ficha_node.mjs <ruta ficha.js> <servida.json> <estado.json> <ids separados por comas> <saltos>
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const [, , fichaJs, servida, estado, ids, saltos] = process.argv;
const F = await import(pathToFileURL(fichaJs).href);
const D = JSON.parse(readFileSync(servida, 'utf8'));
const E = JSON.parse(readFileSync(estado, 'utf8'));
const out = {};
for (const id of ids.split(',')) {
  const m = F.construirFicha(D, E, id, { saltos: Number(saltos), huella: 'h0' });
  m.fecha = new Date(2026, 10, 19, 9, 5);
  out[id] = { html: F.htmlFicha(m), nombre: F.nombreFichero(m), kpis: m.kpis };
}
process.stdout.write(JSON.stringify(out));
