import type { ReactNode } from 'react';

import { useAuth } from '@/app/AuthProvider';

import type { Me } from './types';

/** Superusers pass every check; an empty requirement is always satisfied. */
export function hasPermission(me: Pick<Me, 'is_superuser' | 'permissions'> | null, permission?: string): boolean {
  if (!permission) {
    return true;
  }
  return me !== null && (me.is_superuser || me.permissions.includes(permission));
}

/** `const canCreate = useCan('mm.po.create');` — permission of the signed-in user in the active company. */
export function useCan(permission?: string): boolean {
  return hasPermission(useAuth().me, permission);
}

interface CanProps {
  permission: string;
  children: ReactNode;
  /** Rendered instead of the children when the permission is missing. */
  fallback?: ReactNode;
}

/** `<Can permission="mm.po.approve"><Button>Onayla</Button></Can>` */
export function Can({ permission, children, fallback = null }: CanProps): ReactNode {
  return useCan(permission) ? children : fallback;
}
