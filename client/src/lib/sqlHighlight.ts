import { esc } from './format';

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
