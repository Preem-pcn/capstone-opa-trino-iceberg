import { useEffect, type ReactNode } from 'react';
import { NavLink, matchPath, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { flightBy, phaseBy } from '../data/demo';
import { useMe } from '../session';
import { useAppState } from '../state';
import { BrandMark } from './common';

const NAV = [
  { to: '/flights', label: 'Flight Explorer', icon: '⌕' },
  { to: '/cockpit', label: 'Cockpit & Sensors', icon: '◉' },
  { to: '/sql', label: 'SQL Workspace', icon: '⌘' },
  { to: '/reports', label: 'Gold Reports', icon: '▤' },
];
const PROTOTYPE = [
  { to: '/fixtures', label: 'OPA test fixtures' },
  { to: '/notes', label: 'Assumptions & questions' },
  { to: '/sitemap', label: 'Site map' },
];

export function Shell({ children }: { children: ReactNode }) {
  // Scroll to top when the page changes, but not when switching tabs within a flight.
  const section = useLocation().pathname.split('/').slice(0, 3).join('/');
  useEffect(() => { window.scrollTo({ top: 0 }); }, [section]);
  return (
    <div className="app">
      <Sidebar />
      <div className="main">
        <Topbar />
        <main className="content">{children}</main>
      </div>
    </div>
  );
}

function Sidebar() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  return (
    <aside className="side">
      <button className="brand" onClick={() => navigate('/flights')} aria-label="QAR Flight Analytics home"><BrandMark />QAR</button>
      <div className="brand-sub">FLIGHT ANALYTICS</div>
      <div className="nav-label">EXPLORE</div>
      <nav className="nav" aria-label="Main">
        {NAV.map(n => (
          <NavLink key={n.to} to={n.to} className={({ isActive }) => (isActive ? 'on' : '')}>
            <span className="ic" aria-hidden="true">{n.icon}</span>{n.label}
          </NavLink>
        ))}
      </nav>
      <div className="side-foot">
        <div className="nav-label">PROTOTYPE</div>
        {PROTOTYPE.map(p => <NavLink key={p.to} to={p.to} className={({ isActive }) => `side-link ${isActive ? 'on' : ''}`}>{p.label}</NavLink>)}
        <span className="nav-chip">{pathname === '/fixtures' ? 'POC · OPA test fixtures' : 'POC · Sample + demo'}</span>
        <div className="side-note">Historical recordings only</div>
      </div>
    </aside>
  );
}

const TITLES: Record<string, string> = {
  '/flights': 'Flight Explorer', '/cockpit': 'Cockpit & Sensor Playback', '/sql': 'SQL Workspace', '/reports': 'Gold Reports',
  '/fixtures': 'OPA test fixtures / Query permissions', '/notes': 'Assumptions & questions', '/sitemap': 'Site map',
};

function Crumbs() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { details } = useAppState();
  const m = matchPath('/flights/:id/:tab?', pathname);
  if (!m) return <>{TITLES[pathname] ?? ''}</>;

  const id = m.params.id ?? '';
  const flights = <button onClick={() => navigate('/flights')}>Flights</button>;
  const f = flightBy(id);
  if (!f) {
    // Live flight: name it once its detail has loaded.
    const d = details[id];
    const live = d?.status === 'ready' ? d.data.flight : null;
    return <>{flights}<span className="sep">/</span><span>{live ? live.flight_no || live.flight_id : 'Flight details'}</span></>;
  }
  const phase = phaseBy(params.get('phase') ?? 'cruise');
  return (
    <>
      {flights}<span className="sep">/</span>
      {m.params.tab === 'phases' && f.verified && phase
        ? <><button onClick={() => navigate(`/flights/${f.no}`)}>{f.no}</button><span className="sep">/</span><span>{phase.label}</span></>
        : <span>{f.no}</span>}
    </>
  );
}

// Who is signed in and with which role. The role comes from the identity provider,
// so there is nothing to switch here.
function Topbar() {
  const me = useMe();
  return (
    <header className="top">
      <div className="crumbs"><Crumbs /></div>
      <div className="top-right">
        <span className="utc" title="All timestamps and playback are UTC">UTC</span>
        <span className={`idbtn ${me.role ? 'alt' : ''}`} title={me.scope ?? 'No dashboard role assigned'}>
          <span>Signed in: <b>{me.user}</b> · {me.role_label ?? 'No role'}</span>
        </span>
        <a className="btn" href="/logout">Sign out</a>
      </div>
    </header>
  );
}
