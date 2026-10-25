import { Navigate, Route, Routes } from 'react-router-dom';
import { Shell } from './components/Shell';
import { Cockpit } from './pages/Cockpit';
import { Explorer } from './pages/Explorer';
import { FlightDetail } from './pages/FlightDetail';
import { BackendError, Loading, NoAccess, SignIn } from './pages/Gate';
import { Reports } from './pages/Reports';
import { SqlWorkspace } from './pages/SqlWorkspace';
import { SessionProvider, useSession } from './session';
import { AppStateProvider } from './state';
import { ToastProvider } from './toasts';

export function App() {
  return (
    <ToastProvider>
      <SessionProvider>
        <Gate />
      </SessionProvider>
    </ToastProvider>
  );
}

// Nothing past this point renders without a signed-in user who has a dashboard role.
function Gate() {
  const { state } = useSession();
  if (state.status === 'loading') return <Loading />;
  if (state.status === 'signedOut') return <SignIn />;
  if (state.status === 'error') return <BackendError />;
  if (!state.me.role) return <NoAccess user={state.me.user} />;
  return (
    <AppStateProvider>
      <Shell>
        <Routes>
          <Route path="/" element={<Navigate to="/flights" replace />} />
          <Route path="/flights" element={<Explorer />} />
          <Route path="/flights/:id" element={<FlightDetail />} />
          <Route path="/flights/:id/:tab" element={<FlightDetail />} />
          <Route path="/cockpit" element={<Cockpit />} />
          <Route path="/sql" element={<SqlWorkspace />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="*" element={<Navigate to="/flights" replace />} />
        </Routes>
      </Shell>
    </AppStateProvider>
  );
}
