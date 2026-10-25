import { createContext, useCallback, useContext, useEffect, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react';
import { useNavigate } from 'react-router-dom';
import { ApiError, executeSql, fetchFlightDetail, fetchFlights, type FlightDetail, type FlightList, type SqlResult } from './api';
import { SQL_EXAMPLES } from './lib/sqlExamples';
import { useMe, useSession } from './session';

export interface ExplorerFilters { q: string; from: string; to: string; type: string; org: string; dst: string; source: '' | 'recorded' | 'synthetic' }
export const NO_FILTERS: ExplorerFilters = { q: '', from: '', to: '', type: '', org: '', dst: '', source: '' };

export interface CockpitState { flight: string; t: number; speed: number }

export type Load<T> =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; data: T }
  | { status: 'error'; message: string };

export type SqlRun =
  | { status: 'idle' | 'run' | 'can' }
  | { status: 'ok'; result: SqlResult; ms: number; identity: string }
  | { status: 'err' | 'den'; msg: string; identity: string };
export interface HistoryItem { sql: string; status: SqlRun['status']; label: string }

interface AppState {
  explorer: ExplorerFilters;
  setFilters(patch: Partial<ExplorerFilters>): void;
  resetFilters(): void;
  page: number;
  setPage(page: number): void;

  // Live Silver/Gold data, queried by the backend as the role's Trino user.
  flights: Load<FlightList>;
  loadFlights(force?: boolean): void;
  details: Record<string, Load<FlightDetail>>;
  loadDetail(id: string): void;

  ck: CockpitState; setCk: Dispatch<SetStateAction<CockpitState>>;

  sqlText: string; setSqlText(text: string): void;
  sqlRun: SqlRun; history: HistoryItem[];
  runSql(text: string): void; cancelSql(): void; loadSql(text: string, run?: boolean): void; clearHistory(): void;
  tree: Set<string>; toggleTree(k: string): void;
  catq: string; setCatq(q: string): void;

  openFlight(id: string, tab?: string, phase?: string): void;
  openCockpit(patch?: Partial<CockpitState>): void;
}

const AppContext = createContext<AppState | null>(null);
const failure = (e: unknown) => (e instanceof Error ? e.message : 'Request failed.');

export function AppStateProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const me = useMe();
  const { expire } = useSession();
  const [explorer, setExplorer] = useState(NO_FILTERS);
  const [page, setPage] = useState(1);
  const setFilters = useCallback((patch: Partial<ExplorerFilters>) => { setExplorer(f => ({ ...f, ...patch })); setPage(1); }, []);
  const resetFilters = useCallback(() => { setExplorer(NO_FILTERS); setPage(1); }, []);

  const [flights, setFlights] = useState<Load<FlightList>>({ status: 'idle' });
  const flightsRef = useRef(flights);
  flightsRef.current = flights;
  const loadFlights = useCallback((force = false) => {
    const s = flightsRef.current.status;
    if (s === 'loading' || (!force && s !== 'idle')) return;
    setFlights({ status: 'loading' });
    fetchFlights().then(
      data => setFlights({ status: 'ready', data }),
      e => { if (e instanceof ApiError && e.status === 401) expire(); else setFlights({ status: 'error', message: failure(e) }); },
    );
  }, [expire]);

  const [details, setDetails] = useState<Record<string, Load<FlightDetail>>>({});
  const detailsRef = useRef(details);
  detailsRef.current = details;
  const loadDetail = useCallback((id: string) => {
    if (detailsRef.current[id]) return;
    setDetails(d => ({ ...d, [id]: { status: 'loading' } }));
    fetchFlightDetail(id).then(
      data => setDetails(d => ({ ...d, [id]: { status: 'ready', data } })),
      e => {
        if (e instanceof ApiError && e.status === 401) expire();
        else setDetails(d => ({ ...d, [id]: { status: 'error', message: failure(e) } }));
      },
    );
  }, [expire]);

  const [ck, setCk] = useState<CockpitState>({ flight: '', t: 0, speed: 1 });
  const [tree, setTree] = useState(() => new Set(['iceberg', 'iceberg.silver', 'iceberg.gold', 'iceberg.silver.rate_1hz', 'iceberg.silver.rate_4hz', 'iceberg.silver.rate_8hz']));
  const [catq, setCatq] = useState('');

  const [sqlText, setSqlText] = useState(SQL_EXAMPLES[0].sql);
  const [sqlRun, setSqlRun] = useState<SqlRun>({ status: 'idle' });
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const pending = useRef<{ controller: AbortController; sql: string } | null>(null);
  useEffect(() => () => { pending.current?.controller.abort(); pending.current = null; }, []);

  const runSql = useCallback(async (text: string) => {
    if (pending.current) return;
    const request = { controller: new AbortController(), sql: text };
    pending.current = request;
    setSqlText(text);
    setSqlRun({ status: 'run' });
    try {
      const result = await executeSql(text, request.controller.signal);
      if (pending.current !== request) return;
      const run: SqlRun = { status: 'ok', result, ms: result.ms, identity: result.query_identity };
      setSqlRun(run);
      const item: HistoryItem = { sql: text, status: 'ok', label: `${result.rows.length} rows${result.truncated ? ' (limited)' : ''} · ${result.query_identity}` };
      setHistory(h => [item, ...h].slice(0, 8));
    } catch (e) {
      if (pending.current !== request) return;
      if (e instanceof ApiError && e.status === 401) { expire(); return; }
      const status = e instanceof ApiError && e.status === 403 ? 'den' : 'err';
      const identity = me.trino_user ?? 'No role';
      setSqlRun({ status, msg: failure(e), identity });
      const item: HistoryItem = { sql: text, status, label: `${status === 'den' ? 'denied' : 'error'} · ${identity}` };
      setHistory(h => [item, ...h].slice(0, 8));
    } finally {
      if (pending.current === request) pending.current = null;
    }
  }, [expire, me.trino_user]);

  const cancelSql = useCallback(() => {
    const request = pending.current;
    if (!request) return;
    pending.current = null;
    request.controller.abort();
    setSqlRun({ status: 'can' });
    setHistory(h => [{ sql: request.sql, status: 'can' as const, label: 'stopped waiting' }, ...h].slice(0, 8));
  }, []);

  const loadSql = useCallback((text: string, run = false) => {
    cancelSql();
    setSqlText(text);
    setSqlRun({ status: 'idle' });
    navigate('/sql');
    if (run) runSql(text);
  }, [cancelSql, navigate, runSql]);

  const toggleTree = useCallback((k: string) => setTree(t => {
    const next = new Set(t);
    if (!next.delete(k)) next.add(k);
    return next;
  }), []);

  const openFlight = useCallback((id: string, tab?: string, phase?: string) => {
    navigate(`/flights/${encodeURIComponent(id)}${tab ? `/${tab}` : ''}${phase ? `?phase=${phase}` : ''}`);
  }, [navigate]);

  const openCockpit = useCallback((patch: Partial<CockpitState> = {}) => {
    setCk(c => ({ ...c, t: 0, ...patch }));
    navigate('/cockpit');
  }, [navigate]);

  const value: AppState = {
    explorer, setFilters, resetFilters, page, setPage,
    flights, loadFlights, details, loadDetail,
    ck, setCk,
    sqlText, setSqlText, sqlRun, history, runSql, cancelSql, loadSql, clearHistory: () => setHistory([]),
    tree, toggleTree, catq, setCatq,
    openFlight, openCockpit,
  };
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useAppState() {
  const s = useContext(AppContext);
  if (!s) throw new Error('useAppState outside AppStateProvider');
  return s;
}
