import { useEffect, useMemo, type ReactNode } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { EventsTable, Metric, PhaseBar, PhaseLegend } from '../components/common';
import { FLIGHTS_SQL, TID, TOTAL, VERIFIED_T, dur, flightBy, phaseBy, savedSql, type Flight, type Phase } from '../data/demo';
import { dLong, hms, n0, utc } from '../lib/format';
import { interp, P_ALT } from '../lib/profiles';
import { useAppState } from '../state';
import { SourceBadge } from './Explorer';

const TABS = [['overview', 'Overview'], ['phases', 'Phases & Events'], ['sensors', 'Sensors']] as const;
type Tab = (typeof TABS)[number][0];

export function FlightDetail() {
  const params = useParams();
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const { openCockpit, loadSql } = useAppState();
  const id = params.id ?? '';
  // Prototype flight numbers (TG0341, …) keep their transcribed record; any other id is a live Silver flight.
  const f = flightBy(id);
  if (!f) return <LiveFlight id={id} tab={params.tab === 'phases' ? 'phases' : 'overview'} />;
  if (f.type === 'B777') return <B777Flight f={f} />;
  if (!f.verified) return <DemoFlight f={f} />;

  const tab: Tab = TABS.some(([k]) => k === params.tab) ? (params.tab as Tab) : 'overview';
  const sel = phaseBy(search.get('phase') ?? '') ?? phaseBy('cruise')!;
  const showTab = (k: Tab) => navigate(`/flights/${f.no}${k === 'overview' ? '' : `/${k}`}${k === 'phases' ? `?phase=${sel.k}` : ''}`);
  const selectPhase = (k: string) => navigate(`/flights/${f.no}/phases?phase=${k}`);
  const intervalSql = `SELECT ts, t_offset_s, alt_std, ias\nFROM iceberg.silver.rate_1hz\nWHERE flight_id = '${TID}'\n  AND t_offset_s BETWEEN ${sel.s} AND ${sel.e}\nORDER BY t_offset_s\nLIMIT 100;`;

  return (
    <>
      <div className="ctx-chip"><span className="pill">{f.no} · {f.tail}</span></div>
      <div className="rec-head">
        <div>
          <div className="eyebrow">FLIGHT RECORD &nbsp;/&nbsp; {f.type}</div>
          <div className="title-row"><h1>{f.no}</h1><span className="pill">Recorded · example</span>{tab === 'phases' && <span className="pill teal">{sel.label} selected</span>}</div>
          <div className="rec-meta"><span>{f.type} · {f.tail}</span><span className="bar">|</span><span>{f.org} → {f.dst}</span><span className="bar">|</span><span>{dLong(f.date)}</span></div>
          <div className="rec-start">Recording start &nbsp;{utc(0, true)}</div>
        </div>
        {tab === 'phases' ? (
          <div className="actions" style={{ gridTemplateColumns: 'auto' }}>
            <button className="btn primary" onClick={() => openCockpit({ t: sel.s })}>Open this interval in cockpit</button>
            <button className="btn" onClick={() => loadSql(intervalSql, true)}>Query this interval in SQL</button>
          </div>
        ) : (
          <div className="actions">
            <button className="btn soft" onClick={() => showTab('sensors')}>Explore sensor data</button>
            <button className="btn primary" onClick={() => openCockpit()}>Open cockpit playback</button>
            <span />
            <button className="btn" onClick={() => loadSql(savedSql('q01'), true)}>Open related SQL</button>
          </div>
        )}
      </div>
      <div className="tabs" role="tablist">
        {TABS.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} className={`tab ${tab === k ? 'on' : ''}`} onClick={() => showTab(k)}>{l}</button>)}
      </div>
      {tab === 'phases' ? <PhasesTab sel={sel} onSelect={selectPhase} />
        : tab === 'sensors' ? <SensorsTab />
        : <Overview f={f} onSelect={selectPhase} />}
    </>
  );
}

// Silver metadata plus Gold summary, phases and events, read as the role's Trino user.
function LiveFlight({ id, tab }: { id: string; tab: 'overview' | 'phases' }) {
  const navigate = useNavigate();
  const { details, loadDetail } = useAppState();
  useEffect(() => { loadDetail(id); }, [id, loadDetail]);
  const back = <button className="btn" onClick={() => navigate('/flights')}>← Back to flights</button>;
  const d = details[id];
  if (!d || d.status === 'idle' || d.status === 'loading') return <>{back}<section className="card" role="status">Loading this flight from Silver and Gold…</section></>;
  if (d.status === 'error') return <>{back}<section className="card" role="alert">{d.message}</section></>;

  const { flight: f, summary: g, phases, events, query_identity } = d.data;
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
          <h1>{f.flight_no || f.flight_id}</h1>
          <p>{f.tail} · {f.origin} → {f.destination} · {dLong(f.flight_date)}</p>
        </div>
        <div className="row"><SourceBadge f={f} />{back}</div>
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
              <Metric lab="Airborne time" val={val(g.airborne_min)} unit="min" foot="Gold summary" />
              <Metric lab="Cruise time" val={val(g.cruise_min)} unit="min" foot="Gold summary" />
              <Metric lab="Maximum altitude" val={val(g.max_alt_ft, 0)} unit="ft" foot="Pressure altitude" />
              <Metric lab="Touchdown peak" val={val(g.touchdown_peak_g, 3)} unit="g" foot="Gold event value" />
            </div>
          ) : <section className="card">Gold summary is not available for this flight yet.</section>}
          <section className="card">
            <div className="card-head"><h3>Recording details</h3><span className="note">Trino identity: {query_identity}</span></div>
            <dl className="kv">
              <dt>Flight ID</dt><dd>{f.flight_id}</dd>
              <dt>Data source</dt><dd>{f.is_synthetic ? 'Synthetic demo' : 'Decoded recording'}</dd>
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

function Overview({ f, onSelect }: { f: Flight; onSelect: (k: string) => void }) {
  return (
    <>
      <div className="grid-4">
        <Metric lab="Airborne time" val="268.3" unit="min" foot="Different from total recording" />
        <Metric lab="Cruise time" val="209.5" unit="min" foot="Derived · POC example" />
        <Metric lab="Max pressure altitude" val="43,036" unit="ft" foot="Derived · POC example" />
        <Metric lab="Touchdown peak vertical accel." val="1.277" unit="g" foot="Not an approved safety threshold" />
      </div>
      <section className="card">
        <div className="card-head"><h3>Recorded flight phases</h3><span className="note">Inclusive offset boundaries · total recording 367.0 min (06:07:00) · click a phase to inspect</span></div>
        <PhaseBar onSelect={onSelect} /><PhaseLegend />
      </section>
      <div className="split">
        <section className="card"><div className="card-head"><h3>Detected events</h3><span className="note">Click to open in cockpit</span></div><EventsTable /></section>
        <section className="card"><div className="card-head"><h3>Data details</h3></div>
          <dl className="kv"><dt>flight_id</dt><dd>{f.id}</dd><dt>decoder_version</dt><dd>2.1.0</dd><dt>Phase/event rules</dt><dd>sql/04_gold.sql</dd><dt className="warn">Detector version</dt><dd className="warn">Not specified</dd></dl>
          <p className="small muted" style={{ marginTop: 16 }}>POC metrics · pending airline validation</p>
        </section>
      </div>
    </>
  );
}

function PhasesTab({ sel, onSelect }: { sel: Phase; onSelect: (k: string) => void }) {
  return (
    <>
      <section className="card">
        <div className="card-head"><h3>Select a phase to inspect its recorded interval</h3><span className="note">Inclusive offset boundaries</span></div>
        <PhaseBar sel={sel.k} onSelect={onSelect} /><PhaseLegend sel={sel.k} onSelect={onSelect} />
        <div style={{ marginTop: 18, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div className="mono" style={{ color: 'var(--accent-text)', fontWeight: 600, fontSize: 13 }}>{sel.label.toUpperCase()} &nbsp;·&nbsp; {hms(dur(sel))}</div>
          <div className="row mono small" style={{ gap: '8px 60px' }}>
            <span>Start &nbsp; {n0(sel.s)} s &nbsp;·&nbsp; {utc(sel.s)} UTC</span><span>End &nbsp; {n0(sel.e)} s &nbsp;·&nbsp; {utc(sel.e)} UTC</span>
            <span className="muted">Elapsed {hms(sel.s)} → {hms(sel.e)}</span>
          </div>
          <p className="small muted">Click phase bands to change the chart window; this is a proposed interaction.</p>
        </div>
      </section>
      <section className="card chart">
        <div className="card-head"><h3>Altitude overview · selected {sel.label} window</h3><span className="note">Schematic profile · illustrative, not verified 1 Hz history</span></div>
        <AltChart sel={sel} />
      </section>
      <section className="card"><div className="card-head"><h3>Events in recording</h3><span className="note">Click to open in cockpit</span></div><EventsTable /></section>
    </>
  );
}

const W = 1000, H = 210, L = 56, R = 16, T = 12, B = 30;
const ax = (t: number) => L + (t / TOTAL) * (W - L - R);
const ay = (a: number) => T + (1 - a / 45000) * (H - T - B);

function AltChart({ sel }: { sel: Phase }) {
  const path = useMemo(() => {
    let d = '';
    for (let i = 0; i <= 300; i++) { const t = (i / 300) * TOTAL; d += (i ? 'L' : 'M') + ax(t).toFixed(1) + ',' + ay(interp(P_ALT, t)).toFixed(1); }
    return d;
  }, []);
  const vx = ax(VERIFIED_T), vy = ay(42348);
  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Schematic altitude profile with the ${sel.label} window highlighted`}>
        <rect x={ax(sel.s)} y={T} width={ax(sel.e + 1) - ax(sel.s)} height={H - T - B} fill={`var(${sel.c})`} opacity=".16" />
        {[0, 15000, 30000, 45000].map(a => (
          <g key={a}><line x1={L} x2={W - R} y1={ay(a)} y2={ay(a)} stroke="var(--line-2)" /><text x={L - 8} y={ay(a) + 3} textAnchor="end">{a ? `${a / 1000}k` : '0'}</text></g>
        ))}
        <path d={path} fill="none" stroke="var(--ink-3)" strokeWidth="1.6" strokeDasharray="5 4" />
        <line x1={vx} x2={vx} y1={T} y2={H - B} stroke="var(--teal)" strokeWidth="1" />
        <circle cx={vx} cy={vy} r="5" fill="var(--teal)" stroke="var(--surface)" strokeWidth="2" />
        <rect x={vx + 10} y={vy + 10} rx="11" width="168" height="22" fill="var(--accent-soft)" />
        <text x={vx + 20} y={vy + 25} style={{ fill: 'var(--accent-text)', fontWeight: 600 }}>42,348 ft at 03:20:00</text>
        <text x={L} y={H - 10}>00:00:00</text><text x={W - R} y={H - 10} textAnchor="end">06:07:00</text>
        <text x={ax(sel.s)} y={H - 10} textAnchor={sel.k === 'ground_out' ? 'start' : 'middle'} style={{ fill: 'var(--accent-text)' }}>{sel.k === 'ground_out' ? '' : hms(sel.s)}</text>
      </svg>
      <div className="legend" style={{ marginTop: 6 }}>
        <span><i style={{ background: 'var(--ink-3)', height: 2, width: 16 }} />Illustrative profile</span>
        <span><i style={{ background: 'var(--teal)', borderRadius: '50%' }} />Verified sample (rate_1hz.alt_std)</span>
      </div>
    </>
  );
}

const SENSOR_ROWS = [
  ['rate_0p25hz', '0.25 Hz', '—', 'No rows in POC sample'], ['rate_0p5hz', '0.5 Hz', '—', 'No rows in POC sample'],
  ['rate_1hz', '1 Hz', 'alt_std · ias', 'alt_std 42,348 ft · ias 244 (unit unverified)'], ['rate_2hz', '2 Hz', '—', 'No rows in POC sample'],
  ['rate_4hz', '4 Hz', 'gs · heading · pitch_ang_cap · rollangle_cpt', 'gs 501.0 kts · heading −68.2031444° raw (291.8° normalized)'],
  ['rate_7hz', '7 Hz', '—', 'No rows in POC sample'], ['rate_8hz', '8 Hz', 'vrtg', 'vrtg 0.99609375 g'],
];

function SensorsTab() {
  const { loadSql, openCockpit } = useAppState();
  return (
    <>
      <section className="card">
        <div className="card-head"><h3>Native-rate sensor tables</h3><span className="note">iceberg.silver · verified sample at t_offset_s = 12000 only</span></div>
        <div className="scroll-x">
          <table className="dtable">
            <thead><tr><th>Table</th><th>Rate</th><th>Parameters</th><th>Verified value at 03:20:00</th><th /></tr></thead>
            <tbody>
              {SENSOR_ROWS.map(([table, rate, params, value]) => (
                <tr key={table}>
                  <td className="mono">{table}</td><td>{rate}</td><td className="mono small">{params}</td>
                  <td className={`small ${params === '—' ? 'muted' : ''}`}>{value}</td>
                  <td style={{ textAlign: 'right' }}>
                    <button className="btn sm" onClick={() => loadSql(`SELECT *\nFROM iceberg.silver.${table}\nWHERE flight_id = '${TID}'\nLIMIT 100;`, true)}>Query</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small muted" style={{ marginTop: 12 }}>Missing samples are shown as gaps, never interpolated into the record.</p>
      </section>
      <div className="row"><button className="btn primary" onClick={() => openCockpit()}>Open cockpit demo</button></div>
    </>
  );
}

function DemoFlight({ f }: { f: Flight }) {
  const navigate = useNavigate();
  const { openFlight, loadSql } = useAppState();
  return (
    <>
      <div className="rec-head">
        <div>
          <div className="eyebrow">FLIGHT RECORD &nbsp;/&nbsp; {f.type}</div>
          <div className="title-row"><h1>{f.no}</h1><span className="pill amber">Illustrative flight number</span><span className="pill">Not in verified Gold sample</span></div>
          <div className="rec-meta"><span>{f.type} · {f.tail}</span><span className="bar">|</span><span>{f.org} → {f.dst}</span><span className="bar">|</span><span>{dLong(f.date)}</span></div>
          <div className="rec-start">Recording duration &nbsp;{hms(f.dur)} · {n0(f.dur)} s</div>
        </div>
        <div className="actions" style={{ gridTemplateColumns: 'auto' }}>
          <button className="btn" onClick={() => navigate('/flights')}>← Back to Flight Explorer</button>
          <button className="btn" disabled title="No verified sensor sample">Cockpit · Unavailable</button>
        </div>
      </div>
      <div className="grid-4">
        {['Airborne time', 'Cruise time', 'Max pressure altitude', 'Touchdown peak vertical accel.'].map((lab, i) => (
          <Metric key={lab} lab={lab} val="—" unit={['min', 'min', 'ft', 'g'][i]} foot="Restricted · Unavailable" />
        ))}
      </div>
      <div className="state">
        <h4>No verified Gold outputs for this recording</h4>
        <p className="small" style={{ maxWidth: '60ch' }}>Phase, event and cockpit values are confined to TG0341 in this prototype. This row demonstrates browsing only; its flight number is illustrative.</p>
        <div className="row" style={{ justifyContent: 'center' }}>
          <button className="btn soft" onClick={() => openFlight('TG0341')}>Open verified example TG0341</button>
          <button className="btn" onClick={() => loadSql(FLIGHTS_SQL, true)}>Query silver.flights</button>
        </div>
      </div>
    </>
  );
}

function B777Flight({ f }: { f: Flight }) {
  const navigate = useNavigate();
  const seg = [['Before takeoff', 784, '--ph-go'], ['Airborne segment', 9017, '--teal'], ['After touchdown', 699, '--ph-gi']] as const;
  return (
    <>
      <div className="rec-head">
        <div>
          <div className="eyebrow">DEMO FLIGHT &nbsp;/&nbsp; B777 · MIXED SOURCE &amp; ILLUSTRATIVE METADATA</div>
          <div className="title-row"><h1>{f.no} · {f.tail}</h1><span className="pill amber">Illustrative flight metadata</span><span className="pill">Not in verified Gold sample</span></div>
          <div className="rec-meta" style={{ fontWeight: 600 }}>B777 · {f.tail} · {f.org} → {f.dst} (demo) · {dLong(f.date)}</div>
          <div className="small muted" style={{ marginTop: 8 }}>Recording start: 09:47:01 UTC (source-derived)</div>
          <div className="rec-start">Recorded source: HS-TKN_20220513124029.wgl/raw.dat</div>
        </div>
        <div className="actions" style={{ gridTemplateColumns: 'auto' }}>
          <button className="btn" onClick={() => navigate('/flights')}>← Back to Flight Explorer</button>
        </div>
      </div>
      <div className="grid-4">
        <Metric lab="Recording duration" val="02:55:00" unit="" foot="10,500 s" up />
        <Metric lab="Airborne segment" val="02:30:17" unit="" foot="9017 s · derived from aAIRGND1" up />
        <Metric lab="Parameters decoded" val="1,243" unit="" foot="decoder report" up />
        <Metric lab="Frame integrity" val="1.0" unit="" foot="report value (not validation)" up />
      </div>
      <section className="card">
        <div className="card-head"><h3>Recorded air / ground segmentation</h3><span className="note">Segmentation from aAIRGND1 · not the five-phase Gold timeline</span></div>
        <div style={{ display: 'flex', height: 37, gap: 1, marginTop: 6 }}>
          {seg.map(([label, s, c]) => <div key={label} title={`${label}: ${n0(s)} s`} style={{ width: `${(s / 10500) * 100}%`, background: `var(${c})` }} />)}
        </div>
        <div className="row mono small" style={{ justifyContent: 'space-between', marginTop: 12 }}>
          <span className="muted">0 s</span><b>Takeoff 784 s</b><b>Touchdown 9,801 s</b><span className="muted">10,500 s</span>
        </div>
        <p className="small muted" style={{ marginTop: 14 }}>Event offsets shown from decoder segmentation; no verified Cruise/Climb/Descent boundaries.</p>
      </section>
      <div className="split">
        <section className="card"><div className="card-head"><h3>Available sensor tables</h3></div>
          <p className="mono" style={{ fontSize: 13, lineHeight: 2 }}>0.25 Hz · 0.5 Hz · 1 Hz · 2 Hz<br />4 Hz · 5 Hz · 10 Hz</p>
          <p className="mono small muted" style={{ marginTop: 12, lineHeight: 1.9 }}>Examples: aALTSTD1 (1 Hz), aGS1 (1 Hz), aHEADINGM1 (1 Hz)<br />aPITCH1 (5 Hz), aVRTG1 (10 Hz), aAIRGND1 (5 Hz)</p>
          <p className="small muted" style={{ marginTop: 10 }}>Different from A350 field names and sample rates.</p>
        </section>
        <section className="card"><div className="card-head"><h3>Prototype notes</h3></div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 13, color: 'var(--ink-2)' }}>
            <span style={{ color: 'var(--accent-text)', fontWeight: 600 }}>Flight no. / route: demo-only values</span>
            <span>Cockpit playback values not verified</span><span>No Gold summary / phase metrics confirmed</span><span>Uploaded Parquet ≠ ingested into Trino</span>
            <span className="pill grey" style={{ alignSelf: 'flex-start' }}>Proposed import &amp; validation workflow</span>
          </div>
        </section>
      </div>
    </>
  );
}
