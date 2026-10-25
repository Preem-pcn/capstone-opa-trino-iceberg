import type { ReactNode } from 'react';
import { useAppState } from '../state';

function Section({ title, items }: { title: string; items: ReactNode[] }) {
  return <div><h2>{title}</h2><ul>{items.map((item, i) => <li key={i}>{item}</li>)}</ul></div>;
}

export function Notes() {
  const { openFlight } = useAppState();
  return (
    <>
      <div className="page-head"><div><h1>QAR Flight Analytics · assumptions &amp; questions</h1><p className="eyebrow" style={{ marginTop: 12 }}>DISCUSSION DOCUMENT · NOT APPROVED REQUIREMENTS</p></div></div>
      <div className="split notes">
        <section className="card" style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <Section title="1 / Scope & provenance" items={[
            'Inventory uses 3 A350 source recordings + 1 B777 upload. TG0614, TG0928 and TG0648 are invented flight numbers for UI demonstration.',
            <>Gold and sensor examples are confined to <code>HS-THJ_20220322T111310_F01</code> / TG0341.</>,
            'Parquet-derived POC metrics and phase/event SQL rules require airline validation.',
            'All timestamps and sample playback are UTC. Application visualizations are proposed, not operationally validated.',
          ]} />
          <Section title="2 / Flight & instrument decisions" items={[
            'Phase boundaries are inclusive; widths proportional to 5,154 / 1,640 / 12,568 / 1,890 / 768 s.',
            'Events: liftoff 5154, top_of_climb 6794, top_of_descent 19362, touchdown 21251.',
            <>Altitude: <code>rate_1hz.alt_std</code> 42,348 ft. GS: <code>rate_4hz.gs</code> 501.0 kts. Heading raw −68.2031444°, normalized 291.8°.</>,
            <>Pitch: <code>rate_4hz.pitch_ang_cap</code> +2.8125008°. Roll: <code>rate_4hz.rollangle_cpt</code> +0.1757813°.</>,
            <>Acceleration: <code>rate_8hz.vrtg</code> 0.99609375 g instantaneous; touchdown peak 1.277 g derived, distinct.</>,
            <>IAS <code>rate_1hz.ias</code> 244 with unit unverified. All charts without history are schematic. Missing samples should be gaps.</>,
            'Cockpit instruments are reusable shapes; no third-party cockpit library selected.',
          ]} />
          <Section title="3 / Query, BI & permissions" items={[
            'Existing POC SQL uses iceberg Silver at 0.25 / 0.5 / 1 / 2 / 4 / 7 / 8 Hz; uploaded B777 source also has 5 / 10 Hz, not confirmed ingested.',
            'Trino query execution, result statuses, query history and speed control are prototype-only interactions.',
            'Flight Explorer reads Silver through Trino. Gold Reports embeds the live Metabase dashboard of the signed-in role. Both query Trino as that role, so OPA applies. Cockpit and SQL Workspace retain prototype data.',
            'OPA fixtures are separate mock data. Counts 3/2/1 apply only to fixture identities, not inventory.',
            <>OPA operations_analyst stable SHA-256 (hex) fixture ID 1: <code>45c43228c3b55d0b1e756b232328e8a5bc564e6f5b4f4760d491e10c11ef75aa</code></>,
            <>Fixture ID 2: <code>6b2d528fac0d1077c465889bd9b1c1d5a3f4993ddbf45eeabef9b4ef57a603db</code></>,
            'Masking means REDACTED; denial means unavailable, never 0. This prototype does not enforce authorization.',
          ]} />
          <Section title="4 / Questions for airline stakeholders" items={[
            'What are the primary investigation scenarios, user personas, and preferred search criteria?',
            'Which phase, event and quality definitions should receive operational sign-off?',
            'Should playback default to native samples, hold-last, or explicitly selected resampling?',
            'Which parameters and units should be shown by default in the cockpit?',
            'Which departments need SQL vs. curated reports, and what roles can view each parameter?',
            'What metadata, provenance, and data-quality messages are required for auditability?',
          ]} />
        </section>
        <aside className="card" style={{ background: 'var(--surface-2)', alignSelf: 'start', display: 'flex', flexDirection: 'column', gap: 12 }}>
          <h2 style={{ margin: 0 }}>B777 uploaded source · 13 May 2022</h2>
          <p className="small">report.json: duration 10,500 s; airborne segment 9,017 s</p>
          <p className="small">Source flight number / route unknown; UI mock uses TG0648 / VTBS → RJAA.</p>
          <p className="small">sensor tables: 0.25 / 0.5 / 1 / 2 / 4 / 5 / 10 Hz</p>
          <p className="small" style={{ color: 'var(--red-text)' }}>no verified Gold metrics, no sample cockpit values</p>
          <p className="small muted">Stakeholder decision: accept incomplete flight metadata?</p>
          <button className="btn sm" style={{ alignSelf: 'flex-start' }} onClick={() => openFlight('TG0648')}>Open B777 recording</button>
        </aside>
      </div>
    </>
  );
}
