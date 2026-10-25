import type { KeyboardEvent, ReactNode } from 'react';

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
