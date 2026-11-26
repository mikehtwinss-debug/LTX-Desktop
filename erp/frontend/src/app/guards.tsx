import { Button, Result, Space, Spin } from 'antd';
import type { ReactNode } from 'react';
import { Navigate, Outlet, useLocation, useMatches } from 'react-router-dom';

import { errorMessage } from '@/lib/api';
import { hasPermission } from '@/lib/permissions';

import { useAuth, useMe } from './AuthProvider';
import { requiredPermission } from './menu';
import { ForbiddenPage } from './pages/ForbiddenPage';
import { PATHS } from './paths';
import { menuEntries } from './registry';

/** Location state the login page uses to return to the page that required authentication. */
export interface LoginRedirectState {
  from: string;
}

/**
 * Gate of every authenticated route: anonymous visitors go to the login page, users who must
 * change their password can open nothing else, and the subtree is remounted when the active
 * company changes so that no page keeps state of the previous company.
 */
export function RequireAuth(): ReactNode {
  const { status, me, error, logout, reloadMe } = useAuth();
  const location = useLocation();

  if (status === 'anonymous') {
    const state: LoginRedirectState = { from: `${location.pathname}${location.search}` };
    return <Navigate to={PATHS.login} replace state={state} />;
  }
  if (status === 'error') {
    return (
      <Result
        status="error"
        title="Oturum bilgileri alınamadı"
        subTitle={errorMessage(error)}
        extra={
          <Space>
            <Button type="primary" onClick={() => void reloadMe()}>
              Tekrar dene
            </Button>
            <Button onClick={logout}>Çıkış yap</Button>
          </Space>
        }
      />
    );
  }
  if (me === null) {
    return <Spin fullscreen />;
  }
  if (me.must_change_password && location.pathname !== PATHS.changePassword) {
    return <Navigate to={PATHS.changePassword} replace />;
  }
  return <Outlet key={me.company_id} />;
}

/** Renders the matched page, or the 403 page when the user lacks the permission it requires. */
export function PermissionOutlet(): ReactNode {
  const me = useMe();
  const matches = useMatches();
  const { pathname } = useLocation();
  const permission = requiredPermission(
    matches.map((match) => match.handle),
    pathname,
    menuEntries,
  );
  return hasPermission(me, permission) ? <Outlet /> : <ForbiddenPage />;
}
