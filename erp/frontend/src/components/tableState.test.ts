import { describe, expect, it } from 'vitest';

import { initialTableState, readTableState, type TableStateConfig, writeTableState } from './tableState';

const config: TableStateConfig = {
  prefix: '',
  defaultPageSize: 50,
  filterNames: ['status', 'vendor_id'],
  multiValued: ['status'],
};

describe('readTableState', () => {
  it('returns the defaults for an empty query string', () => {
    expect(readTableState(new URLSearchParams(), config)).toEqual(initialTableState(config));
    expect(initialTableState(config)).toEqual({ page: 1, pageSize: 50, sort: undefined, q: '', filters: {} });
  });

  it('reads paging, sorting, search and declared filters', () => {
    const search = new URLSearchParams('page=3&page_size=100&sort=-order_date&q=sac&status=DRAFT&status=APPROVED&vendor_id=7');
    expect(readTableState(search, config)).toEqual({
      page: 3,
      pageSize: 100,
      sort: '-order_date',
      q: 'sac',
      filters: { status: ['DRAFT', 'APPROVED'], vendor_id: '7' },
    });
  });

  it('ignores invalid numbers, caps the page size and skips unknown keys', () => {
    const state = readTableState(new URLSearchParams('page=-2&page_size=99999&tab=lines&vendor_id='), config);
    expect(state).toEqual({ page: 1, pageSize: 500, sort: undefined, q: '', filters: {} });
    expect(readTableState(new URLSearchParams('page=abc&page_size=1.5'), config).pageSize).toBe(50);
  });

  it('honours the key prefix', () => {
    const prefixed = { ...config, prefix: 'po_' };
    const state = readTableState(new URLSearchParams('page=4&po_page=2&po_status=DRAFT'), prefixed);
    expect(state.page).toBe(2);
    expect(state.filters).toEqual({ status: ['DRAFT'] });
  });
});

describe('writeTableState', () => {
  it('leaves defaults out of the URL', () => {
    expect(writeTableState(new URLSearchParams(), initialTableState(config), config).toString()).toBe('');
  });

  it('writes the state and round-trips through readTableState', () => {
    const state = { page: 2, pageSize: 20, sort: 'number', q: 'çelik sac', filters: { status: ['DRAFT', 'APPROVED'], vendor_id: '7' } };
    const written = writeTableState(new URLSearchParams(), state, config);
    expect(written.getAll('status')).toEqual(['DRAFT', 'APPROVED']);
    expect(written.get('q')).toBe('çelik sac');
    expect(readTableState(written, config)).toEqual(state);
  });

  it('replaces its own keys and preserves foreign ones', () => {
    const before = new URLSearchParams('tab=lines&page=5&status=DRAFT&q=eski');
    const after = writeTableState(before, { ...initialTableState(config), filters: { vendor_id: '3' } }, config);
    expect(after.toString()).toBe('tab=lines&vendor_id=3');
    expect(before.get('page')).toBe('5');
  });
});
