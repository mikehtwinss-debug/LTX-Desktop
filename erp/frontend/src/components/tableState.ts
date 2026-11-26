/** State of a server-side table and its representation in the URL query string. */

export type FilterValue = string | string[];

export interface TableState {
  page: number;
  pageSize: number;
  /** Sort name, `-` prefixed for descending; `undefined` means the table's default order. */
  sort: string | undefined;
  q: string;
  /** Active filters by parameter name. Empty filters are absent. */
  filters: Record<string, FilterValue>;
}

export interface TableStateConfig {
  /** Prefix of the query-string keys, for pages that show more than one table. */
  prefix: string;
  defaultPageSize: number;
  /** Parameter names of the declared filters; other query-string keys are left alone. */
  filterNames: readonly string[];
  /** Filters that may hold several values (repeated keys). */
  multiValued: readonly string[];
}

export const MAX_PAGE_SIZE = 500;

function positiveInt(raw: string | null, fallback: number, max = Number.MAX_SAFE_INTEGER): number {
  const value = Number(raw);
  return raw !== null && Number.isInteger(value) && value > 0 ? Math.min(value, max) : fallback;
}

export function initialTableState(config: TableStateConfig): TableState {
  return { page: 1, pageSize: config.defaultPageSize, sort: undefined, q: '', filters: {} };
}

export function readTableState(search: URLSearchParams, config: TableStateConfig): TableState {
  const key = (name: string): string => `${config.prefix}${name}`;
  const filters: Record<string, FilterValue> = {};
  for (const name of config.filterNames) {
    const values = search.getAll(key(name)).filter((value) => value !== '');
    if (values.length === 0) {
      continue;
    }
    filters[name] = config.multiValued.includes(name) ? values : (values[0] ?? '');
  }
  return {
    page: positiveInt(search.get(key('page')), 1),
    pageSize: positiveInt(search.get(key('page_size')), config.defaultPageSize, MAX_PAGE_SIZE),
    sort: search.get(key('sort')) || undefined,
    q: search.get(key('q')) ?? '',
    filters,
  };
}

/** Returns a copy of `search` with the table's keys replaced; defaults are left out to keep URLs short. */
export function writeTableState(search: URLSearchParams, state: TableState, config: TableStateConfig): URLSearchParams {
  const key = (name: string): string => `${config.prefix}${name}`;
  const next = new URLSearchParams(search);
  ['page', 'page_size', 'sort', 'q', ...config.filterNames].forEach((name) => next.delete(key(name)));

  if (state.page > 1) {
    next.set(key('page'), String(state.page));
  }
  if (state.pageSize !== config.defaultPageSize) {
    next.set(key('page_size'), String(state.pageSize));
  }
  if (state.sort) {
    next.set(key('sort'), state.sort);
  }
  if (state.q) {
    next.set(key('q'), state.q);
  }
  for (const name of config.filterNames) {
    const value = state.filters[name];
    const values = value === undefined ? [] : Array.isArray(value) ? value : [value];
    values.filter((item) => item !== '').forEach((item) => next.append(key(name), item));
  }
  return next;
}
