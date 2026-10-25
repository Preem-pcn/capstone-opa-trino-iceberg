import type { CSSProperties } from 'react';
import { useNavigate } from 'react-router-dom';

// [label, kind, route, description, children]; content nodes describe a page and do not navigate.
type Node = [string, 'page' | 'sub' | 'content', string | null, string, Node[]?];

const SECTIONS: [string, string, string, Node[]][] = [
  ['Flight Explorer', '--st1', '/flights', [
    ['Search box', 'content', null, 'flight no · flight ID · tail'],
    ['Filters', 'content', null, 'date · aircraft type · origin · destination'],
    ['Flight list', 'content', null, 'date · flight · type · tail · route · recording'],
    ['Flight Detail', 'page', '/flights/TG0341', 'one page for every flight', [
      ['Overview', 'sub', '/flights/TG0341', 'KPI cards · phase bar · events · data details'],
      ['Phases & Events', 'sub', '/flights/TG0341/phases', 'select phase → interval chart · events'],
      ['Sensors', 'sub', '/flights/TG0341/sensors', 'native-rate tables · canonical parameters'],
    ]],
  ]],
  ['Cockpit & Sensors', '--st2', '/cockpit', [
    ['Flight & time picker', 'content', null, 'flight · UTC · t_offset_s'],
    ['Instrument panel', 'content', null, 'attitude · altitude · GS · heading · VRTG'],
    ['Playback controls', 'content', null, 'play · step · speed · seek bar'],
    ['Synchronized sensors', 'content', null, 'mini charts with one time cursor'],
  ]],
  ['SQL Workspace', '--st3', '/sql', [
    ['Catalog', 'content', null, 'Silver & Gold tables, columns'],
    ['SQL editor', 'content', null, 'saved examples · run / cancel'],
    ['Results', 'content', null, 'rows · masked / denied states'],
    ['Query history', 'content', null, 'this session'],
  ]],
  ['Gold Reports', '--st4', '/reports', [
    ['Metabase dashboard', 'content', null, 'live Gold through Trino · dashboard of the signed-in role'],
    ['Filters and KPIs', 'content', null, 'flight date · aircraft type · count · time · altitude'],
    ['Charts and tables', 'content', null, 'route · phases · flight summary · events'],
  ]],
  ['Prototype', '--st5', '/notes', [
    ['OPA test fixtures', 'page', '/fixtures', '5 demo identities · masked / denied'],
    ['Assumptions & questions', 'page', '/notes', 'scope · open questions'],
    ['Site map', 'page', '/sitemap', 'this page'],
  ]],
];

export function Sitemap() {
  const navigate = useNavigate();
  const node = ([label, kind, to, desc, kids]: Node, c: string) => (
    <li key={label}>
      <button className={`st-node ${kind}`} style={{ '--c': `var(${c})` } as CSSProperties}
        tabIndex={to ? undefined : -1} onClick={to ? () => navigate(to) : undefined}>
        <b>{label}</b>{desc && <small>{desc}</small>}
      </button>
      {kids && <ul className="st-list">{kids.map(k => node(k, c))}</ul>}
    </li>
  );
  return (
    <>
      <div className="page-head"><div><h1>Site map</h1><p>Every page in the prototype and what it contains. Click a box to open it.</p></div></div>
      <section className="card st-card">
        <div className="st">
          <div className="st-home"><b>QAR Flight Analytics</b><small>Home · opens Flight Explorer</small></div>
          <div className="st-cols">
            {SECTIONS.map(([label, c, to, kids]) => (
              <div key={label} className="st-col">
                <button className="st-sec" style={{ '--c': `var(${c})` } as CSSProperties} onClick={() => navigate(to)}>{label}</button>
                <ul className="st-list">{kids.map(k => node(k, c))}</ul>
              </div>
            ))}
          </div>
        </div>
        <div className="legend" style={{ marginTop: 22 }}>
          <span><i className="st-k" style={{ background: 'var(--st1)' }} />Section (sidebar menu)</span>
          <span><i className="st-k solid" />Page or tab</span>
          <span><i className="st-k dash" />Content on the page</span>
        </div>
      </section>
      <section className="card">
        <div className="card-head"><h3>Links between sections</h3></div>
        <ul className="sm-j" style={{ listStyle: 'disc' }}>
          <li>Flight Explorer → <b>Flight Detail</b> (Open flight)</li>
          <li>Gold Reports → <b>Metabase dashboard</b> (live Gold; cross-page drill-through is not configured)</li>
          <li>Flight Detail → <b>Cockpit &amp; Sensors</b> (Open cockpit playback / open interval)</li>
          <li>Flight Detail → <b>SQL Workspace</b> (Open related SQL)</li>
        </ul>
      </section>
    </>
  );
}
