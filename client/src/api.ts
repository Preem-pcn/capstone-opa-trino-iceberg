// Contract with the backend (backend/app/main.py).

export interface Me {
  user: string;
  name: string;
  // One role resolved by the backend from the verified identity and configured role source.
  role: string | null;
  role_label: string | null;
  scope: string | null;
  trino_user: string | null;
}

// A Metabase static-embed link the backend signed for the session's role dashboard.
export interface EmbedInfo {
  embed_url: string;
  refresh_after_seconds: number;
  dashboard_id: number;
  role: string;
  role_label: string;
  query_identity: string;
}

// Silver flight metadata as the role's Trino user sees it (OPA may mask columns to 'REDACTED').
export interface FlightRow {
  flight_id: string;
  flight_date: string;
  flight_no: string | null;
  aircraft_type: string | null;
  tail: string | null;
  origin: string | null;
  destination: string | null;
  start_time: string | null;
  duration_s: number | null;
  decoder_version: string | null;
  is_synthetic: boolean;
}

export interface FlightList {
  flights: FlightRow[];
  total: number;
  truncated: boolean;
  query_identity: string;
  source: string;
}

export interface FlightDetail {
  flight: FlightRow & { recording: string | null; fap: string | null; dec_takeoff_s: number | null; dec_touchdown_s: number | null };
  // Only the summary columns this role may read; OPA hides touchdown_peak_g from Operations.
  summary: Partial<Record<'airborne_min' | 'cruise_min' | 'max_alt_ft' | 'touchdown_peak_g', number | null> & { built_at: string | null }> | null;
  phases: { phase_order: number; phase: string; start_s: number; end_s: number; duration_s: number; detector_ver: string | null }[];
  events: { event: string; t_offset_s: number; ts: string | null; value: number | null; unit: string | null; detector_ver: string | null }[];
  query_identity: string;
}

export interface FlightSensors {
  seconds: number;
  series: Record<'alt' | 'ias' | 'gs' | 'heading' | 'pitch' | 'roll' | 'vrtg' | 'vrtg_max', (number | null)[]>;
  query_identity: string;
  source: Record<string, string>;
}

export type SqlValue = null | boolean | number | string | SqlValue[] | { [key: string]: SqlValue };
export interface SqlColumn { name: string; type: string }
export interface SqlResult {
  columns: SqlColumn[];
  rows: SqlValue[][];
  truncated: boolean;
  ms: number;
  query_identity: string;
}
export interface CatalogResult {
  tables: Record<string, SqlColumn[]>;
  query_identity: string;
}

export class ApiError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}

async function requestJson<T>(path: string, options: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { ...options, credentials: 'same-origin', cache: 'no-store',
      headers: { Accept: 'application/json', ...options.headers } });
  } catch (error) {
    if (options.signal?.aborted) throw error;
    throw new ApiError(0, 'The QAR backend is not reachable.');
  }
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { error?: string } | null;
    throw new ApiError(res.status, body?.error ?? `The backend answered ${res.status}.`);
  }
  return res.json() as Promise<T>;
}

export const fetchMe = () => requestJson<Me>('/api/me');
export const fetchEmbed = () => requestJson<EmbedInfo>('/api/bi/embed');
export const fetchFlights = () => requestJson<FlightList>('/api/flights');
export const fetchFlightDetail = (id: string) => requestJson<FlightDetail>(`/api/flights/detail?id=${encodeURIComponent(id)}`);
export const fetchFlightSensors = (id: string, signal?: AbortSignal) => requestJson<FlightSensors>(`/api/flights/sensors?id=${encodeURIComponent(id)}`, { signal });
export const fetchCatalog = (signal?: AbortSignal) => requestJson<CatalogResult>('/api/catalog', { signal });
// Only SQL is sent: the backend derives the Trino account from the authenticated session.
export const executeSql = (sql: string, signal?: AbortSignal) => requestJson<SqlResult>('/api/sql', {
  method: 'POST', signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sql }),
});

// A full-page navigation: the backend owns the OIDC redirects and the session cookie,
// so the IdP tokens never reach this JavaScript. Sign-out is a plain link to /logout.
// `next` brings the person back to this page, on this origin (the backend allows its own
// site and the dev server only).
export function signIn() { location.assign(`/login?next=${encodeURIComponent(location.href)}`); }
