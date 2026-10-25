export const START_TG0341 = Date.UTC(2022, 2, 22, 11, 13, 10);   // TG0341 recording start

export const pad = (n: number) => String(n).padStart(2, '0');

export function hms(s: number) {
  s = Math.max(0, Math.round(s));
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
}

// Offset into the TG0341 recording -> UTC wall time.
export function utc(off: number, full = false) {
  const d = new Date(START_TG0341 + Math.round(off) * 1000);
  const t = `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
  return full ? `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${t} UTC` : t;
}

export const clockUtc = (iso: string) => { const d = new Date(iso); return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`; };

export const n0 = (v: number) => Number(v).toLocaleString('en-US');

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
export function dLong(iso: string) { const [y, m, d] = iso.split('-'); return `${+d} ${MONTHS[+m - 1]} ${y}`; }

const ENTITY: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (s: unknown) => String(s).replace(/[&<>"']/g, c => ENTITY[c]);
