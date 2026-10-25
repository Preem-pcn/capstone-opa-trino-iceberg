import { createContext, useCallback, useContext, useEffect, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react';
import { useNavigate } from 'react-router-dom';
import { ApiError, fetchFlightDetail, fetchFlights, type FlightDetail, type FlightList } from './api';
import { SAVED } from './data/demo';
import { runQuery, SqlError, type QueryResult } from './lib/sqlEngine';
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
  | { status: 'ok'; result: QueryResult; ms: number; identity: string }
  | { status: 'err' | 'den'; msg: string; identity: string };
export interface HistoryItem { sql: string; status: SqlRun['status']; label: string }

interface AppState {
  // Trino identity the SQL and fixture pages simulate. Starts as the signed-in
  // role's Trino user; the fixture page's walk-through buttons switch it.
  identity: string;
  setSimIdentity(id: string | null): void;

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
  const [simIdentity, setSimIdentity] = useState<string | null>(null);
  const identity = simIdentity ?? me.trino_user ?? 'blocked_user';

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

  const [ck, setCk] = useState<CockpitState>({ flight: 'TG0341', t: 0, speed: 1 });
  const [tree, setTree] = useState(() => new Set(['iceberg', 'iceberg.silver', 'iceberg.gold', 'iceberg.silver.rate_1hz', 'iceberg.silver.rate_4hz', 'iceberg.silver.rate_8hz']));
  const [catq, setCatq] = useState('');

  const [sqlText, setSqlText] = useState(SAVED[0].sql);
  const [sqlRun, setSqlRun] = useState<SqlRun>({ status: 'idle' });
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const timer = useRef<number | null>(null);
  const stopTimer = () => { if (timer.current !== null) { clearTimeout(timer.current); timer.current = null; } };
  useEffect(() => stopTimer, []);

  const addHistory = (item: HistoryItem) => setHistory(h => [item, ...h].slice(0, 8));

  // Execution is simulated in the browser with a short artificial delay.
  const runSql = useCallback((text: string) => {
    if (timer.current !== null) return;
    const started = performance.now();
    setSqlText(text);
    setSqlRun({ status: 'run' });
    timer.current = window.setTimeout(() => {
      timer.current = null;
      let run: SqlRun, label: string;
      try {
        const result = runQuery(text, identity);
        run = { status: 'ok', result, ms: Math.round(performance.now() - started), identity };
        label = `${result.rows.length} row${result.rows.length === 1 ? '' : 's'}`;
      } catch (e) {
        if (!(e instanceof SqlError)) throw e;
        run = { status: e.kind, msg: e.message, identity };
        label = e.kind === 'den' ? 'denied' : 'error';
      }
      setSqlRun(run);
      addHistory({ sql: text, status: run.status, label: `${label} · ${identity}` });
    }, 450 + Math.random() * 450);
  }, [identity]);

  const cancelSql = useCallback(() => {
    stopTimer();
    setSqlRun({ status: 'can' });
    addHistory({ sql: sqlText, status: 'can', label: 'cancelled' });
  }, [sqlText]);

  const loadSql = useCallback((text: string, run = false) => {
    stopTimer();
    setSqlText(text);
    setSqlRun({ status: 'idle' });
    navigate('/sql');
    if (run) runSql(text);
  }, [navigate, runSql]);

  const toggleTree = useCallback((k: string) => setTree(t => {
    const next = new Set(t);
    if (!next.delete(k)) next.add(k);
    return next;
  }), []);

  const openFlight = useCallback((id: string, tab?: string, phase?: string) => {
    navigate(`/flights/${encodeURIComponent(id)}${tab ? `/${tab}` : ''}${phase ? `?phase=${phase}` : ''}`);
  }, [navigate]);

  // Cockpit links always target the TG0341 demo recording unless told otherwise.
  const openCockpit = useCallback((patch: Partial<CockpitState> = {}) => {
    setCk(c => ({ ...c, flight: 'TG0341', t: 0, ...patch }));
    navigate('/cockpit');
  }, [navigate]);

  const value: AppState = {
    identity, setSimIdentity,
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
