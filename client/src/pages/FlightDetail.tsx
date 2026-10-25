import { useEffect, type ReactNode } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Metric } from '../components/common';
import { dLong, hms } from '../lib/format';
import { useAppState } from '../state';
import { SourceBadge } from './Explorer';

export function FlightDetail() {
  const { id = '', tab } = useParams();
  return <LiveFlight id={id} tab={tab === 'phases' ? 'phases' : 'overview'} />;
}

function LiveFlight({ id, tab }: { id: string; tab: 'overview' | 'phases' }) {
  const navigate = useNavigate();
  const { details, loadDetail, openCockpit } = useAppState();
  useEffect(() => { loadDetail(id); }, [id, loadDetail]);
  const back = <button className="btn" onClick={() => navigate('/flights')}>← Back to flights</button>;
  const d = details[id];
  if (!d || d.status === 'idle' || d.status === 'loading') return <>{back}<section className="card" role="status">Loading flight details…</section></>;
  if (d.status === 'error') return <>{back}<section className="card" role="alert">{d.message}</section></>;

  const { flight: f, summary: g, phases, events } = d.data;
  const val = (x: number | null | undefined, digits = 1) => (x === null || x === undefined ? '—' : Number(x).toLocaleString('en-US', { maximumFractionDigits: digits }));
  const table = (headers: string[], rows: ReactNode[][]) => (
    <div className="scroll-x"><table className="dtable">
      <thead><tr>{headers.map(h => <th key={h}>{h}</th>)}</tr></thead>
      <tbody>{rows.map((row, i) => <tr key={i}>{row.map((x, j) => <td key={j}>{x ?? '—'}</td>)}</tr>)}</tbody>
    </table></div>
  );
  const showTab = (k: 'overview' | 'phases') => navigate(`/flights/${encodeURIComponent(id)}${k === 'phases' ? '/phases' : ''}`);

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">FLIGHT RECORD / {f.aircraft_type}</div>
          <h1>{f.flight_no && f.flight_no !== 'REDACTED' ? f.flight_no : `${f.aircraft_type} · ${f.tail}`}</h1>
          <p>{f.tail} · {f.origin} → {f.destination} · {dLong(f.flight_date)}</p>
        </div>
        <div className="row"><SourceBadge f={f} /><button className="btn primary" onClick={() => openCockpit({ flight: id })}>Sensor playback</button>{back}</div>
      </div>
      <div className="tabs" role="tablist">
        {([['overview', 'Overview'], ['phases', 'Phases & Events']] as const).map(([k, l]) => (
          <button key={k} className={`tab ${tab === k ? 'on' : ''}`} role="tab" aria-selected={tab === k} onClick={() => showTab(k)}>{l}</button>
        ))}
      </div>
      {tab === 'phases' ? (
        <>
          <section className="card"><div className="card-head"><h3>Flight phases</h3><span className="note">Inclusive recording offsets</span></div>
            {table(['Phase', 'Start (s)', 'End (s)', 'Duration', 'Detector'], phases.map(p => [p.phase, p.start_s, p.end_s, hms(p.duration_s), p.detector_ver]))}</section>
          <section className="card"><div className="card-head"><h3>Detected events</h3></div>
            {table(['Event', 'Offset (s)', 'UTC time', 'Value', 'Unit'], events.map(e => [e.event, e.t_offset_s, e.ts, val(e.value, 3), e.unit]))}</section>
        </>
      ) : (
        <>
          {g ? (
            <div className="grid-4">
              <Metric lab="Airborne time" val={val(g.airborne_min)} unit="min" foot="Flight summary" />
              <Metric lab="Cruise time" val={val(g.cruise_min)} unit="min" foot="Flight summary" />
              <Metric lab="Maximum altitude" val={val(g.max_alt_ft, 0)} unit="ft" foot="Pressure altitude" />
              <Metric lab="Touchdown peak" val={val(g.touchdown_peak_g, 3)} unit="g" foot="Detected event" />
            </div>
          ) : <section className="card">Flight summary is not available for this flight yet.</section>}
          <section className="card">
            <div className="card-head"><h3>Recording details</h3></div>
            <dl className="kv">
              <dt>Flight ID</dt><dd>{f.flight_id}</dd>
              <dt>Data source</dt><dd>{f.is_synthetic ? 'Synthetic data' : 'Decoded recording'}</dd>
              <dt>Recording start (UTC)</dt><dd>{f.start_time ?? '—'}</dd>
              <dt>Recording duration</dt><dd>{hms(f.duration_s ?? 0)}</dd>
              <dt>Recording</dt><dd>{f.recording ?? '—'}</dd>
              <dt>Decoder version</dt><dd>{f.decoder_version ?? '—'}</dd>
            </dl>
          </section>
        </>
      )}
    </>
  );
}
