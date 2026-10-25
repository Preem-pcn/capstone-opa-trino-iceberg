import { useEffect, type ReactNode } from 'react';
import { NavLink, matchPath, useLocation, useNavigate } from 'react-router-dom';
import { useMe } from '../session';
import { useAppState } from '../state';
import { BrandMark } from './common';

const NAV = [
  { to: '/flights', label: 'Flight Explorer', icon: '⌕' },
  { to: '/cockpit', label: 'Sensor Playback', icon: '◉' },
  { to: '/sql', label: 'SQL Workspace', icon: '⌘' },
  { to: '/reports', label: 'Flight Reports', icon: '▤' },
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
      <div className="side-foot"><div className="side-note">QAR Flight Analytics<br />All times in UTC</div></div>
    </aside>
  );
}

const TITLES: Record<string, string> = {
  '/flights': 'Flight Explorer', '/cockpit': 'Sensor Playback', '/sql': 'SQL Workspace', '/reports': 'Flight Reports',
};

function Crumbs() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { details } = useAppState();
  const m = matchPath('/flights/:id/:tab?', pathname);
  if (!m) return <>{TITLES[pathname] ?? ''}</>;

  const id = m.params.id ?? '';
  const flights = <button onClick={() => navigate('/flights')}>Flights</button>;
  const d = details[id];
  const live = d?.status === 'ready' ? d.data.flight : null;
  const label = live?.flight_no && live.flight_no !== 'REDACTED' ? live.flight_no : live ? `${live.tail} · ${live.flight_date}` : 'Flight details';
  return <>{flights}<span className="sep">/</span><span>{label}</span></>;
}

// The backend resolves the role from the verified identity. It cannot be switched in the client.
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
