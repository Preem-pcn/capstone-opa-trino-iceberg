import type { ReactNode } from 'react';
import { signIn } from '../api';
import { BrandMark } from '../components/common';
import { useSession } from '../session';

// Screens shown before the app: checking, signed out, backend down, or no dashboard role.

function GateCard({ children }: { children: ReactNode }) {
  return (
    <div className="gate">
      <div className="gate-card">
        <div className="gate-brand"><BrandMark color="var(--accent)" />QAR Flight Analytics</div>
        {children}
      </div>
    </div>
  );
}

export function Loading() {
  return <GateCard><p className="row"><span className="spinner" aria-hidden="true" /> Checking your session…</p></GateCard>;
}

export function SignIn() {
  return (
    <GateCard>
      <h1>Sign in</h1>
      <p>Sign in with your Google account. What you can see depends on the role assigned to that account.</p>
      <button className="btn primary" style={{ alignSelf: 'flex-start' }} onClick={signIn}>Sign in</button>
    </GateCard>
  );
}

export function BackendError() {
  const { reload } = useSession();
  return (
    <GateCard>
      <h1>Service unavailable</h1>
      <p>We couldn't reach the sign-in service. Please try again in a moment.</p>
      <button className="btn" style={{ alignSelf: 'flex-start' }} onClick={reload}>Try again</button>
    </GateCard>
  );
}

// The backend grants data only for exactly one known role; with none or several,
// every data API answers 403, so there is nothing to show.
export function NoAccess({ user }: { user: string }) {
  return (
    <GateCard>
      <h1>Access not assigned</h1>
      <p>You're signed in as <span className="mono">{user}</span>. Ask your administrator to assign access to flight analytics.</p>
      <a className="btn" style={{ alignSelf: 'flex-start' }} href="/logout">Sign out</a>
    </GateCard>
  );
}
