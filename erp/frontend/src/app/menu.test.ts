import { describe, expect, it } from 'vitest';

import { buildMenu, findActiveEntry, requiredPermission } from './menu';
import { collectFeatures, type FeatureModule, type MenuEntry } from './registry';

const entries: MenuEntry[] = [
  { key: 'mm.po', label: 'Siparişler', path: '/mm/siparis', group: 'malzeme', section: 'Satınalma', permission: 'mm.po.view', order: 20 },
  { key: 'mm.pr', label: 'Talepler', path: '/mm/talep', group: 'malzeme', section: 'Satınalma', permission: 'mm.pr.view', order: 10 },
  { key: 'mm.material', label: 'Malzemeler', path: '/mm/malzeme', group: 'malzeme', order: 1 },
  { key: 'mm.stock', label: 'Stok Durumu', path: '/mm/stok', group: 'malzeme', section: 'Stok', permission: 'mm.stock.view', order: 5 },
  { key: 'fi.journal', label: 'Yevmiye Fişleri', path: '/fi/fis', group: 'finans', permission: 'fi.journal.view' },
  { key: 'fi.accounts', label: 'Hesap Planı', path: '/fi/hesap', group: 'finans' },
  { key: 'fi.report', label: 'Çek Raporu', path: '/fi/rapor', group: 'finans' },
  { key: 'org.users', label: 'Kullanıcılar', path: '/yonetim/kullanici', group: 'yonetim', permission: 'auth.user.view' },
];

const allow = (): boolean => true;
const allowOnly =
  (...granted: string[]) =>
  (permission?: string): boolean =>
    permission === undefined || granted.includes(permission);

describe('buildMenu', () => {
  it('returns the fixed groups in their fixed order', () => {
    expect(buildMenu(entries, allow).map((group) => [group.key, group.label])).toEqual([
      ['finans', 'Finans'],
      ['malzeme', 'Malzeme Yönetimi'],
      ['yonetim', 'Yönetim'],
    ]);
  });

  it('orders entries by position, then by label in Turkish collation', () => {
    const finans = buildMenu(entries, allow)[0];
    expect(finans?.entries.map((entry) => entry.label)).toEqual(['Çek Raporu', 'Hesap Planı', 'Yevmiye Fişleri']);
  });

  it('splits a group into direct entries and sections ordered by their first entry', () => {
    const malzeme = buildMenu(entries, allow)[1];
    expect(malzeme?.entries.map((entry) => entry.key)).toEqual(['mm.material']);
    expect(malzeme?.sections).toEqual([
      { title: 'Stok', entries: [entries[3]] },
      { title: 'Satınalma', entries: [entries[1], entries[0]] },
    ]);
  });

  it('hides entries without permission and drops empty sections and groups', () => {
    const menu = buildMenu(entries, allowOnly('mm.pr.view'));
    expect(menu.map((group) => group.key)).toEqual(['finans', 'malzeme']);
    expect(menu[0]?.entries.map((entry) => entry.key)).toEqual(['fi.report', 'fi.accounts']);
    expect(menu[1]?.sections).toEqual([{ title: 'Satınalma', entries: [entries[1]] }]);
  });

  it('is empty when no feature is registered', () => {
    expect(buildMenu([], allow)).toEqual([]);
  });
});

describe('findActiveEntry', () => {
  it('matches the entry itself and pages below it', () => {
    expect(findActiveEntry(entries, '/mm/siparis')?.key).toBe('mm.po');
    expect(findActiveEntry(entries, '/mm/siparis/42')?.key).toBe('mm.po');
    expect(findActiveEntry(entries, '/mm/siparis/')?.key).toBe('mm.po');
  });

  it('only matches whole path segments', () => {
    expect(findActiveEntry(entries, '/mm/siparisler')).toBeUndefined();
    expect(findActiveEntry(entries, '/')).toBeUndefined();
  });

  it('prefers the longest matching path and ignores query strings of entries', () => {
    const nested: MenuEntry[] = [
      { key: 'reports', label: 'Raporlar', path: '/mm/rapor', group: 'malzeme' },
      { key: 'aging', label: 'Stok Yaşlandırma', path: '/mm/rapor/yaslandirma?gun=90', group: 'malzeme' },
    ];
    expect(findActiveEntry(nested, '/mm/rapor/yaslandirma')?.key).toBe('aging');
    expect(findActiveEntry(nested, '/mm/rapor/devir')?.key).toBe('reports');
  });
});

describe('requiredPermission', () => {
  it('uses the innermost route handle that declares a permission', () => {
    const handles = [undefined, { permission: 'mm.po.view' }, { title: 'x' }, { permission: 'mm.po.create' }, null];
    expect(requiredPermission(handles, '/mm/siparis/yeni', entries)).toBe('mm.po.create');
  });

  it('falls back to the permission of the menu entry the page lives under', () => {
    expect(requiredPermission([undefined, undefined], '/mm/siparis/42', entries)).toBe('mm.po.view');
  });

  it('requires nothing for pages outside the menu or under an open entry', () => {
    expect(requiredPermission([], '/', entries)).toBeUndefined();
    expect(requiredPermission([], '/fi/hesap/100', entries)).toBeUndefined();
  });
});

describe('collectFeatures', () => {
  const feature = (key: string, menu: MenuEntry[] = []): FeatureModule => ({ key, menu, routes: [] });

  it('works with zero feature modules', () => {
    expect(collectFeatures({})).toEqual([]);
  });

  it('returns the modules ordered by key', () => {
    const features = collectFeatures({
      '../modules/mm.master/index.tsx': { default: feature('mm.master') },
      '../modules/fi.gl/index.tsx': { default: feature('fi.gl') },
    });
    expect(features.map((item) => item.key)).toEqual(['fi.gl', 'mm.master']);
  });

  it('names the file whose default export is not a feature module', () => {
    expect(() => collectFeatures({ '../modules/broken/index.tsx': {} })).toThrow('../modules/broken/index.tsx');
    expect(() => collectFeatures({ '../modules/broken/index.tsx': { default: { key: 'x', menu: [] } } })).toThrow(
      'must default-export a FeatureModule',
    );
  });

  it('rejects duplicate feature and menu keys', () => {
    expect(() => collectFeatures({ a: { default: feature('fi.gl') }, b: { default: feature('fi.gl') } })).toThrow(
      'Duplicate feature key "fi.gl"',
    );
    const entry = entries[0] as MenuEntry;
    expect(() =>
      collectFeatures({ a: { default: feature('a', [entry]) }, b: { default: feature('b', [entry]) } }),
    ).toThrow('Duplicate menu key "mm.po"');
  });
});
