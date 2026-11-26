import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
} from 'react';

import { api, ApiError, apiGet, apiPost } from '@/lib/api';
import { getCompanyId, getToken, setCompanyId, setToken, subscribeSession } from '@/lib/session';
import type { LoginResponse, Me } from '@/lib/types';

import { PATHS } from './paths';

export type AuthStatus = 'loading' | 'anonymous' | 'authenticated' | 'error';

interface AuthContextValue {
  status: AuthStatus;
  /** The signed-in user in the active company; `null` unless the status is `authenticated`. */
  me: Me | null;
  /** Why the session could not be loaded (status `error`). */
  error: unknown;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  switchCompany: (companyId: number) => Promise<void>;
  reloadMe: () => Promise<void>;
}

const ME_KEY = ['auth', 'me'] as const;

const AuthContext = createContext<AuthContextValue | null>(null);

const COMPANY_REJECTED = new Set(['COMPANY_ACCESS_DENIED', 'INVALID_COMPANY']);

async function fetchMe(signal: AbortSignal): Promise<Me> {
  try {
    return await apiGet<Me>('/auth/me', undefined, signal);
  } catch (error) {
    // The remembered company is no longer open to this user: fall back to the default company.
    if (error instanceof ApiError && COMPANY_REJECTED.has(error.code) && getCompanyId() !== null) {
      setCompanyId(null);
      return apiGet<Me>('/auth/me', undefined, signal);
    }
    throw error;
  }
}

export function AuthProvider({ children }: { children: ReactNode }): ReactNode {
  const queryClient = useQueryClient();
  const token = useSyncExternalStore(subscribeSession, getToken);

  const meQuery = useQuery({
    queryKey: ME_KEY,
    queryFn: ({ signal }) => fetchMe(signal),
    enabled: token !== null,
    staleTime: Infinity,
  });
  const me = token !== null ? (meQuery.data ?? null) : null;

  // Nothing cached may outlive the session, whether it ended here, in another tab or by expiry.
  useEffect(() => {
    if (token === null) {
      queryClient.clear();
    }
  }, [token, queryClient]);

  // Requests must name the company the server actually resolved (first login, fallback).
  useEffect(() => {
    if (me !== null && getCompanyId() !== me.company_id) {
      setCompanyId(me.company_id);
    }
  }, [me]);

  const login = useCallback(
    async (username: string, password: string) => {
      const { access_token: accessToken, user } = await apiPost<LoginResponse>('/auth/login', { username, password });
      const remembered = getCompanyId();
      const resumeRemembered =
        remembered !== null && remembered !== user.company_id && user.companies.some((c) => c.id === remembered);
      // The login answer describes the default company. It is used as is unless the user last
      // worked in another company, in which case the me query loads that one.
      if (!resumeRemembered) {
        setCompanyId(user.company_id);
        queryClient.setQueryData(ME_KEY, user);
      }
      setToken(accessToken);
    },
    [queryClient],
  );

  const logout = useCallback(() => {
    setToken(null);
    // A full page load guarantees that no in-memory state of the session survives.
    window.location.assign(PATHS.login);
  }, []);

  const switchCompany = useCallback(
    async (companyId: number) => {
      const response = await api.get<Me>('/auth/me', { headers: { 'X-Company-Id': String(companyId) } });
      setCompanyId(companyId);
      // Everything cached so far belongs to the previous company.
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== ME_KEY[0] });
      queryClient.setQueryData(ME_KEY, response.data);
    },
    [queryClient],
  );

  const reloadMe = useCallback(() => queryClient.invalidateQueries({ queryKey: ME_KEY }), [queryClient]);

  const value = useMemo<AuthContextValue>(() => {
    const status: AuthStatus =
      token === null ? 'anonymous' : me !== null ? 'authenticated' : meQuery.isError ? 'error' : 'loading';
    return { status, me, error: meQuery.error, login, logout, switchCompany, reloadMe };
  }, [token, me, meQuery.isError, meQuery.error, login, logout, switchCompany, reloadMe]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (value === null) {
    throw new Error('useAuth must be used inside <AuthProvider>');
  }
  return value;
}

/** The signed-in user; for components that only render below the authentication guard. */
export function useMe(): Me {
  const { me } = useAuth();
  if (me === null) {
    throw new Error('useMe must be used below <RequireAuth>');
  }
  return me;
}
