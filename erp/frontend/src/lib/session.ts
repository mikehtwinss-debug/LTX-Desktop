/**
 * Browser session store: the access token and the active company live in localStorage so that they
 * survive reloads and are shared between tabs. React subscribes through `subscribeSession`.
 */

const TOKEN_KEY = 'erp.token';
const COMPANY_KEY = 'erp.company';

const listeners = new Set<() => void>();

function notify(): void {
  listeners.forEach((listener) => listener());
}

function write(key: string, value: string | null): void {
  if (value === null) {
    localStorage.removeItem(key);
  } else {
    localStorage.setItem(key, value);
  }
  notify();
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  write(TOKEN_KEY, token);
}

export function getCompanyId(): number | null {
  const raw = localStorage.getItem(COMPANY_KEY);
  const id = raw === null ? NaN : Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}

export function setCompanyId(companyId: number | null): void {
  write(COMPANY_KEY, companyId === null ? null : String(companyId));
}

/** Subscribes to session changes made in this tab or in another one. Returns the unsubscribe function. */
export function subscribeSession(listener: () => void): () => void {
  const onStorage = (event: StorageEvent): void => {
    if (event.key === null || event.key === TOKEN_KEY || event.key === COMPANY_KEY) {
      listener();
    }
  };
  listeners.add(listener);
  window.addEventListener('storage', onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener('storage', onStorage);
  };
}
