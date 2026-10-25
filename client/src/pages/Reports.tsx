import { useEffect, useState } from 'react';
import { ApiError, fetchEmbed, type EmbedInfo } from '../api';
import { useSession } from '../session';

type EmbedState =
  | { status: 'loading' }
  | { status: 'ready'; info: EmbedInfo }
  | { status: 'error'; message: string; fromServer: boolean };

/* Gold reports use the signed-in role's live, signed Metabase dashboard. The backend
   picks the dashboard from the session's role; the browser never chooses it. */
export function Reports() {
  const { expire } = useSession();
  const [state, setState] = useState<EmbedState>({ status: 'loading' });
  const [loaded, setLoaded] = useState(false);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let live = true;
    setState({ status: 'loading' });
    setLoaded(false);
    fetchEmbed().then(
      info => { if (live) setState({ status: 'ready', info }); },
      (e: unknown) => {
        if (!live) return;
        if (e instanceof ApiError && e.status === 401) { expire(); return; }
        const fromServer = e instanceof ApiError && e.status > 0;
        setState({ status: 'error', fromServer,
          message: fromServer ? (e as ApiError).message : 'Dashboard unavailable. Start the local BI demo server and Metabase, then use Refresh dashboard.' });
      },
    );
    return () => { live = false; };
  }, [nonce, expire]);

  // Signed links last 10 minutes; fetch a fresh one when the server says to.
  useEffect(() => {
    if (state.status !== 'ready') return;
    const id = window.setTimeout(() => setNonce(n => n + 1), state.info.refresh_after_seconds * 1000);
    return () => clearTimeout(id);
  }, [state]);

  const pill = state.status === 'ready'
    ? `${state.info.role_label} dashboard · Trino user ${state.info.query_identity} · read-only`
    : state.status === 'error' && state.fromServer ? 'No dashboard for this account' : 'Checking your role…';
  const loadText = state.status === 'error' ? state.message : state.status === 'ready' ? 'Loading the Gold dashboard…' : 'Connecting to Metabase…';

  return (
    <>
      <div className="page-head">
        <div><h1>Gold Reports</h1><p>Existing Iceberg Gold data · queried through Trino and visualized by Metabase</p></div>
        <div className="row">
          <button className="btn" onClick={() => setNonce(n => n + 1)}>Refresh dashboard</button>
          <button className="btn primary" onClick={() => window.open('/metabase', '_blank', 'noopener')}>Open in Metabase ↗</button>
        </div>
      </div>
      <section className="card bi-context">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <b>Metabase · Live Gold dashboard · capstone-opa-trino-iceberg</b>
          <span className="pill teal">{pill}</span>
        </div>
        <p className="small muted" style={{ marginTop: 9 }}>
          Use Flight date and Aircraft type inside the dashboard. Each role has its own dashboard. Its charts query this repo’s Gold tables
          through Trino over HTTPS with that role’s login, so OPA filters rows and masks columns before Metabase receives them. Flight Explorer
          reads Silver the same way; Cockpit and SQL Workspace keep their sample data.
        </p>
      </section>
      <section className="card bi-dashboard">
        {!loaded && <div role="status" className="bi-load-state">{loadText}</div>}
        {state.status === 'ready' && (
          <iframe key={state.info.embed_url} src={state.info.embed_url} title="Metabase dashboard showing actual QAR Gold data"
            onLoad={() => setLoaded(true)} />
        )}
      </section>
    </>
  );
}
