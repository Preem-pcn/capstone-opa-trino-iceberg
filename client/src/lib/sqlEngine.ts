import { FIX, TABLES } from '../data/demo';
import { esc } from './format';

/* =====================================================================
   SQL ENGINE (prototype) + OPA-style policy fixtures
   Like v3, the browser simulates the policy for the OPA fixture tables only;
   every other table answers as written. Real enforcement is Trino + OPA, which
   Flight Explorer and Gold Reports go through.
   ===================================================================== */
export const MASK = Symbol('REDACTED');
export type Cell = string | number | typeof MASK;
export type Row = Record<string, Cell>;

const fixOf = (r: Row) => FIX.find(f => f.flight_id === r.flight_id);

export interface Policy { allow: boolean; mask: string[]; deny: string[]; filter: ((r: Row) => boolean) | null; pseudo: boolean }

export function policy(id: string, table: string): Policy {
  const open: Policy = { allow: true, mask: [], deny: [], filter: null, pseudo: false };
  if (!table.includes('.opa_demo_')) return open;
  switch (id) {
    case 'safety_analyst': return { ...open, mask: ['recording', 'source_file'] };
    case 'operations_analyst': return {
      ...open, mask: ['tail', 'recording', 'source_file'], deny: ['touchdown_peak_g'], pseudo: true,
      filter: r => { const f = fixOf(r); return f?.origin === 'VTBS' || f?.destination === 'VTBS'; },
    };
    case 'engineering_analyst': return { ...open, mask: ['flight_no', 'origin', 'destination'], filter: r => fixOf(r)?.tail === 'HS-THJ' };
    case 'blocked_user': return { ...open, allow: false };
    default: return open;
  }
}

export function applyPolicy(id: string, table: string, rows: Record<string, string | number>[]) {
  const p = policy(id, table);
  const out = rows.filter(r => !p.filter || p.filter(r)).map(r => {
    const o: Row = { ...r };
    p.mask.forEach(c => { if (c in o) o[c] = MASK; });
    if (p.pseudo && o.flight_id) o.flight_id = fixOf(r)?.hash ?? 'sha256:unavailable';
    return o;
  });
  return { p, rows: out };
}

export class SqlError extends Error {
  constructor(message: string, readonly kind: 'err' | 'den' = 'err') { super(message); }
}

function resolveTable(name: string) {
  const n = name.toLowerCase();
  for (const c of [n, 'iceberg.' + n]) if (TABLES[c]) return c;
  throw new SqlError(`Table '${name}' does not exist`);
}

interface Cond { c: string; op: string; a: string | number; b?: string | number }
const lit = (x: string) => (x.startsWith("'") ? x.slice(1, -1) : Number(x));

function parseWhere(src: string, cols: string[]): Cond[] {
  const conds: Cond[] = [];
  let s = src.trim();
  while (s.length) {
    let m: RegExpMatchArray | null;
    if ((m = s.match(/^(\w+)\s+between\s+('[^']*'|-?[\d.]+)\s+and\s+('[^']*'|-?[\d.]+)/i))) conds.push({ c: m[1].toLowerCase(), op: 'between', a: lit(m[2]), b: lit(m[3]) });
    else if ((m = s.match(/^(\w+)\s+like\s+('[^']*')/i))) conds.push({ c: m[1].toLowerCase(), op: 'like', a: lit(m[2]) });
    else if ((m = s.match(/^(\w+)\s*(=|!=|<>|>=|<=|>|<)\s*('[^']*'|-?[\d.]+)/i))) conds.push({ c: m[1].toLowerCase(), op: m[2], a: lit(m[3]) });
    else throw new SqlError(`Prototype engine could not parse WHERE near "${s.slice(0, 32)}". Use AND-joined comparisons, BETWEEN or LIKE.`);
    const last = conds[conds.length - 1].c;
    if (!cols.includes(last)) throw new SqlError(`Column '${last}' cannot be resolved`);
    s = s.slice(m[0].length).trim();
    if (!s) break;
    const a = s.match(/^and\s+/i);
    if (!a) {
      if (/^or\b/i.test(s)) throw new SqlError('OR is not supported by the prototype engine; use AND-joined conditions.');
      throw new SqlError(`Unexpected token near "${s.slice(0, 24)}"`);
    }
    s = s.slice(a[0].length);
  }
  return conds;
}

function test(r: Row, c: Cond) {
  const v = r[c.c];
  if (v === MASK) return false;   // masked values never match a predicate
  // Loose JS comparison, as in the prototype ('12000' = 12000).
  const x = v as number, a = c.a as number, b = c.b as number;
  switch (c.op) {
    case '=': return x == a;
    case '!=': case '<>': return x != a;
    case '>': return x > a;
    case '<': return x < a;
    case '>=': return x >= a;
    case '<=': return x <= a;
    case 'between': return x >= a && x <= b;
    case 'like': return new RegExp('^' + String(c.a).replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/%/g, '.*').replace(/_/g, '.') + '$', 'i').test(String(v));
  }
  return false;
}

export interface QueryResult { table: string; cols: string[]; rows: Cell[][]; masked: string[]; pseudo: boolean }

export function runQuery(text: string, identity: string): QueryResult {
  const clean = text.replace(/--[^\n]*/g, ' ').replace(/\s+/g, ' ').trim().replace(/;\s*$/, '');
  if (!clean) throw new SqlError('Query is empty. Write a SELECT or pick a saved example.');
  if (/;/.test(clean)) throw new SqlError('Run one statement at a time.');
  if (!/^select\b/i.test(clean)) throw new SqlError('Only read-only SELECT statements are allowed in this workspace.');
  const m = clean.match(/^select\s+(.+?)\s+from\s+([\w.]+)(?:\s+where\s+(.+?))?(?:\s+order\s+by\s+(\w+)(?:\s+(asc|desc))?)?(?:\s+limit\s+(\d+))?$/i);
  if (!m) throw new SqlError('Prototype engine supports SELECT … FROM … [WHERE …] [ORDER BY col] [LIMIT n].');
  const tname = resolveTable(m[2]), T = TABLES[tname];
  const sel = m[1].trim() === '*' ? T.cols.slice() : m[1].split(',').map(s => s.trim().toLowerCase());
  sel.forEach(c => { if (!T.cols.includes(c)) throw new SqlError(`Column '${c}' cannot be resolved`); });
  const conds = m[3] ? parseWhere(m[3], T.cols) : [];
  const ap = policy(identity, tname);
  if (!ap.allow) throw new SqlError(`${identity} is prohibited from querying ${tname.replace('iceberg.', '')}`, 'den');
  const deniedCol = [...sel, ...conds.map(c => c.c)].find(c => ap.deny.includes(c));
  if (deniedCol) throw new SqlError(`${identity} cannot query ${deniedCol}`, 'den');
  let { rows } = applyPolicy(identity, tname, T.rows);
  rows = rows.filter(r => conds.every(c => test(r, c)));
  if (m[4]) {
    const oc = m[4].toLowerCase();
    if (!T.cols.includes(oc)) throw new SqlError(`Column '${oc}' cannot be resolved`);
    const dir = (m[5] || 'asc').toLowerCase() === 'desc' ? -1 : 1;
    rows = rows.slice().sort((a, b) => { const x = a[oc] as number, y = b[oc] as number; return (x > y ? 1 : x < y ? -1 : 0) * dir; });
  }
  if (m[6]) rows = rows.slice(0, +m[6]);
  return { table: tname, cols: sel, rows: rows.map(r => sel.map(c => r[c])), masked: ap.mask.filter(c => sel.includes(c)), pseudo: ap.pseudo && sel.includes('flight_id') };
}

// Returns escaped HTML for the editor's highlight layer.
export function highlight(src: string) {
  const re = /(--[^\n]*)|('(?:[^'\n])*'?)|(\b\d+(?:\.\d+)?\b)|(\b(?:SELECT|FROM|WHERE|AND|OR|ORDER|BY|LIMIT|BETWEEN|AS|ASC|DESC|LIKE|IN|NOT|NULL|IS|GROUP|HAVING|JOIN|ON|COUNT|DISTINCT)\b)/gi;
  let out = '', last = 0, m: RegExpExecArray | null;
  while ((m = re.exec(src))) {
    out += esc(src.slice(last, m.index));
    const cls = m[1] ? 'hl-com' : m[2] ? 'hl-str' : m[3] ? 'hl-num' : 'hl-kw';
    out += `<span class="${cls}">${esc(m[0])}</span>`;
    last = re.lastIndex;
  }
  return out + esc(src.slice(last)) + '\n';
}
