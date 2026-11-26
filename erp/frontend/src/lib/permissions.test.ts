import { describe, expect, it } from 'vitest';

import { hasPermission } from './permissions';

const buyer = { is_superuser: false, permissions: ['mm.po.view', 'mm.po.create'] };

describe('hasPermission', () => {
  it('checks the permission keys of the active company', () => {
    expect(hasPermission(buyer, 'mm.po.create')).toBe(true);
    expect(hasPermission(buyer, 'mm.po.approve')).toBe(false);
  });

  it('lets superusers pass every check', () => {
    expect(hasPermission({ is_superuser: true, permissions: [] }, 'fi.journal.post')).toBe(true);
  });

  it('treats a missing requirement as satisfied', () => {
    expect(hasPermission(buyer, undefined)).toBe(true);
    expect(hasPermission(null, undefined)).toBe(true);
  });

  it('denies everything to an anonymous visitor', () => {
    expect(hasPermission(null, 'mm.po.view')).toBe(false);
  });
});
