import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { ApiError, fetchFlightSensors, type FlightDetail, type FlightRow, type FlightSensors } from '../api';
import { dLong, hms } from '../lib/format';
import { displaySample, recordingUtc, sensorPath } from '../lib/sensors';
import { useSession } from '../session';
import { useAppState, type Load } from '../state';

export function Cockpit() {
  const { ck, setCk, flights, loadFlights, details, loadDetail, openFlight } = useAppState();
  const { expire } = useSession();
  const [sensors, setSensors] = useState<Load<{ id: string; data: FlightSensors }>>({ status: 'idle' });
  const [retry, setRetry] = useState(0);
  useEffect(() => { loadFlights(); }, [loadFlights]);
  const rows = flights.status === 'ready' ? flights.data.flights : [];
  const flight = rows.find(f => f.flight_id === ck.flight) ?? rows[0];
  const id = flight?.flight_id;
  useEffect(() => {
    if (!id) return;
    const controller = new AbortController();
    setSensors({ status: 'loading' });
    loadDetail(id);
    fetchFlightSensors(id, controller.signal).then(
      data => { if (!controller.signal.aborted) setSensors({ status: 'ready', data: { id, data } }); },
      error => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 401) expire();
        else setSensors({ status: 'error', message: error instanceof Error ? error.message : 'Sensor data unavailable.' });
      },
    );
    return () => controller.abort();
  }, [id, retry, loadDetail, expire]);

  if (flights.status === 'error') return <section className="card state" role="alert"><h3>Flights unavailable</h3><p>{flights.message}</p><button className="btn" onClick={() => loadFlights(true)}>Retry</button></section>;
  if (!flight) return <section className="card state" role="status">{flights.status === 'ready' ? 'No recordings available for your account.' : 'Loading recordings…'}</section>;
  const detail = details[flight.flight_id];
  const picker = <select className="select" style={{ width: 'auto', maxWidth: '100%' }} aria-label="Flight recording" value={flight.flight_id}
    onChange={e => setCk(c => ({ ...c, flight: e.target.value, t: 0 }))}>
    {rows.map(f => <option key={f.flight_id} value={f.flight_id}>{f.tail} · {dLong(f.flight_date)} · {f.flight_no}</option>)}
  </select>;

  return <>
    <div className="page-head">
      <div><h1>Sensor playback</h1><p>Review recorded flight parameters on a synchronized timeline.</p></div>
      <div className="row">{picker}<button className="btn" onClick={() => openFlight(flight.flight_id)}>Flight details →</button></div>
    </div>
    {sensors.status === 'ready' && sensors.data.id === id
      ? <Playback key={flight.flight_id} flight={flight} data={sensors.data.data} phases={detail?.status === 'ready' ? detail.data.phases : []} events={detail?.status === 'ready' ? detail.data.events : []} />
      : <section className="card state" role={sensors.status === 'error' ? 'alert' : 'status'}>
        {sensors.status === 'error' ? <><h3>Sensor data unavailable</h3><p>{sensors.message}</p><button className="btn" onClick={() => setRetry(n => n + 1)}>Retry</button></> : 'Loading recorded sensors…'}
      </section>}
  </>;
}

function Playback({ flight, data, phases, events }: { flight: FlightRow; data: FlightSensors; phases: FlightDetail['phases']; events: FlightDetail['events'] }) {
  const { ck, setCk } = useAppState();
  const [playing, setPlaying] = useState(false);
  const last = Math.max(0, data.seconds - 1);
  const t = Math.min(last, Math.max(0, Math.floor(ck.t)));
  const seek = (v: number) => { setPlaying(false); setCk(c => ({ ...c, t: Math.min(last, Math.max(0, v)) })); };
  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => setCk(c => ({ ...c, t: Math.min(last, c.t + c.speed) })), 1000);
    return () => clearInterval(timer);
  }, [playing, last, setCk]);
  useEffect(() => { if (t >= last) setPlaying(false); }, [t, last]);
  const v = Object.fromEntries(Object.entries(data.series).map(([key, values]) => [key, values[t] ?? null]));
  const phase = phases.find(p => p.start_s <= t && p.end_s >= t);
  const attitudeAvailable = v.pitch !== null && v.roll !== null;
  const heading = v.heading == null ? null : (v.heading % 360 + 360) % 360;
  const progress = { '--p': `${last ? t / last * 100 : 0}%` } as CSSProperties;
  return <>
    <div className="ck-head">
      <div><h2>{flight.aircraft_type} · {flight.tail} · {dLong(flight.flight_date)}</h2>
        <div className="ck-time"><span className="utc-big">{recordingUtc(flight.start_time, t)}</span><span className="off">Elapsed {hms(t)}</span></div>
      </div>
      {phase && <span className="pill teal">{phase.phase}</span>}
    </div>
    <div className="ck-panel">
      <div className="ck-top"><b>RECORDED FLIGHT PARAMETERS</b><span>{flight.is_synthetic ? 'Synthetic recording' : 'Flight recording'}</span></div>
      <div className="ck-grid">
        <div className="horizon">
          <div className="lbl">PITCH <span>{displaySample(v.pitch, 2)}°</span></div>
          {attitudeAvailable ? <svg viewBox="0 0 200 200" role="img" aria-label={`Pitch ${v.pitch} degrees, roll ${v.roll} degrees`}>
            <defs><clipPath id="hz-clip"><circle cx="100" cy="100" r="86" /></clipPath></defs>
            <circle cx="100" cy="100" r="96" fill="var(--cockpit)" stroke="var(--cockpit-line)" />
            <g clipPath="url(#hz-clip)"><g transform={`rotate(${-v.roll!} 100 100) translate(0 ${v.pitch! * 4})`}>
              <rect x="-200" y="-300" width="600" height="400" fill="var(--sky)" />
              <rect x="-200" y="100" width="600" height="400" fill="var(--ground)" />
              <line x1="-200" x2="400" y1="100" y2="100" stroke="var(--horizon)" strokeWidth="2" />
              {[-20, -10, 10, 20].map(d => <g key={d}><line x1="78" x2="122" y1={100 - d * 4} y2={100 - d * 4} stroke="var(--horizon)" /><text x="132" y={103 - d * 4} fill="var(--horizon)" fontSize="8">{Math.abs(d)}</text></g>)}
            </g></g>
            <path d="M52 100H84l16 7 16-7h32" fill="none" stroke="var(--wing)" strokeWidth="4" />
            <circle cx="100" cy="100" r="3" fill="var(--wing)" />
          </svg> : <div className="state">No attitude sample at this time</div>}
          <div className="lbl">ROLL <span>{displaySample(v.roll, 2)}°</span></div>
        </div>
        <div className="inst">
          <Instrument name="PRESSURE ALTITUDE" unit="ft" value={v.alt} digits={0} />
          <Instrument name="GROUND SPEED" unit="kt" value={v.gs} />
          <Instrument name="HEADING" unit="°" value={heading} />
          <Instrument name="VERTICAL ACCELERATION" unit="g" value={v.vrtg} digits={3} />
        </div>
      </div>
    </div>
    <section className="card">
      <div className="card-head"><h3>Recording timeline</h3><span className="note">{data.seconds.toLocaleString()} seconds · UTC</span></div>
      <div className="play">
        <div className="ctl">
          <button className="btn" onClick={() => seek(t - 1)} disabled={t === 0}>◂ Step</button>
          <button className="btn soft" disabled={!last} onClick={() => { if (t >= last) setCk(c => ({ ...c, t: 0 })); setPlaying(p => !p); }}>{playing ? '❚❚ Pause' : '▶ Play'}</button>
          <button className="btn" onClick={() => seek(t + 1)} disabled={t === last}>Step ▸</button>
          {[1, 10, 60].map(speed => <button key={speed} className={`speed ${ck.speed === speed ? 'on' : ''}`} aria-pressed={ck.speed === speed} onClick={() => setCk(c => ({ ...c, speed }))}>{speed}×</button>)}
        </div>
        <div className="seek">
          <div className="ticks"><span>{hms(0)}</span><b>{hms(t)}</b><span>{hms(last)}</span></div>
          <input className="rng" type="range" min="0" max={last} value={t} step="1" aria-label="Seek recording" style={progress} onChange={e => seek(Number(e.target.value))} />
          <div className="small muted">1× = one recorded second per second · Missing values appear as gaps.</div>
        </div>
      </div>
    </section>
    <section className="card">
      <div className="card-head"><h3>Synchronized sensors</h3><span className="note">One recorded sample per second · Individual value scales</span></div>
      <div className="sens">
        <Trend title="Pressure altitude" values={data.series.alt} t={t} unit="ft" digits={0} />
        <Trend title="Ground speed" values={data.series.gs} t={t} unit="kt" />
        <Trend title="Vertical acceleration · peak per second" values={data.series.vrtg_max} t={t} unit="g" digits={3} />
      </div>
    </section>
    {(phases.length > 0 || events.length > 0) && <section className="card">
      <div className="card-head"><h3>Phases & events</h3><span className="note">Select to seek</span></div>
      {phases.length > 0 && <>
        <div className="pbar phase-nav-track" role="group" aria-label="Flight phase timeline">
          {phases.map(p => {
            const start = Math.max(0, Math.min(data.seconds, p.start_s));
            const end = Math.max(start, Math.min(data.seconds, p.end_s + 1));
            return <button key={`${p.phase_order}-${p.start_s}`} type="button"
              className={`seg ${phase === p ? 'sel' : ''}`}
              style={{ left: `${start / data.seconds * 100}%`, width: `${(end - start) / data.seconds * 100}%`, background: phaseColor(p.phase) }}
              title={`${phaseLabel(p.phase)} · ${hms(p.start_s)}–${hms(p.end_s)}`}
              aria-label={`Seek to ${phaseLabel(p.phase)} at ${hms(p.start_s)}`} aria-pressed={phase === p}
              onClick={() => seek(p.start_s)} />;
          })}
          {events.map((e, i) => <span key={i} className="evmark" aria-hidden="true" style={{ left: `${Math.max(0, Math.min(1, e.t_offset_s / data.seconds)) * 100}%` }} />)}
        </div>
        <div className="phase-nav-buttons" role="group" aria-label="Jump to phase">
          {phases.map(p => <button key={`${p.phase_order}-${p.start_s}`} type="button"
            className={`phase-nav-button ${phase === p ? 'on' : ''}`} aria-pressed={phase === p}
            style={{ '--phase-color': phaseColor(p.phase) } as CSSProperties} onClick={() => seek(p.start_s)}>
            <span className="phase-nav-name">{phaseLabel(p.phase)}</span>
            <span className="phase-nav-time">{hms(p.start_s)}–{hms(p.end_s)}</span>
          </button>)}
        </div>
      </>}
      {events.length > 0 && <div className="event-nav-buttons" role="group" aria-label="Jump to event">
        {events.map((e, i) => <button key={i} className="event-nav-button" type="button" onClick={() => seek(e.t_offset_s)}>
          <span>{phaseLabel(e.event)}</span><span className="phase-nav-time">{hms(e.t_offset_s)}</span>
        </button>)}
      </div>}
    </section>}
  </>;
}

const PHASE_COLORS: Record<string, string> = {
  ground_out: '--ph-go', climb: '--ph-cl', cruise: '--ph-cr', descent: '--ph-de', ground_in: '--ph-gi',
};
const phaseColor = (name: string) => `var(${PHASE_COLORS[name] ?? '--ink-3'})`;
const phaseLabel = (name: string) => name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

function Instrument({ name, unit, value, digits = 1 }: { name: string; unit: string; value: number | null; digits?: number }) {
  return <div className={`ins ${value === null ? 'none' : ''}`}><div className="n">{name}</div><div className="v">{displaySample(value, digits)}</div><div className="u">{unit}</div><div className="s">{value === null ? 'No sample at this time' : 'Recorded value'}</div></div>;
}

function Trend({ title, values, t, unit, digits = 1 }: { title: string; values: (number | null)[]; t: number; unit: string; digits?: number }) {
  const { path, min, max } = useMemo(() => sensorPath(values), [values]);
  const cursor = 6 + t / Math.max(1, values.length - 1) * 298;
  return <div className="sp">
    <div className="h">{title}<span>{displaySample(values[t], digits)} {unit}</span></div>
    <svg viewBox="0 0 310 80" role="img" aria-label={`${title} over recording time`}>
      {[0.25, 0.5, 0.75].map(fr => <line key={fr} x1="6" x2="304" y1={6 + fr * 68} y2={6 + fr * 68} stroke="var(--line-2)" />)}
      <path d={path} fill="none" stroke="var(--teal)" strokeWidth="1.3" />
      <line x1={cursor} x2={cursor} y1="2" y2="78" stroke="var(--accent)" />
    </svg>
    <div className="f">{min === null ? 'No samples available' : `${displaySample(min, digits)} – ${displaySample(max, digits)} ${unit}`}</div>
  </div>;
}
