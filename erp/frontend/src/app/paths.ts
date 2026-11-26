/** Routes owned by the application shell. */
export const PATHS = {
  home: '/',
  login: '/giris',
  changePassword: '/sifre-degistir',
  /** Approval inbox; the page itself is registered by the feature module that owns approvals. */
  approvals: '/onaylar',
} as const;
