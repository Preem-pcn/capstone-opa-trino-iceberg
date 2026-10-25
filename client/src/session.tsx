import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { ApiError, fetchMe, type Me } from './api';

export type SessionState =
  | { status: 'loading' }
  | { status: 'signedOut' }
  | { status: 'error' }
  | { status: 'ready'; me: Me };

interface Session {
  state: SessionState;
  reload(): void;
  // An API answered 401: the backend session ended, so show sign-in again.
  expire(): void;
}

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: 'loading' });

  const reload = useCallback(() => {
    setState({ status: 'loading' });
    fetchMe().then(
      me => setState({ status: 'ready', me }),
      (e: unknown) => setState({ status: e instanceof ApiError && e.status === 401 ? 'signedOut' : 'error' }),
    );
  }, []);
  useEffect(reload, [reload]);

  const expire = useCallback(() => setState({ status: 'signedOut' }), []);
  const value = useMemo(() => ({ state, reload, expire }), [state, reload, expire]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const s = useContext(SessionContext);
  if (!s) throw new Error('useSession outside SessionProvider');
  return s;
}

// For components behind the sign-in gate, where a user with a role exists.
export function useMe() {
  const s = useSession();
  if (s.state.status !== 'ready') throw new Error('useMe outside the sign-in gate');
  return s.state.me;
}
