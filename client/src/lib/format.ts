export const pad = (n: number) => String(n).padStart(2, '0');

export function hms(s: number) {
  s = Math.max(0, Math.round(s));
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
}

export const clockUtc = (iso: string) => { const d = new Date(iso); return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`; };

export const n0 = (v: number) => Number(v).toLocaleString('en-US');

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
export function dLong(iso: string) { const [y, m, d] = iso.split('-'); return `${+d} ${MONTHS[+m - 1]} ${y}`; }

const ENTITY: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (s: unknown) => String(s).replace(/[&<>"']/g, c => ENTITY[c]);
