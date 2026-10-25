import type { KeyboardEvent, ReactNode } from 'react';
import { EV, PH, TOTAL, dur } from '../data/demo';
import { hms, n0, utc } from '../lib/format';
import { useAppState } from '../state';

export function BrandMark({ color = 'var(--teal-bright)' }: { color?: string }) {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true">
      <path d="M14 2 26 14 14 26 2 14Z" fill="none" stroke={color} strokeWidth="2.2" />
      <path d="M14 9 19 14 14 19 9 14Z" fill={color} />
    </svg>
  );
}

export function Metric({ lab, val, unit, foot, up }: { lab: string; val: ReactNode; unit: string; foot: string; up?: boolean }) {
  return (
    <div className={`metric ${up ? 'up' : ''}`}>
      <div className="lab">{lab}</div><div className="val">{val}</div><div className="unit">{unit}</div><div className="foot">{foot}</div>
    </div>
  );
}

// Enter/Space on a focusable table row behaves like a click.
export const rowKeys = (go: () => void) => (e: KeyboardEvent) => {
  if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); go(); }
};

export function PhaseBar({ sel, onSelect, labels }: { sel?: string | null; onSelect: (k: string) => void; labels?: boolean }) {
  return (
    <>
      <div className="pbar">
        {PH.map(p => {
          const min = (dur(p) / 60).toFixed(1);
          return (
            <button key={p.k} className={`seg ${sel ? (sel === p.k ? 'sel' : 'dim') : ''}`}
              style={{ width: `${(dur(p) / TOTAL) * 100}%`, background: `var(${p.c})` }} onClick={() => onSelect(p.k)}
              title={`${p.label}: ${min} min · ${n0(p.s)}–${n0(p.e)} s`} aria-label={`${p.label} phase, ${min} minutes`} />
          );
        })}
        {EV.map(e => <span key={e.k} className="evmark" style={{ left: `${(e.t / TOTAL) * 100}%` }} title={`${e.label} · ${n0(e.t)} s`} />)}
      </div>
      {labels && (
        <div className="pbar-labels">
          {PH.map(p => (
            <span key={p.k} className={sel === p.k ? 'on' : ''} style={{ left: `${Math.min(Math.max(((p.s + dur(p) / 2) / TOTAL) * 100, 4), 95)}%` }}>{p.label}</span>
          ))}
        </div>
      )}
    </>
  );
}

export function PhaseLegend({ sel, onSelect }: { sel?: string | null; onSelect?: (k: string) => void }) {
  return (
    <div className="legend">
      {PH.map(p => {
        const inner = <><i style={{ background: `var(${p.c})` }} />{p.label}: {(dur(p) / 60).toFixed(1)} min</>;
        return onSelect
          ? <button key={p.k} className={sel === p.k ? 'on' : ''} onClick={() => onSelect(p.k)}>{inner}</button>
          : <span key={p.k}>{inner}</span>;
      })}
    </div>
  );
}

export function EventsTable() {
  const { openCockpit } = useAppState();
  return (
    <div className="scroll-x">
      <table className="dtable">
        <thead><tr><th>Event</th><th>Offset</th><th>Elapsed</th><th>UTC time</th></tr></thead>
        <tbody>
          {EV.map(e => {
            const go = () => openCockpit({ t: e.t });
            return (
              <tr key={e.k} className="click" tabIndex={0} onClick={go} onKeyDown={rowKeys(go)}>
                <td className="mono">{e.k}</td><td className="mono muted">{n0(e.t)} s</td>
                <td className="mono muted">{hms(e.t)}</td><td className="mono">{utc(e.t)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
