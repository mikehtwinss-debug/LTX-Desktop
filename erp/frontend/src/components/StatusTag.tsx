import { Tag, type TagProps } from 'antd';
import type { ReactNode } from 'react';

export interface StatusMeta {
  label: string;
  color?: TagProps['color'];
}

/** Turkish label and tag colour for every key of a status enum. */
export type StatusMap<Key extends string = string> = Record<Key, StatusMeta>;

export interface StatusTagProps<Key extends string> {
  map: StatusMap<Key>;
  value: Key | null | undefined;
}

/**
 * Coloured label of an enum value.
 *
 *   const PO_STATUS: StatusMap<PoStatus> = {
 *     DRAFT: { label: 'Taslak', color: 'default' },
 *     APPROVED: { label: 'Onaylandı', color: 'green' },
 *   };
 *   <StatusTag map={PO_STATUS} value={order.status} />
 */
export function StatusTag<Key extends string>({ map, value }: StatusTagProps<Key>): ReactNode {
  if (value === null || value === undefined) {
    return null;
  }
  // A newer backend may send keys this build does not know yet; show them raw instead of nothing.
  const meta: StatusMeta | undefined = map[value];
  return (
    <Tag color={meta?.color} style={{ marginInlineEnd: 0 }}>
      {meta?.label ?? value}
    </Tag>
  );
}
