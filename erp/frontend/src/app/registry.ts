import type { RouteObject } from 'react-router-dom';

export type MenuGroupKey = 'finans' | 'malzeme' | 'yonetim';

export interface MenuEntry {
  /** Unique across all features, e.g. `mm.po`. */
  key: string;
  label: string;
  /** Absolute route the entry links to, e.g. `/mm/siparis`. */
  path: string;
  group: MenuGroupKey;
  /** Optional heading inside the group, e.g. `Satınalma`. */
  section?: string;
  /**
   * Permission needed to see the entry. Pages at or below `path` require it as well unless their
   * route declares its own `handle.permission`.
   */
  permission?: string;
  /** Position inside the group or section; entries without it come last, ordered by label. */
  order?: number;
}

/**
 * What `src/modules/<feature>/index.tsx` default-exports. `routes` become children of the
 * authenticated layout and should load their pages lazily (`lazy: () => import('./pages/...')`
 * or `React.lazy`).
 */
export interface FeatureModule {
  key: string;
  menu: MenuEntry[];
  routes: RouteObject[];
}

/** Optional `handle` of a feature route: `handle: { permission: 'mm.po.create' } satisfies RouteHandle`. */
export interface RouteHandle {
  permission?: string;
}

export const MENU_GROUPS: readonly { key: MenuGroupKey; label: string }[] = [
  { key: 'finans', label: 'Finans' },
  { key: 'malzeme', label: 'Malzeme Yönetimi' },
  { key: 'yonetim', label: 'Yönetim' },
];

interface ModuleExports {
  default?: unknown;
}

function isFeatureModule(value: unknown): value is FeatureModule {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const candidate = value as Partial<FeatureModule>;
  return typeof candidate.key === 'string' && Array.isArray(candidate.menu) && Array.isArray(candidate.routes);
}

function assertUnique(kind: string, keys: string[]): void {
  const seen = new Set<string>();
  for (const key of keys) {
    if (seen.has(key)) {
      throw new Error(`Duplicate ${kind} key "${key}" in the feature registry`);
    }
    seen.add(key);
  }
}

/** Validates the modules found by the glob import and returns them in a stable order. */
export function collectFeatures(modules: Record<string, ModuleExports>): FeatureModule[] {
  const features = Object.entries(modules).map(([file, exports]) => {
    if (!isFeatureModule(exports.default)) {
      throw new Error(`${file} must default-export a FeatureModule ({ key, menu, routes })`);
    }
    return exports.default;
  });
  assertUnique('feature', features.map((feature) => feature.key));
  assertUnique('menu', features.flatMap((feature) => feature.menu.map((entry) => entry.key)));
  return features.sort((a, b) => a.key.localeCompare(b.key));
}

export const features: FeatureModule[] = collectFeatures(
  import.meta.glob<ModuleExports>('../modules/*/index.tsx', { eager: true }),
);

export const menuEntries: MenuEntry[] = features.flatMap((feature) => feature.menu);

export const featureRoutes: RouteObject[] = features.flatMap((feature) => feature.routes);
