import { useEffect, useState } from 'react';
import type { FlightRow } from '../api';
import { rowKeys } from '../components/common';
import { usePopover } from '../components/Popover';
import { dLong, hms } from '../lib/format';
import { useAppState, type ExplorerFilters } from '../state';
import { useToast } from '../toasts';

/* Silver-backed listing. The backend queries iceberg.silver.flights as the signed-in
   role's Trino user, so OPA has already filtered rows and masked columns. */
const PAGE_SIZE = 20;

function matching(rows: FlightRow[], f: ExplorerFilters) {
  const q = f.q.trim().toLowerCase();
  return rows.filter(x =>
    (!q || [x.flight_no, x.flight_id, x.tail].some(v => String(v ?? '').toLowerCase().includes(q))) &&
    (!f.from || x.flight_date >= f.from) && (!f.to || x.flight_date <= f.to) &&
    (!f.type || x.aircraft_type === f.type) && (!f.org || x.origin === f.org) && (!f.dst || x.destination === f.dst) &&
    (!f.source || (f.source === 'synthetic' ? x.is_synthetic : !x.is_synthetic)));
}
const options = (rows: FlightRow[], key: 'aircraft_type' | 'origin' | 'destination') =>
  [...new Set(rows.map(x => x[key]).filter((v): v is string => !!v))].sort();

export function SourceBadge({ f }: { f: Pick<FlightRow, 'is_synthetic'> }) {
  return <span className={`pill sm ${f.is_synthetic ? '' : 'teal'}`}>{f.is_synthetic ? 'Synthetic demo' : 'Recorded'}</span>;
}

export function Explorer() {
  const { explorer: f, setFilters, resetFilters, page, setPage, flights, loadFlights, openFlight } = useAppState();
  const toast = useToast();
  useEffect(() => { loadFlights(); }, [loadFlights]);

  const all = flights.status === 'ready' ? flights.data.flights : [];
  const rows = matching(all, f);
  const recorded = all.filter(x => !x.is_synthetic).length;
  const countText = (n: number) => (n === all.length ? `${n} flights` : `${n} of ${all.length} flights`);

  const date = usePopover();
  const [from, setFrom] = useState(f.from);
  const [to, setTo] = useState(f.to);
  const openDate = () => { setFrom(f.from); setTo(f.to); date.toggle(); };
  const applyDate = () => {
    if (from && to && from > to) { toast('Start date must be on or before the end date.'); return; }
    setFilters({ from, to });
    date.setOpen(false);
  };

  const select = (id: string, label: string, key: 'type' | 'org' | 'dst', opts: string[], allLabel: string) => (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select id={id} className={`select ${f[key] ? 'set' : ''}`} value={f[key]} onChange={e => setFilters({ [key]: e.target.value } as Partial<ExplorerFilters>)}>
        <option value="">{allLabel}</option>
        {opts.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
    </div>
  );

  return (
    <>
      <div className="page-head">
        <div><h1>Browse flights</h1><p>Recorded and synthetic flights from Silver · UTC</p></div>
        <div className="row">
          <span className="pill">{flights.status === 'ready' ? countText(rows.length) : 'Loading…'}</span>
          <button className="btn" onClick={() => loadFlights(true)}>Refresh flights</button>
        </div>
      </div>
      <label className="search"><span aria-hidden="true" className="muted">⌕</span>
        <input type="search" placeholder="Search by flight number, flight ID, or aircraft tail" value={f.q} autoComplete="off" onChange={e => setFilters({ q: e.target.value })} />
      </label>
      <div className="filters">
        <div className="field" ref={date.ref}>
          <label htmlFor="f-date">Flight date</label>
          <button id="f-date" className={`datebtn ${f.from || f.to ? 'set' : ''}`} onClick={openDate} aria-haspopup="dialog" aria-expanded={date.open}>
            {f.from || f.to ? `${f.from || '…'} → ${f.to || '…'}` : 'All dates'}
          </button>
          {date.open && (
            <div className="menu datepop" role="dialog" aria-label="Flight date range">
              <div className="two">
                <div className="field"><label htmlFor="d-from">From</label><input type="date" id="d-from" value={from} onChange={e => setFrom(e.target.value)} /></div>
                <div className="field"><label htmlFor="d-to">To</label><input type="date" id="d-to" value={to} onChange={e => setTo(e.target.value)} /></div>
              </div>
              <div className="row" style={{ justifyContent: 'flex-end' }}>
                <button className="btn sm" onClick={() => date.setOpen(false)}>Cancel</button>
                <button className="btn sm primary" onClick={applyDate}>Apply</button>
              </div>
            </div>
          )}
        </div>
        {select('f-type', 'Aircraft type', 'type', options(all, 'aircraft_type'), 'All types')}
        {select('f-org', 'Origin', 'org', options(all, 'origin'), 'All origins')}
        {select('f-dst', 'Destination', 'dst', options(all, 'destination'), 'All destinations')}
        <button className="btn" onClick={resetFilters} style={{ height: 39 }}>Clear filters</button>
      </div>
      <section className="card" style={{ padding: '20px 14px 24px' }}>
        <div className="card-head" style={{ padding: '0 8px' }}>
          <h3>Silver flights</h3>
          <div className="seg2" aria-label="Data source">
            {([['', 'All', all.length], ['recorded', 'Recorded', recorded], ['synthetic', 'Synthetic', all.length - recorded]] as const).map(([key, label, n]) => (
              <button key={key} className={f.source === key ? 'on' : ''} aria-pressed={f.source === key} onClick={() => setFilters({ source: key })}>{label} ({n})</button>
            ))}
          </div>
        </div>
        <Rows rows={rows} page={page} setPage={setPage} openFlight={openFlight} onReset={resetFilters} onRetry={() => loadFlights(true)} />
      </section>
      <p className="small muted">
        Source: iceberg.silver.flights · Trino identity: {flights.status === 'ready' ? flights.data.query_identity : 'loading'} · Flight numbers are shown as stored, including source placeholders.
        {flights.status === 'ready' && flights.data.truncated && ` Showing the first ${all.length} of ${flights.data.total} available flights.`}
      </p>
    </>
  );
}

function Rows({ rows, page, setPage, openFlight, onReset, onRetry }: {
  rows: FlightRow[]; page: number; setPage(p: number): void; openFlight(id: string): void; onReset(): void; onRetry(): void;
}) {
  const { flights } = useAppState();
  if (flights.status === 'idle' || flights.status === 'loading') return <div className="state" role="status">Loading flights from Silver…</div>;
  if (flights.status === 'error') {
    return <div className="state" role="alert"><h4>Flights unavailable</h4><p>{flights.message}</p><button className="btn" onClick={onRetry}>Retry</button></div>;
  }
  if (!rows.length) {
    return <div className="state"><h4>No flights match these filters</h4><p>Try a different date, aircraft, airport, or data source.</p><button className="btn" onClick={onReset}>Reset filters</button></div>;
  }
  const pages = Math.ceil(rows.length / PAGE_SIZE);
  const current = Math.min(Math.max(1, page), pages);
  const first = (current - 1) * PAGE_SIZE;
  return (
    <>
      <div className="scroll-x">
        <table className="ftable">
          <thead><tr><th>FLIGHT DATE</th><th>FLIGHT NO. / SOURCE</th><th>TYPE</th><th>TAIL</th><th>ROUTE</th><th>RECORDING</th><th /></tr></thead>
          <tbody>
            {rows.slice(first, first + PAGE_SIZE).map(f => {
              const go = () => openFlight(f.flight_id);
              return (
                <tr key={f.flight_id} className="frow" tabIndex={0} onClick={go} onKeyDown={rowKeys(go)}>
                  <td>{dLong(f.flight_date)}</td>
                  <td><div className="fno" title={f.flight_id}>{f.flight_no || '—'}<SourceBadge f={f} /></div></td>
                  <td>{f.aircraft_type || '—'}</td><td>{f.tail || '—'}</td>
                  <td>{f.origin || '—'} → {f.destination || '—'}</td>
                  <td className="mono">{hms(f.duration_s ?? 0)}</td>
                  <td><button className="btn soft" aria-label={`Open ${f.flight_no || f.flight_id}`} onClick={e => { e.stopPropagation(); go(); }}>Open flight →</button></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="ex-pagination">
        <span>{first + 1}–{Math.min(first + PAGE_SIZE, rows.length)} of {rows.length} matching flights</span>
        <div className="row">
          <button className="btn sm" disabled={current === 1} onClick={() => setPage(current - 1)}>Previous</button>
          <span>Page {current} of {pages}</span>
          <button className="btn sm" disabled={current === pages} onClick={() => setPage(current + 1)}>Next</button>
        </div>
      </div>
    </>
  );
}
