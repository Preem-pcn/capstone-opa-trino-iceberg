import { useLayoutEffect, useRef, type MouseEvent } from 'react';
import { usePopover } from '../components/Popover';
import { SAVED, TABLES, savedSql } from '../data/demo';
import { pad } from '../lib/format';
import { highlight, MASK, type Cell, type QueryResult } from '../lib/sqlEngine';
import { useAppState, type SqlRun } from '../state';

export function SqlWorkspace() {
  const { identity, sqlText, setSqlText, sqlRun, runSql, cancelSql, loadSql, history, clearHistory } = useAppState();
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
        <b style={{ fontSize: 14 }}>{identity === 'admin' ? 'Flight TG0341 / HS-THJ · Trino / iceberg' : `Fixture SQL · ${identity}`}</b>
        <span className="small muted">Ctrl/⌘ + Enter to run</span>
      </div>
      <div className="sqlwrap">
        <Catalog onInsert={insert} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, minWidth: 0 }}>
          <section className="card">
            <div className="ed-head" ref={saved.ref}>
              <div className="t">SQL EDITOR <span>Query 01</span></div>
              <div className="row">
                <button className="btn" onClick={saved.toggle} aria-haspopup="menu" aria-expanded={saved.open} style={{ minWidth: 150 }}>Saved examples ⌄</button>
                {sqlRun.status === 'run'
                  ? <button className="btn" onClick={cancelSql} style={{ minWidth: 147 }}>■ Cancel</button>
                  : <button className="btn primary" onClick={() => runSql(sqlText)} style={{ minWidth: 147 }}>▶ Run</button>}
              </div>
              {saved.open && (
                <div className="menu" role="menu" style={{ top: 44, right: 0 }}>
                  {SAVED.map(q => (
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
      <p className="small muted" style={{ paddingLeft: 2 }}>Query execution, statuses, history and permissions are simulated in the browser. This prototype does not enforce authorization.</p>
    </>
  );
}

function Catalog({ onInsert }: { onInsert: (txt: string) => void }) {
  const { tree, toggleTree, catq, setCatq, loadSql } = useAppState();
  const q = catq.trim().toLowerCase();
  const isOpen = (k: string) => !!q || tree.has(k);
  const caret = (k: string) => <span className="car">{isOpen(k) ? '▾' : '▸'}</span>;
  const schemas: Record<string, string[]> = {};
  Object.keys(TABLES).forEach(k => { const [, sch, tb] = k.split('.'); (schemas[sch] ??= []).push(tb); });

  // Click inserts the table name; double-click queries it; the caret toggles columns.
  const onTable = (tk: string) => (e: MouseEvent) => {
    if (e.detail >= 2) loadSql(`SELECT *\nFROM ${tk}\nLIMIT 100;`, true);
    else if ((e.target as HTMLElement).classList.contains('car')) toggleTree(tk);
    else onInsert(tk);
  };

  return (
    <section className="card catalog">
      <div className="ch">CATALOG <span className="muted" aria-hidden="true">⌕</span></div>
      <input type="search" placeholder="Filter tables & columns" value={catq} onChange={e => setCatq(e.target.value)} aria-label="Filter catalog" />
      <div className="tree">
        <button className="lv0" onClick={() => toggleTree('iceberg')}>{caret('iceberg')}iceberg</button>
        {isOpen('iceberg') && Object.entries(schemas).map(([sch, tbs]) => {
          const sk = `iceberg.${sch}`;
          const visible = tbs.filter(tb => !q || tb.includes(q) || sch.includes(q) || TABLES[`${sk}.${tb}`].cols.some(c => c.includes(q)));
          if (!visible.length) return null;
          return (
            <div key={sk} style={{ display: 'contents' }}>
              <button className="lv1" onClick={() => toggleTree(sk)}>{caret(sk)}{sch}{sch.startsWith('opa') && <span className="ty">fixture</span>}</button>
              {isOpen(sk) && visible.map(tb => {
                const tk = `${sk}.${tb}`;
                const showCols = isOpen(tk) && (!q || tree.has(tk) || TABLES[tk].cols.some(c => c.includes(q)));
                return (
                  <div key={tk} style={{ display: 'contents' }}>
                    <button className="lv2" onClick={onTable(tk)} title="Click to insert · double-click to query">{caret(tk)}{tb}</button>
                    {showCols && TABLES[tk].cols.filter(c => !q || c.includes(q) || tb.includes(q) || sch.includes(q)).map(c => (
                      <button key={c} className="lv3" onClick={() => onInsert(c)}>{c}</button>
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
  idle: ['idle', 'Idle'], run: ['run', 'Running…'], ok: ['ok', ''], err: ['err', 'ERROR'], den: ['den', 'ACCESS DENIED'], can: ['idle', 'CANCELLED'],
};

function Results({ run }: { run: SqlRun }) {
  const { loadSql } = useAppState();
  let label = STATUS[run.status][1];
  if (run.status === 'ok') {
    const n = run.result.rows.length;
    label = n ? `SUCCESS · ${n} ${run.result.table.includes('rate_') && n === 1 ? 'verified sample' : `row${n === 1 ? '' : 's'}`}` : 'SUCCESS · 0 rows';
  }
  return (
    <>
      <div className="res-head">
        <h3>RESULTS</h3>
        <span className={`status ${STATUS[run.status][0]}`}>{label}{run.status === 'ok' && <span className="muted" style={{ fontWeight: 400 }}> · {run.ms} ms</span>}</span>
      </div>
      <ResultBody run={run} />
      <div className="row" style={{ justifyContent: 'flex-end', marginTop: 14 }}>
        <button className="btn" onClick={() => loadSql(savedSql('phases'), true)}>Saved example: flight_phases</button>
      </div>
    </>
  );
}

function ResultBody({ run }: { run: SqlRun }) {
  switch (run.status) {
    case 'idle': return <div className="state" style={{ border: 0, padding: 24 }}><p className="small">Run a query to see results. Try a saved example or double-click a table in the catalog.</p></div>;
    case 'run': return <div className="state" style={{ border: 0, padding: 30 }}><span className="spinner" aria-hidden="true" /><p className="small">Loading · Retrieving from Trino / iceberg…</p></div>;
    case 'can': return <div className="state" style={{ border: 0, padding: 24 }}><h4>Query cancelled</h4><p className="small">No rows were returned.</p></div>;
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
        <p className="small muted" style={{ marginTop: 14 }}>Denied at query time · no zero substitution</p>
      </div>
    );
    case 'ok': {
      const r = run.result;
      if (!r.rows.length) {
        return (
          <div className="state" style={{ border: 0, padding: 20 }}><h4>Empty · 0 rows</h4>
            <p className="small">{/rate_(0p25|0p5|2|7)hz/.test(r.table) ? 'This sensor table has no rows in the POC sample.' : 'No rows match the WHERE clause. Adjust the filter or reset it.'}</p></div>
        );
      }
      const notes = notesFor(r, run.identity);
      return (
        <>
          <div className="scroll-x">
            <table className="rtable">
              <thead><tr>{r.cols.map(c => <th key={c}>{c}</th>)}</tr></thead>
              <tbody>{r.rows.map((row, i) => <tr key={i}>{row.map((v, j) => <ResultCell key={j} v={v} pseudoId={r.pseudo && r.cols[j] === 'flight_id'} />)}</tr>)}</tbody>
            </table>
          </div>
          {notes.length > 0 && <p className="small muted" style={{ marginTop: 12 }}>{notes.map((n, i) => <span key={i}>{i > 0 && <br />}{n}</span>)}</p>}
        </>
      );
    }
  }
}

function ResultCell({ v, pseudoId }: { v: Cell; pseudoId: boolean }) {
  if (v === MASK) return <td><span className="redact">REDACTED</span></td>;
  if (pseudoId && typeof v === 'string' && v.length > 40) return <td title={v}>{v.slice(0, 21)}…</td>;
  return <td>{String(v)}</td>;
}

function notesFor(r: QueryResult, identity: string) {
  const n: string[] = [];
  if (r.cols.includes('ias')) n.push('IAS unit unverified · only repository-supported point shown');
  if (r.cols.includes('heading')) n.push('heading is raw (−68.2031444°); cockpit shows 291.8° normalized');
  if (r.masked.length) n.push(`Masked for ${identity}: ${r.masked.join(', ')} → REDACTED`);
  if (r.pseudo) n.push('flight_id shown as SHA-256 pseudonym (truncated; hover for full hash)');
  if (r.table.includes('opa_demo')) n.push('Synthetic OPA fixture rows · not QAR recordings');
  return n;
}
