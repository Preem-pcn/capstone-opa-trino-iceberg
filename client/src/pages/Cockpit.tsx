import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { PhaseBar } from '../components/common';
import { EV, FLIGHTS, TOTAL, flightBy, phaseAt, phaseBy, type Flight } from '../data/demo';
import { dLong, hms, n0, utc } from '../lib/format';
import { illus, interp, P_ALT, P_GS, valuesAt, type Sample } from '../lib/profiles';
import { useAppState } from '../state';

const SPEC = {
  alt: { min: 0, max: 45000, P: (t: number) => interp(P_ALT, t), fmt: (v: number) => `${n0(Math.round(v))} ft` },
  gs: { min: 0, max: 560, P: (t: number) => interp(P_GS, t), fmt: (v: number) => `${v.toFixed(1)} kts` },
  vrtg: { min: 0.85, max: 1.35, P: (t: number) => illus(t).vrtg, fmt: (v: number) => `${v.toFixed(3)} g` },
};
type SparkKey = keyof typeof SPEC;
const SPW = 310, SPH = 80;
const spx = (t: number) => 6 + (t / TOTAL) * (SPW - 12);
const spy = (k: SparkKey, v: number) => { const s = SPEC[k]; return 6 + (1 - (v - s.min) / (s.max - s.min)) * (SPH - 12); };
// The demo trend lines never change, so build them once.
const SPARK_PATH = Object.fromEntries((Object.keys(SPEC) as SparkKey[]).map(k => {
  let d = '';
  for (let i = 0; i <= 240; i++) { const t = (i / 240) * TOTAL; d += (i ? 'L' : 'M') + spx(t).toFixed(1) + ',' + spy(k, SPEC[k].P(t)).toFixed(1); }
  return [k, d];
})) as Record<SparkKey, string>;

export function Cockpit() {
  const { ck, setCk } = useAppState();
  const f = flightBy(ck.flight) ?? FLIGHTS[0];
  const picker = (
    <select className="select" style={{ width: 'auto', minWidth: 220 }} aria-label="Flight" value={f.no}
      onChange={e => setCk(c => ({ ...c, flight: e.target.value, t: 0 }))}>
      {FLIGHTS.map(x => <option key={x.no} value={x.no}>{x.no} · {x.tail} · {dLong(x.date)}</option>)}
    </select>
  );

  if (!f.verified) {
    return (
      <>
        <div className="ck-head"><div><h1>{f.no} &nbsp;/&nbsp; {f.type} · {f.tail}</h1><div className="ck-sub">{f.org} → {f.dst} · {dLong(f.date)} · HISTORICAL PLAYBACK</div></div>{picker}</div>
        <div className="ck-panel">
          <div className="ck-top"><b>RECORDED SENSOR VALUES</b><span>Not live aircraft telemetry</span></div>
          <div className="inst" style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))' }}>
            {['ALTITUDE', 'GS', 'HEADING', 'VERTICAL ACCEL.'].map(n => (
              <div key={n} className="ins none"><div className="n">{n}</div><div className="v">—</div><div className="u" /><div className="s">Restricted · Unavailable</div></div>
            ))}
          </div>
        </div>
        <div className="state"><h4>Cockpit playback unavailable for {f.no}</h4><p className="small">Cockpit demo is available for TG0341 in this prototype.</p>
          <button className="btn primary" onClick={() => setCk(c => ({ ...c, flight: 'TG0341', t: 0 }))}>Switch to demo TG0341</button></div>
      </>
    );
  }
  return <Playback f={f} picker={picker} />;
}

function Playback({ f, picker }: { f: Flight; picker: ReactNode }) {
  const { ck, setCk } = useAppState();
  const [playing, setPlaying] = useState(false);
  const t = ck.t;
  const setT = useCallback((v: number) => setCk(c => ({ ...c, t: Math.max(0, Math.min(TOTAL - 1, v)) })), [setCk]);
  const tRef = useRef(t);
  useEffect(() => { tRef.current = t; }, [t]);

  // 1× = one minute of recording per second.
  useEffect(() => {
    if (!playing) return;
    let raf = 0, last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min((now - last) / 1000, 0.25); last = now;
      const next = tRef.current + dt * 60 * ck.speed;
      if (next >= TOTAL - 1) { setT(TOTAL - 1); setPlaying(false); return; }
      tRef.current = next; setT(next);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, ck.speed, setT]);

  const togglePlay = useCallback(() => {
    if (!playing && tRef.current >= TOTAL - 2) setT(0);
    setPlaying(p => !p);
  }, [playing, setT]);
  const seek = (v: number) => { setPlaying(false); setT(v); };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (/INPUT|TEXTAREA|SELECT/.test(tag)) return;
      if (e.key === ' ') { if (tag === 'BUTTON') return; e.preventDefault(); togglePlay(); }   // a focused button handles its own Space
      else if (e.key === 'ArrowRight') { e.preventDefault(); seek(Math.round(tRef.current) + (e.shiftKey ? 60 : 1)); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); seek(Math.round(tRef.current) - (e.shiftKey ? 60 : 1)); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const v = valuesAt(t);
  const cur = phaseAt(t);
  const signed = (x: number) => `${x >= 0 ? '+' : '−'}${Math.abs(x).toFixed(4)}°`;
  const progress = { '--p': `${(t / (TOTAL - 1)) * 100}%` } as CSSProperties;

  return (
    <>
      <div className="ck-head">
        <div>
          <h1>{f.no} &nbsp;/&nbsp; {f.type} · {f.tail}</h1>
          <div className="ck-sub"><span>{f.org} → {f.dst}</span><span>{dLong(f.date)}</span><span>HISTORICAL PLAYBACK</span></div>
          <div className="ck-time"><span className="utc-big">{utc(t, true)}</span><span className="off">t_offset_s = {Math.round(t)} &nbsp;·&nbsp; elapsed {hms(t)}</span></div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-end' }}>{picker}<span className="pill teal">{cur.label}</span></div>
      </div>
      <div className="ck-panel" aria-live="off">
        <div className="ck-top"><b>SENSOR PLAYBACK DEMO</b><span>Demo data</span></div>
        <div className="ck-grid">
          <div className="horizon">
            <div className="lbl">PITCH &nbsp;<span>{signed(v.pitch)}</span></div>
            <svg viewBox="0 0 200 200" aria-label="Attitude indicator" role="img">
              <defs><clipPath id="hz-clip"><circle cx="100" cy="100" r="86" /></clipPath></defs>
              <circle cx="100" cy="100" r="96" fill="var(--cockpit)" stroke="var(--cockpit-line)" />
              <g clipPath="url(#hz-clip)">
                <g transform={`rotate(${-v.roll} 100 100) translate(0 ${v.pitch * 4})`}>
                  <rect x="-200" y="-300" width="600" height="400" fill="var(--sky)" />
                  <rect x="-200" y="100" width="600" height="400" fill="var(--ground)" />
                  <line x1="-200" x2="400" y1="100" y2="100" stroke="var(--horizon)" strokeWidth="2" />
                  {[-20, -10, 10, 20].map(d => {
                    const half = Math.abs(d) === 10 ? 18 : 28;
                    return (
                      <g key={d}>
                        <line x1={100 - half} x2={100 + half} y1={100 - d * 4} y2={100 - d * 4} stroke="var(--horizon)" strokeWidth="1.2" opacity=".85" />
                        <text x={134} y={100 - d * 4 + 3} style={{ fill: 'var(--horizon)', fontSize: 8 }}>{Math.abs(d)}</text>
                      </g>
                    );
                  })}
                  {[-5, 5, -15, 15].map(d => <line key={d} x1="92" x2="108" y1={100 - d * 4} y2={100 - d * 4} stroke="var(--horizon)" strokeWidth="1" opacity=".6" />)}
                </g>
              </g>
              <path d="M52 100H84l6 7 6-7" fill="none" stroke="var(--wing)" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" transform="translate(4 0)" />
              <path d="M148 100H116l-6 7-6-7" fill="none" stroke="var(--wing)" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" transform="translate(-4 0)" />
              <circle cx="100" cy="100" r="3" fill="var(--wing)" />
              <path d="M100 8l-6 10h12z" fill="var(--wing)" />
            </svg>
            <div className="lbl">ROLL &nbsp;&nbsp;<span>{signed(v.roll)}</span></div>
          </div>
          <div className="inst">
            <Instrument name="ALTITUDE" unit="ft" src="rate_1hz.alt_std" value={n0(Math.round(v.alt))} />
            <Instrument name="GROUND SPEED · GS" unit="kts" src="rate_4hz.gs" value={v.gs.toFixed(1)} />
            <Instrument name="MAG HEADING" unit="°" src="rate_4hz.heading" value={v.hdg.toFixed(1)} />
            <Instrument name="VERTICAL ACCEL." unit="g" src="rate_8hz.vrtg" value={v.vrtg.toFixed(3)} />
          </div>
        </div>
      </div>
      <section className="card">
        <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
          <span className="eyebrow">HISTORICAL PLAYBACK</span><span className="small muted">Demo data</span>
        </div>
        <div className="play">
          <div className="ctl">
            <button className="btn" onClick={() => seek(Math.round(t) - 1)} aria-label="Step back 1 second">◂ Step</button>
            <button className="btn soft" onClick={togglePlay} style={{ minWidth: 90 }}>{playing ? '❚❚ Pause' : '▶ Play'}</button>
            <button className="btn" onClick={() => seek(Math.round(t) + 1)} aria-label="Step forward 1 second">Step ▸</button>
            <span style={{ width: 8 }} />
            {[0.5, 1, 2, 4].map(s => (
              <button key={s} className={`speed ${ck.speed === s ? 'on' : ''}`} aria-pressed={ck.speed === s} onClick={() => setCk(c => ({ ...c, speed: s }))}>{s}×</button>
            ))}
          </div>
          <div className="seek">
            <div className="ticks"><span>00:00:00</span><b>{hms(t)}</b><span>06:07:00</span></div>
            <div className="seekwrap">
              <input className="rng" type="range" min="0" max={TOTAL - 1} step="1" value={Math.round(t)} aria-label="Seek recording" style={progress}
                onChange={e => seek(+e.target.value)} />
            </div>
            <div className="row small muted"><span>1× = 1 min of recording per second · ← → step, space play</span></div>
          </div>
        </div>
      </section>
      <section className="card">
        <div className="card-head"><h3>Synchronized sensors</h3><span className="note">Common time cursor · individual value scales · native 1 / 4 / 8 Hz</span></div>
        <div className="sens">
          <Spark k="alt" title="Pressure altitude" src="rate_1hz.alt_std · 1 Hz" t={t} v={v} />
          <Spark k="gs" title="Ground speed" src="rate_4hz.gs · 4 Hz" t={t} v={v} />
          <Spark k="vrtg" title="Vertical acceleration" src="rate_8hz.vrtg · 8 Hz" t={t} v={v} />
        </div>
      </section>
      <section className="card">
        <div className="card-head"><h3>Phase navigation</h3><span className="note">Click a phase or event to seek</span></div>
        <PhaseBar sel={cur.k} onSelect={k => seek(phaseBy(k)!.s)} labels />
        <div className="evlinks">{EV.map(e => <button key={e.k} onClick={() => seek(e.t)}>{e.label} {hms(e.t)}</button>)}</div>
      </section>
    </>
  );
}

// Demo values render in the illustrative (yellow) style; there is no verified/illustrative tag in v3.
function Instrument({ name, unit, src, value }: { name: string; unit: string; src: string; value: string }) {
  return (
    <div className="ins illus">
      <div className="n"><span>{name}</span></div>
      <div className="v">{value}</div><div className="u">{unit}</div><div className="s">{src}</div>
    </div>
  );
}

function Spark({ k, title, src, t, v }: { k: SparkKey; title: string; src: string; t: number; v: Sample }) {
  return (
    <div className="sp">
      <div className="h">{title}<span>{SPEC[k].fmt(v[k])}</span></div>
      <svg viewBox={`0 0 ${SPW} ${SPH}`} aria-hidden="true">
        {[0.25, 0.5, 0.75].map(fr => <line key={fr} x1="6" x2={SPW - 6} y1={6 + fr * (SPH - 12)} y2={6 + fr * (SPH - 12)} stroke="var(--line-2)" />)}
        <path d={SPARK_PATH[k]} fill="none" stroke="var(--amber)" strokeWidth="1.3" strokeDasharray="3 3" opacity={0.9} />
        <line x1={spx(t)} x2={spx(t)} y1="2" y2={SPH - 2} stroke="var(--accent)" strokeWidth="1.2" />
      </svg>
      <div className="f">Demo sensor trend</div>
      <div className="src">{src}</div>
    </div>
  );
}
