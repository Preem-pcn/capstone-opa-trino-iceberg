import { TABLES, savedSql } from '../data/demo';
import { applyPolicy, MASK, type Cell } from '../lib/sqlEngine';
import { useAppState } from '../state';
import { useToast } from '../toasts';

const WALK = [['admin', '1  Admin · 3'], ['operations_analyst', '2  Operations · 2'], ['engineering_analyst', '3  Engineering · 1'], ['blocked_user', '4  Blocked · denied'], ['safety_analyst', 'Safety · 3 masked']];
const NOTE: Record<string, string> = {
  admin: 'All three fixtures and original fields visible.',
  safety_analyst: 'All three fixtures visible; recording and source_file masked.',
  operations_analyst: 'Only routes involving VTBS (2 rows); tail, recording, source_file masked; touchdown_peak_g denied.',
  engineering_analyst: 'Only tail HS-THJ (1 row); flight_no, origin, destination masked.',
  blocked_user: 'Fixture queries denied. Frontend hiding alone is not authorization.',
};
const SENSITIVE: Record<string, string | null> = {
  admin: null, safety_analyst: 'recording: REDACTED', operations_analyst: 'source_file: REDACTED', engineering_analyst: 'route: REDACTED',
};

const show = (v: Cell) => (v === MASK ? <span className="redact">REDACTED</span> : String(v));

export function Fixtures() {
  const { identity, setSimIdentity, loadSql } = useAppState();
  const toast = useToast();
  // Mock identities only: they change this page and the fixture SQL, never what Trino returns.
  const pick = (k: string) => { setSimIdentity(k); toast(`Demo identity: ${k} · applies to OPA fixture queries`); };

  let body;
  if (identity === 'blocked_user') {
    body = (
      <>
        <div className="card-head"><h3 style={{ color: 'var(--red-text)' }}>Access Denied</h3><span className="note">0 accessible rows · query denied</span></div>
        <div style={{ padding: '20px 8px' }}><h2 style={{ fontSize: 28, color: 'var(--red-text)' }}>Access Denied</h2>
          <p style={{ marginTop: 14, color: 'var(--ink-2)' }}>This mock identity is prohibited from querying the OPA test fixtures.</p></div>
      </>
    );
  } else {
    const { rows } = applyPolicy(identity, 'iceberg.opa_demo_silver.flights', TABLES['iceberg.opa_demo_silver.flights'].rows);
    const sensitive = SENSITIVE[identity];
    body = (
      <>
        <div className="card-head"><h3>Fixture flights visible</h3><span className="note">{rows.length} synthetic fixture row{rows.length === 1 ? '' : 's'}</span></div>
        <div className="scroll-x">
          <table className="dtable" style={{ minWidth: 720 }}>
            <thead><tr><th>flight_id</th><th>Tail</th><th>Route</th><th>flight_no</th><th>Sensitive fields</th></tr></thead>
            <tbody>
              {rows.map((r, i) => {
                const id = String(r.flight_id);
                return (
                  <tr key={i}>
                    <td className="mono" title={id.length > 40 ? id : undefined}>{id.length > 40 ? `${id.slice(0, 21)}…` : id}</td>
                    <td className="mono">{show(r.tail)}</td>
                    <td className="mono">{r.origin === MASK ? show(MASK) : `${String(r.origin)} → ${String(r.destination)}`}</td>
                    <td className="mono">{show(r.flight_no)}</td>
                    <td>{sensitive ? <span className="redact">{sensitive}</span> : <span className="small muted">Original</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {identity === 'operations_analyst' && <p className="small muted" style={{ marginTop: 16 }}>Flight IDs displayed as truncated SHA-256 pseudonyms; hover a row to see the full stable hash.</p>}
      </>
    );
  }

  return (
    <>
      <div className="page-head"><div><h1>Permission fixture scenario</h1><p>Synthetic test rows · NOT QAR recordings · no cockpit playback or dates</p></div></div>
      <div className="row">
        {WALK.map(([k, l]) => <button key={k} className={`btn ${identity === k ? 'primary' : ''}`} aria-pressed={identity === k} onClick={() => pick(k)}>{l}</button>)}
      </div>
      <div className="card mono" style={{ background: 'var(--surface-2)', fontWeight: 600, fontSize: 13 }}>Dataset: OPA test fixtures &nbsp;&nbsp; iceberg.opa_demo_silver &nbsp;/&nbsp; iceberg.opa_demo_gold</div>
      <section className="card">{body}</section>
      <section className="card">
        <div className="card-head"><h3>OPA demonstration · server-enforced access control</h3></div>
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <p style={{ color: 'var(--ink-2)' }}>{NOTE[identity]}</p>
          <div className="row">
            <button className="btn" onClick={() => loadSql(savedSql('fix'), true)}>Run fixture query as {identity}</button>
            {identity === 'operations_analyst' && <button className="btn primary" onClick={() => loadSql(savedSql('denied'), true)}>Run denied SQL example →</button>}
          </div>
        </div>
      </section>
    </>
  );
}
