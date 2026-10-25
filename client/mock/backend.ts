import { createHash, createHmac, timingSafeEqual } from 'node:crypto';
import type { IncomingMessage, ServerResponse } from 'node:http';
import type { Plugin } from 'vite';
import { EV, PH } from '../src/data/demo';
import { START_TG0341 } from '../src/lib/format';

// Dev-only stand-in for the identity provider and backend/: same routes, JSON shapes and
// role rules, so the client runs without the Docker stack. Vite loads it only when
// QAR_BACKEND_URL is unset; it is never part of a build. Flight values other than TG0341's
// Gold rows are placeholders, not decoded data.

// Roles as in bi/roles.json; the users are made up for local development.
const ROLES: Record<string, { label: string; trino_user: string; scope: string }> = {
  safety: { label: 'Safety', trino_user: 'safety_analyst', scope: 'All flights · recording and source file masked' },
  operations: { label: 'Operations', trino_user: 'operations_analyst', scope: 'Flights to or from VTBS · tail masked · touchdown g hidden' },
  engineering: { label: 'Engineering', trino_user: 'engineering_analyst', scope: 'Aircraft HS-THJ only · flight number and route masked' },
};
const USERS: Record<string, string | null> = { 'safety.demo': 'safety', 'ops.demo': 'operations', 'eng.demo': 'engineering', 'norole.demo': null };
const DASHBOARDS: Record<string, number> = { safety: 14, operations: 12, engineering: 13 };
const NO_ROLE = 'Your account has no dashboard role. Ask an administrator to assign safety, operations or engineering.';
const SECRET = 'dev-only-metabase-embedding-secret';
const COOKIE = 'qar_mock_user';
const EMBED_PATH = '/mock-metabase/embed/dashboard/';

interface Flight {
  flight_id: string; flight_date: string; flight_no: string; aircraft_type: string; tail: string; origin: string; destination: string;
  start_time: string; duration_s: number; decoder_version: string; recording: string;
}
const real = (id: string, date: string, no: string, tail: string, org: string, dst: string, start: string, dur: number, rec: string): Flight =>
  ({ flight_id: id, flight_date: date, flight_no: no, aircraft_type: 'A350', tail, origin: org, destination: dst, start_time: start, duration_s: dur, decoder_version: '2.1.0', recording: rec });
const synthetic = (n: number, type: string, org: string, dst: string, dur: number): Flight => {
  const date = `2022-09-${21 + n}`;
  return { flight_id: `DEMO-${type}-${n}_${date.replace(/-/g, '')}T060000_F01`, flight_date: date, flight_no: `DEMO00${n}`, aircraft_type: type,
    tail: `DEMO-${type}${n}`, origin: org, destination: dst, start_time: `${date}T06:00:00+00:00`, duration_s: dur,
    decoder_version: 'synthetic-demo', recording: `synthetic_demo_00${n}` };
};
const FLIGHTS: Flight[] = [
  real('HS-THJ_20220322T111310_F01', '2022-03-22', 'TG0341', 'HS-THJ', 'VTBS', 'OPKC', '2022-03-22T11:13:10+00:00', 22020, 'A350_HS-THJ_20220322_TG0341_VTBS-OPKC'),
  real('HS-THE_20220826T142818_F01', '2022-08-26', 'TG0000', 'HS-THE', 'VTBS', 'RKSI', '2022-08-26T14:28:18+00:00', 24308, 'A350_HS-THE_20220826_TG0000_VTBS-RKSI'),
  real('HS-THJ_20220921T003554_F01', '2022-09-21', 'TG0000', 'HS-THJ', 'ESSA', 'VTBS', '2022-09-21T00:35:54+00:00', 37096, 'A350_HS-THJ_20220921_TG0000_ESSA-VTBS'),
  synthetic(1, 'A350', 'VTBS', 'RJAA', 21400), synthetic(2, 'A350', 'RKSI', 'VTBS', 20100), synthetic(3, 'A350', 'VTBS', 'WSSS', 8700),
  synthetic(4, 'B777', 'VHHH', 'VTBS', 10200), synthetic(5, 'B777', 'EGLL', 'ESSA', 9600),
];
const TG0341 = FLIGHTS[0].flight_id;

// opa/trino.rego, reduced to what these endpoints touch.
const visible = (role: string, f: Flight) =>
  role === 'operations' ? f.origin === 'VTBS' || f.destination === 'VTBS' : role === 'engineering' ? f.tail === 'HS-THJ' : true;
const pseudonym = (id: string) => createHash('sha256').update(id).digest('hex');
function present(role: string, f: Flight) {
  const row = { ...f, is_synthetic: f.decoder_version.startsWith('synthetic-') };
  if (role === 'operations') Object.assign(row, { flight_id: pseudonym(f.flight_id), tail: 'REDACTED', recording: 'REDACTED' });
  if (role === 'engineering') Object.assign(row, { flight_no: 'REDACTED', origin: 'REDACTED', destination: 'REDACTED' });
  if (role === 'safety') row.recording = 'REDACTED';
  return row;
}

function detail(role: string, id: string) {
  const f = FLIGHTS.find(x => visible(role, x) && present(role, x).flight_id === id);
  if (!f) return null;
  const { recording, ...row } = present(role, f);
  const gold = f.flight_id === TG0341;
  // OPA denies touchdown_peak_g to Operations, so the backend leaves it out.
  const summary = gold ? { airborne_min: 268.3, cruise_min: 209.5, max_alt_ft: 43036, built_at: null,
    ...(role === 'operations' ? {} : { touchdown_peak_g: 1.277 }) } : null;
  return {
    flight: { ...row, recording, fap: null, dec_takeoff_s: gold ? 5154 : null, dec_touchdown_s: gold ? 21251 : null },
    summary,
    phases: gold ? PH.map((p, i) => ({ phase_order: i + 1, phase: p.k, start_s: p.s, end_s: p.e, duration_s: p.e - p.s + 1, detector_ver: 'mock' })) : [],
    events: gold ? EV.map(e => ({ event: e.k, t_offset_s: e.t, ts: new Date(START_TG0341 + e.t * 1000).toISOString(), value: null, unit: null, detector_ver: 'mock' })) : [],
    query_identity: ROLES[role].trino_user,
  };
}

interface EmbedClaims { resource: { dashboard: number }; params: Record<string, string>; iat: number; exp: number }
const hmac = (data: string) => createHmac('sha256', SECRET).update(data).digest();
// HS256, the only algorithm Metabase static embedding accepts.
function sign(claims: EmbedClaims) {
  const head = Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url');
  const body = Buffer.from(JSON.stringify(claims)).toString('base64url');
  return `${head}.${body}.${hmac(`${head}.${body}`).toString('base64url')}`;
}
function verify(token: string): EmbedClaims | null {
  const [head, body, sig] = token.split('.');
  if (!head || !body || !sig) return null;
  const want = hmac(`${head}.${body}`), got = Buffer.from(sig, 'base64url');
  if (got.length !== want.length || !timingSafeEqual(got, want)) return null;
  return JSON.parse(Buffer.from(body, 'base64url').toString()) as EmbedClaims;
}
function embedUrl(dashboard: number) {
  const now = Math.floor(Date.now() / 1000);
  return EMBED_PATH + sign({ resource: { dashboard }, params: {}, iat: now, exp: now + 600 }) + '#bordered=false&titled=false';
}

const esc = (s: string) => s.replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
function currentUser(req: IncomingMessage): string | null {
  const m = new RegExp(`(?:^|;\\s*)${COOKIE}=([^;]+)`).exec(req.headers.cookie ?? '');
  return m && Object.hasOwn(USERS, m[1]) ? m[1] : null;
}
function send(res: ServerResponse, status: number, body: string, type = 'text/html; charset=utf-8', headers: Record<string, string> = {}) {
  res.writeHead(status, { 'Content-Type': type, 'Cache-Control': 'no-store', ...headers });
  res.end(body);
}
const json = (res: ServerResponse, status: number, data: unknown) => send(res, status, JSON.stringify(data), 'application/json');
const redirect = (res: ServerResponse, location: string, cookie?: string) =>
  send(res, 302, '', 'text/plain', { Location: location, ...(cookie ? { 'Set-Cookie': cookie } : {}) });

const PAGE_CSS = `
:root{--bg:#F6F3FA;--surface:#fff;--line:#E3DCEE;--ink:#22143A;--ink-2:#5A4C70;--accent:#5B2C91;--soft:#EEE6F7;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#150B26;--surface:#1F1236;--line:#3A2960;--ink:#EEE8F7;--ink-2:#BDB0D6;--accent:#CDB4F2;--soft:#34205C;color-scheme:dark}}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 Inter,system-ui,sans-serif;padding:32px 16px}
main{max-width:560px;margin:0 auto;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:24px}
h1{font-size:20px;margin:0 0 6px}p{color:var(--ink-2);margin:0 0 16px}
a.user{display:block;border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin-top:10px;color:inherit;text-decoration:none}
a.user:hover{border-color:var(--accent);background:var(--soft)}small{color:var(--ink-2)}
dl{display:grid;grid-template-columns:auto 1fr;gap:6px 16px;font:12.5px/1.6 ui-monospace,Menlo,monospace;margin:0}dt{color:var(--ink-2)}dd{margin:0;word-break:break-all}`;

const loginPage = () => `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mock sign-in</title>
<style>${PAGE_CSS}</style><main><h1>Mock identity provider</h1><p>Dev only. The real backend redirects to Google here; pick who to sign in as.</p>
${Object.entries(USERS).map(([u, role]) => `<a class="user" href="/login/as?u=${u}"><b>${u}</b><br><small>${role ? `role: ${role}` : 'no role'}</small></a>`).join('')}</main>`;

function dashboardPage(claims: EmbedClaims) {
  const role = Object.keys(DASHBOARDS).find(r => DASHBOARDS[r] === claims.resource.dashboard) ?? 'unknown';
  return `<!doctype html><meta charset="utf-8"><title>Mock Metabase</title><style>${PAGE_CSS}main{max-width:none}</style>
<main><h1>Mock Metabase · dashboard ${claims.resource.dashboard}</h1>
<p>Real Metabase renders the role's Gold cards here. Each card runs on the connection below, so Trino and OPA decide what it returns.</p>
<dl><dt>role</dt><dd>${esc(role)}</dd><dt>connection</dt><dd>${esc(ROLES[role]?.trino_user ?? '?')} (HTTPS + password)</dd>
<dt>link expires</dt><dd>${new Date(claims.exp * 1000).toISOString()}</dd><dt>token claims</dt><dd>${esc(JSON.stringify(claims))}</dd></dl></main>`;
}

export function mockBackend(): Plugin {
  return {
    name: 'qar-mock-backend',
    apply: 'serve',
    configureServer(server) {
      const log = (msg: string) => server.config.logger.info(`[mock backend] ${msg}`, { timestamp: true });
      server.middlewares.use((req, res, next) => {
        const url = new URL(req.url ?? '/', 'http://localhost');
        const path = url.pathname;
        if (path === '/login') return send(res, 200, loginPage());
        if (path === '/login/as') {
          const u = url.searchParams.get('u') ?? '';
          if (!Object.hasOwn(USERS, u)) return send(res, 400, 'Unknown mock user', 'text/plain');
          return redirect(res, '/', `${COOKIE}=${u}; HttpOnly; SameSite=Lax; Path=/`);
        }
        if (path === '/logout') return redirect(res, '/', `${COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0`);
        if (path.startsWith(EMBED_PATH)) {
          // Metabase's own wording for these two failures.
          const claims = verify(path.slice(EMBED_PATH.length));
          if (!claims) return send(res, 400, 'Message seems corrupt or manipulated.', 'text/plain');
          if (claims.exp * 1000 < Date.now()) return send(res, 400, 'Token is expired.', 'text/plain');
          return send(res, 200, dashboardPage(claims));
        }
        if (!path.startsWith('/api/') && path !== '/metabase') return next();

        const user = currentUser(req);
        if (!user) return json(res, 401, { error: 'Sign in again.' });
        const role = USERS[user];
        if (path === '/api/me') {
          const r = role ? ROLES[role] : null;
          return json(res, 200, { user, name: '', role, role_label: r?.label ?? null, scope: r?.scope ?? null, trino_user: r?.trino_user ?? null });
        }
        if (!role) return json(res, 403, { error: NO_ROLE });
        if (path === '/api/flights') {
          const rows = FLIGHTS.filter(f => visible(role, f)).sort((a, b) => b.flight_date.localeCompare(a.flight_date))
            .map(f => { const { recording: _r, ...row } = present(role, f); return row; });
          return json(res, 200, { flights: rows, total: rows.length, truncated: false, query_identity: ROLES[role].trino_user, source: 'iceberg.silver.flights' });
        }
        if (path === '/api/flights/detail') {
          const d = detail(role, url.searchParams.get('id') ?? '');
          return d ? json(res, 200, d) : json(res, 404, { error: 'Flight not found or not visible to this identity.' });
        }
        if (path === '/api/bi/embed' || path === '/metabase') {
          const dashboard = DASHBOARDS[role];
          log(`${user} role=${role} dashboard=${dashboard}`);
          if (path === '/metabase') return redirect(res, embedUrl(dashboard));
          return json(res, 200, { embed_url: embedUrl(dashboard), refresh_after_seconds: 480, dashboard_id: dashboard, role,
            role_label: ROLES[role].label, query_identity: ROLES[role].trino_user });
        }
        return json(res, 404, { error: 'Not found' });
      });
    },
  };
}
