import { MENU_GROUPS, type MenuEntry, type MenuGroupKey } from './registry';

export interface MenuSection {
  title: string;
  entries: MenuEntry[];
}

export interface MenuGroup {
  key: MenuGroupKey;
  label: string;
  /** Entries placed directly in the group, shown before its sections. */
  entries: MenuEntry[];
  sections: MenuSection[];
}

const collator = new Intl.Collator('tr');

function position(entry: MenuEntry): number {
  return entry.order ?? Number.MAX_SAFE_INTEGER;
}

function byOrder(a: MenuEntry, b: MenuEntry): number {
  return position(a) - position(b) || collator.compare(a.label, b.label);
}

/**
 * Arranges the registered entries into the fixed groups. Entries the user may not see are left
 * out, and so are sections and groups that end up empty. A section takes the position of its
 * first entry.
 */
export function buildMenu(entries: readonly MenuEntry[], can: (permission?: string) => boolean): MenuGroup[] {
  const visible = entries.filter((entry) => can(entry.permission));

  return MENU_GROUPS.map(({ key, label }) => {
    const inGroup = visible.filter((entry) => entry.group === key).sort(byOrder);
    const sections = new Map<string, MenuEntry[]>();
    for (const entry of inGroup) {
      if (entry.section) {
        sections.set(entry.section, [...(sections.get(entry.section) ?? []), entry]);
      }
    }
    return {
      key,
      label,
      entries: inGroup.filter((entry) => !entry.section),
      sections: [...sections].map(([title, sectionEntries]) => ({ title, entries: sectionEntries })),
    };
  }).filter((group) => group.entries.length > 0 || group.sections.length > 0);
}

function pathnameOf(path: string): string {
  const pathname = path.split(/[?#]/)[0] ?? '';
  return pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname;
}

/** The entry whose path is the longest prefix of `pathname` (whole segments only). */
export function findActiveEntry(entries: readonly MenuEntry[], pathname: string): MenuEntry | undefined {
  const current = pathnameOf(pathname);
  let best: MenuEntry | undefined;
  let bestLength = 0;
  for (const entry of entries) {
    const base = pathnameOf(entry.path);
    const matches = current === base || current.startsWith(base === '/' ? base : `${base}/`);
    if (matches && base.length > bestLength) {
      best = entry;
      bestLength = base.length;
    }
  }
  return best;
}

/**
 * Permission a location requires: the innermost `handle.permission` of the matched routes, or
 * else the permission of the menu entry the page lives under.
 */
export function requiredPermission(
  handles: readonly unknown[],
  pathname: string,
  entries: readonly MenuEntry[],
): string | undefined {
  for (let index = handles.length - 1; index >= 0; index -= 1) {
    const handle = handles[index];
    if (typeof handle === 'object' && handle !== null && 'permission' in handle) {
      const { permission } = handle;
      if (typeof permission === 'string') {
        return permission;
      }
    }
  }
  return findActiveEntry(entries, pathname)?.permission;
}
