import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from 'react';
import { ApiError, fetchCatalog, type CatalogResult, type SqlValue } from '../api';
import { usePopover } from '../components/Popover';
import { SQL_EXAMPLES } from '../lib/sqlExamples';
import { pad } from '../lib/format';
import { highlight } from '../lib/sqlHighlight';
import { useMe, useSession } from '../session';
import { useAppState, type Load, type SqlRun } from '../state';

export function SqlWorkspace() {
  const { sqlText, setSqlText, sqlRun, runSql, cancelSql, loadSql, history, clearHistory } = useAppState();
  const me = useMe();
  const ta = useRef<HTMLTextAreaElement>(null), hl = useRef<HTMLPreElement>(null), gut = useRef<HTMLDivElement>(null);
  const caret = useRef<number | null>(null);
  const saved = usePopover();

  const syncScroll = () => {
    if (!ta.current || !hl.current || !gut.current) return;
    hl.current.scrollTop = gut.current.scrollTop = ta.current.scrollTop;
    hl.current.scrollLeft = ta.current.scrollLeft;
  };
  // Restore the caret after an insert re-renders the controlled textarea.
  useLayoutEffect(() => {
    if (caret.current !== null && ta.current) {
      ta.current.selectionStart = ta.current.selectionEnd = caret.current;
      ta.current.focus();
      caret.current = null;
    }
    syncScroll();
  }, [sqlText]);

  const insert = (txt: string) => {
    const el = ta.current;
    if (!el) return;
    const s = el.selectionStart, e = el.selectionEnd;
    caret.current = s + txt.length;
    setSqlText(el.value.slice(0, s) + txt + el.value.slice(e));
  };
  const lines = sqlText.split('\n').length;

  return (
    <>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <b style={{ fontSize: 14 }}>Trino / iceberg · {me.trino_user}</b>
        <span className="small muted">Ctrl/⌘ + Enter to run</span>
      </div>
      <div className="sqlwrap">
        <Catalog onInsert={insert} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, minWidth: 0 }}>
          <section className="card">
            <div className="ed-head" ref={saved.ref}>
              <div className="t">SQL EDITOR <span>Query 01</span></div>
              <div className="row">
                <button className="btn" onClick={saved.toggle} aria-haspopup="menu" aria-expanded={saved.open} style={{ minWidth: 150 }}>Query library ⌄</button>
                {sqlRun.status === 'run'
                  ? <button className="btn" onClick={cancelSql} style={{ minWidth: 147 }} title="Stop waiting for this response. The server cancels queries that exceed 30 seconds.">■ Stop waiting</button>
                  : <button className="btn primary" onClick={() => runSql(sqlText)} style={{ minWidth: 147 }}>▶ Run</button>}
              </div>
              {saved.open && (
                <div className="menu" role="menu" style={{ top: 44, right: 0 }}>
                  {SQL_EXAMPLES.map(q => (
                    <button key={q.k} role="menuitem" onClick={() => { saved.setOpen(false); loadSql(q.sql); }}>
                      <span>{q.name}</span><small className="mono">{(q.sql.split('\n').find(l => /from/i.test(l)) ?? '').trim()}</small>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="editor">
              <div className="gutter" ref={gut}>{Array.from({ length: lines }, (_, i) => <div key={i}>{pad(i + 1)}</div>)}</div>
              <div className="code">
                <pre ref={hl} aria-hidden="true" dangerouslySetInnerHTML={{ __html: highlight(sqlText) }} />
                <textarea ref={ta} spellCheck={false} wrap="off" autoCapitalize="off" autoComplete="off" aria-label="SQL query"
                  value={sqlText} onChange={e => setSqlText(e.target.value)} onScroll={syncScroll}
                  onKeyDown={e => {
                    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); runSql(e.currentTarget.value); }
                    else if (e.key === 'Tab') { e.preventDefault(); insert('  '); }
                  }} />
              </div>
            </div>
          </section>
          <section className="card"><Results run={sqlRun} /></section>
          {history.length > 0 && (
            <section className="card">
              <div className="card-head" style={{ marginBottom: 8 }}><h3 style={{ fontSize: 14 }}>Query history · this session</h3><button className="btn sm" onClick={clearHistory}>Clear</button></div>
              <div className="hist">
                {history.map((h, i) => (
                  <button key={i} onClick={() => setSqlText(h.sql)}>
                    <span className={`dot ${h.status}`} /><code>{h.sql.replace(/\s+/g, ' ')}</code><span className="small muted">{h.label}</span>
                  </button>
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
      <p className="small muted" style={{ paddingLeft: 2 }}>Queries run through the backend as your signed-in role. Trino and OPA enforce data access. Results are limited to 500 rows and queries to 30 seconds.</p>
    </>
  );
}

function Catalog({ onInsert }: { onInsert: (txt: string) => void }) {
  const { tree, toggleTree, catq, setCatq, loadSql } = useAppState();
  const { expire } = useSession();
  const [catalog, setCatalog] = useState<Load<CatalogResult>>({ status: 'loading' });
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setCatalog({ status: 'loading' });
    fetchCatalog(controller.signal).then(
      data => { if (!controller.signal.aborted) setCatalog({ status: 'ready', data }); },
      error => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 401) expire();
        else setCatalog({ status: 'error', message: error instanceof Error ? error.message : 'Could not load catalog.' });
      },
    );
    return () => controller.abort();
  }, [expire, revision]);
  const tables = catalog.status === 'ready' ? catalog.data.tables : {};
  const q = catq.trim().toLowerCase();
  const isOpen = (k: string) => !!q || tree.has(k);
  const caret = (k: string) => <span className="car">{isOpen(k) ? '▾' : '▸'}</span>;
  const schemas: Record<string, string[]> = {};
  Object.keys(tables).forEach(k => { const [, sch, tb] = k.split('.'); (schemas[sch] ??= []).push(tb); });

  // Click inserts the table name; double-click queries it; the caret toggles columns.
  const onTable = (tk: string) => (e: MouseEvent) => {
    if (e.detail >= 2) loadSql(`SELECT *\nFROM ${tk}\nLIMIT 100;`, true);
    else if ((e.target as HTMLElement).classList.contains('car')) toggleTree(tk);
    else onInsert(tk);
  };

  return (
    <section className="card catalog">
      <div className="ch">CATALOG <button className="btn sm" onClick={() => setRevision(n => n + 1)} disabled={catalog.status === 'loading'}>Refresh</button></div>
      <input type="search" placeholder="Filter tables & columns" value={catq} onChange={e => setCatq(e.target.value)} aria-label="Filter catalog" />
      {catalog.status === 'loading' && <p className="small muted" role="status">Loading available tables…</p>}
      {catalog.status === 'error' && <p className="small" role="alert">{catalog.message}</p>}
      {catalog.status === 'ready' && <p className="small muted">{`Available to ${catalog.data.query_identity}`}</p>}
      {catalog.status === 'ready' && !Object.keys(tables).length && <p className="small muted">No tables available for this role.</p>}
      <div className="tree">
        <button className="lv0" onClick={() => toggleTree('iceberg')}>{caret('iceberg')}iceberg</button>
        {isOpen('iceberg') && Object.entries(schemas).map(([sch, tbs]) => {
          const sk = `iceberg.${sch}`;
          const visible = tbs.filter(tb => !q || tb.includes(q) || sch.includes(q) || tables[`${sk}.${tb}`].some(c => c.name.toLowerCase().includes(q)));
          if (!visible.length) return null;
          return (
            <div key={sk} style={{ display: 'contents' }}>
              <button className="lv1" onClick={() => toggleTree(sk)}>{caret(sk)}{sch}</button>
              {isOpen(sk) && visible.map(tb => {
                const tk = `${sk}.${tb}`;
                const showCols = isOpen(tk) && (!q || tree.has(tk) || tables[tk].some(c => c.name.toLowerCase().includes(q)));
                return (
                  <div key={tk} style={{ display: 'contents' }}>
                    <button className="lv2" onClick={onTable(tk)} title="Click to insert · double-click to query">{caret(tk)}{tb}</button>
                    {showCols && tables[tk].filter(c => !q || c.name.toLowerCase().includes(q) || tb.includes(q) || sch.includes(q)).map(c => (
                      <button key={c.name} className="lv3" onClick={() => onInsert(c.name)} title={c.type}>{c.name}<span className="ty">{c.type}</span></button>
                    ))}
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </section>
  );
}

const STATUS: Record<SqlRun['status'], [string, string]> = {
  idle: ['idle', 'Idle'], run: ['run', 'Running…'], ok: ['ok', ''], err: ['err', 'ERROR'], den: ['den', 'ACCESS DENIED'], can: ['idle', 'STOPPED WAITING'],
};

function Results({ run }: { run: SqlRun }) {
  const { loadSql } = useAppState();
  let label = STATUS[run.status][1];
  if (run.status === 'ok') {
    const n = run.result.rows.length;
    label = `SUCCESS · ${n} row${n === 1 ? '' : 's'}${run.result.truncated ? ' (limited)' : ''}`;
  }
  return (
    <>
      <div className="res-head">
        <h3>RESULTS</h3>
        <span className={`status ${STATUS[run.status][0]}`}>{label}{run.status === 'ok' && <span className="muted" style={{ fontWeight: 400 }}> · {run.ms} ms</span>}</span>
      </div>
      <ResultBody run={run} />
      <div className="row" style={{ justifyContent: 'flex-end', marginTop: 14 }}>
        <button className="btn" onClick={() => loadSql(SQL_EXAMPLES.find(q => q.k === 'phases')!.sql, true)}>Query flight phases</button>
      </div>
    </>
  );
}

function ResultBody({ run }: { run: SqlRun }) {
  switch (run.status) {
    case 'idle': return <div className="state" style={{ border: 0, padding: 24 }}><p className="small">Run a query to see results. Choose a query from the library or double-click a table in the catalog.</p></div>;
    case 'run': return <div className="state" style={{ border: 0, padding: 30 }}><span className="spinner" aria-hidden="true" /><p className="small">Loading · Retrieving from Trino / iceberg…</p></div>;
    case 'can': return <div className="state" style={{ border: 0, padding: 24 }}><h4>Stopped waiting for results</h4><p className="small">The server may still be running this query. Queries exceeding 30 seconds are cancelled automatically.</p></div>;
    case 'err': return (
      <div style={{ padding: '6px 0 4px' }}>
        <p className="mono" style={{ color: 'var(--red-text)', fontSize: 13 }}>{run.msg}</p>
        <p className="small muted" style={{ marginTop: 10 }}>Check table and column names in the catalog, then run again.</p>
      </div>
    );
    case 'den': return (
      <div style={{ padding: '4px 0' }}>
        <h2 style={{ fontSize: 26, color: 'var(--red-text)' }}>Access Denied</h2>
        <p className="mono" style={{ marginTop: 12, fontSize: 13 }}>{run.msg}</p>
        <p className="small muted" style={{ marginTop: 14 }}>Your account does not have permission to access this data.</p>
      </div>
    );
    case 'ok': {
      const r = run.result;
      if (!r.rows.length) {
        return (
          <div className="state" style={{ border: 0, padding: 20 }}><h4>Empty · 0 rows</h4>
            <p className="small">Query completed with no rows. Adjust the query or try another table.</p></div>
        );
      }
      return (
        <>
          <p className="small muted" style={{ marginBottom: 10 }}>{`Executed as ${run.identity}`}</p>
          <div className="scroll-x">
            <table className="rtable">
              <thead><tr>{r.columns.map((c, i) => <th key={i} title={c.type}>{c.name}</th>)}</tr></thead>
              <tbody>{r.rows.map((row, i) => <tr key={i}>{row.map((v, j) => <ResultCell key={j} v={v} column={r.columns[j]?.name} />)}</tr>)}</tbody>
            </table>
          </div>
          {r.truncated && <p className="small muted" style={{ marginTop: 12 }}>Showing the first {r.rows.length} rows. Add filters or a smaller LIMIT to narrow the result.</p>}
        </>
      );
    }
  }
}

function ResultCell({ v, column }: { v: SqlValue; column?: string }) {
  if (v === null) return <td><span className="muted">NULL</span></td>;
  if (v === 'REDACTED') return <td><span className="redact">REDACTED</span></td>;
  if (column === 'flight_id' && typeof v === 'string' && /^[a-f0-9]{64}$/.test(v)) return <td title={v}>{v.slice(0, 21)}…</td>;
  return <td>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</td>;
}
