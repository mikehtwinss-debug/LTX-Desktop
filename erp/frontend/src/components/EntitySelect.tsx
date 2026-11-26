import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import { Select, type SelectProps, Spin, Typography } from 'antd';
import { type ReactNode, useState } from 'react';

import { errorMessage, getList, getOne, type QueryParams } from '@/lib/api';
import { queryKeys } from '@/lib/queryClient';
import { useDebouncedValue } from '@/lib/useDebouncedValue';

const PAGE_SIZE = 25;
const SEARCH_DELAY_MS = 300;
const OPTION_STALE_MS = 5 * 60_000;

export interface EntitySelectProps<Item extends { id: number }>
  extends Pick<
    SelectProps,
    'id' | 'placeholder' | 'disabled' | 'allowClear' | 'size' | 'status' | 'variant' | 'style' | 'autoFocus' | 'onBlur'
  > {
  /** List endpoint relative to `/api`, e.g. `/fi/vendors`. The item itself is read from `<endpoint>/<id>`. */
  endpoint: string;
  value?: number | null;
  /** Receives the id and, when it is known, the selected item (to fill dependent fields). */
  onChange?: (value: number | null, item: Item | null) => void;
  /** Label of an item in the dropdown and as the selected value. */
  getLabel: (item: Item) => ReactNode;
  /** Additional list parameters, e.g. `{ is_active: true }`. */
  params?: QueryParams;
}

/**
 * Select box that searches a list endpoint on the server (`q`), for master data of any size.
 * The label of the current value is loaded by id when it is not among the search results.
 *
 *   <Form.Item name="vendor_id" label="Satıcı">
 *     <EntitySelect<Vendor> endpoint="/fi/vendors" getLabel={(v) => `${v.code} — ${v.name}`} params={{ is_blocked: false }} />
 *   </Form.Item>
 */
export function EntitySelect<Item extends { id: number }>({
  endpoint,
  value,
  onChange,
  getLabel,
  params,
  allowClear = true,
  placeholder = 'Seçin',
  style,
  ...selectProps
}: EntitySelectProps<Item>): ReactNode {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const q = useDebouncedValue(search, SEARCH_DELAY_MS);
  const selectedId = value ?? null;

  const listParams = { ...params, q, page_size: PAGE_SIZE };
  const list = useQuery({
    queryKey: queryKeys.list(endpoint, listParams),
    queryFn: ({ signal }) => getList<Item>(endpoint, listParams, signal),
    enabled: open,
    placeholderData: keepPreviousData,
  });
  const items = list.data?.items ?? [];
  const listed = selectedId === null ? undefined : items.find((item) => item.id === selectedId);

  // Kept apart from the detail queries of the resource, whose payload may be richer than a list row.
  const optionKey = (id: number) => [...queryKeys.all(endpoint), 'option', id] as const;
  const current = useQuery({
    queryKey: optionKey(selectedId ?? 0),
    queryFn: ({ signal }) => getOne<Item>(endpoint, selectedId ?? 0, signal),
    enabled: selectedId !== null && listed === undefined,
    staleTime: OPTION_STALE_MS,
  });
  const selected = listed ?? (selectedId !== null ? current.data : undefined);

  const options = items.map((item) => ({ value: item.id, label: getLabel(item) }));
  if (selectedId !== null && listed === undefined) {
    const label = selected ? getLabel(selected) : current.isError ? `#${selectedId}` : 'Yükleniyor…';
    options.unshift({ value: selectedId, label });
  }

  const handleChange = (next: number | undefined): void => {
    const item = next === undefined ? null : (items.find((candidate) => candidate.id === next) ?? null);
    if (item !== null) {
      queryClient.setQueryData(optionKey(item.id), item);
    }
    onChange?.(next ?? null, item);
  };

  const notFound = list.isError ? (
    <Typography.Text type="danger">{errorMessage(list.error)}</Typography.Text>
  ) : list.isFetching || search !== q ? (
    <Spin size="small" />
  ) : (
    'Kayıt bulunamadı'
  );
  const hiddenCount = (list.data?.total ?? 0) - items.length;

  return (
    <Select<number>
      {...selectProps}
      style={{ width: '100%', ...style }}
      showSearch
      filterOption={false}
      allowClear={allowClear}
      placeholder={placeholder}
      value={selectedId ?? undefined}
      options={options}
      loading={list.isFetching || current.isFetching}
      notFoundContent={notFound}
      popupMatchSelectWidth={false}
      onSearch={setSearch}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        if (!nextOpen) {
          setSearch('');
        }
      }}
      onChange={handleChange}
      popupRender={(menu) => (
        <>
          {menu}
          {hiddenCount > 0 && (
            <Typography.Text type="secondary" style={{ display: 'block', padding: '4px 12px', fontSize: 12 }}>
              {hiddenCount} kayıt daha var; daraltmak için yazmaya devam edin.
            </Typography.Text>
          )}
        </>
      )}
    />
  );
}
