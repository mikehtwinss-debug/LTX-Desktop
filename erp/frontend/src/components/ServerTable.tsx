import { ClearOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { Alert, Button, DatePicker, Empty, Flex, Input, Select, Table, type TableProps, Tooltip } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import {
  type Key,
  type MouseEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import { useSearchParams } from 'react-router-dom';

import { errorMessage, getList, type QueryParams } from '@/lib/api';
import { queryKeys } from '@/lib/queryClient';

import { DateInput } from './DateInput';
import { EntitySelect } from './EntitySelect';
import {
  type FilterValue,
  initialTableState,
  MAX_PAGE_SIZE,
  readTableState,
  type TableState,
  type TableStateConfig,
  writeTableState,
} from './tableState';

interface ColumnCommon {
  title: ReactNode;
  width?: number | string;
  align?: 'left' | 'right' | 'center';
  ellipsis?: boolean;
  fixed?: 'left' | 'right';
  hidden?: boolean;
  /** `true` sorts by the column key; a string names the server-side sort field. */
  sortable?: boolean | string;
}

type FieldColumn<Row> = {
  [Field in keyof Row & string]: ColumnCommon & {
    /** Row field shown by the column; `render` receives its typed value. */
    dataIndex: Field;
    /** Defaults to `dataIndex`. */
    key?: string;
    render?: (value: Row[Field], row: Row, index: number) => ReactNode;
  };
}[keyof Row & string];

interface ComputedColumn<Row> extends ColumnCommon {
  key: string;
  dataIndex?: undefined;
  render: (row: Row, index: number) => ReactNode;
}

export type ServerTableColumn<Row> = FieldColumn<Row> | ComputedColumn<Row>;

interface FilterCommon {
  /** Query parameter the filter sets. */
  name: string;
  label: string;
  width?: number;
}

export type ServerTableFilter =
  | (FilterCommon & { type: 'text' })
  | (FilterCommon & { type: 'select'; options: { value: string; label: string }[]; multiple?: boolean })
  | (FilterCommon & { type: 'boolean' })
  | (FilterCommon & { type: 'date' })
  /** Range over the date field `name`; sets the parameters `<name>_from` and `<name>_to`. */
  | (FilterCommon & { type: 'dateRange' })
  | (FilterCommon & {
      type: 'entity';
      endpoint: string;
      // Declared as a method so that a label function typed for the concrete item is accepted.
      getLabel(item: { id: number }): ReactNode;
      params?: QueryParams;
    });

export interface ServerTableSelection<Row> {
  selectedKeys: Key[];
  onChange: (keys: Key[], rows: Row[]) => void;
  /** Rows that cannot be selected. */
  isDisabled?: (row: Row) => boolean;
}

export interface ServerTableProps<Row extends object> {
  /** List endpoint relative to `/api`, e.g. `/mm/purchase-orders`. */
  endpoint: string;
  columns: ServerTableColumn<Row>[];
  /** Field or function identifying a row. Default: `id`. */
  rowKey?: (keyof Row & string) | ((row: Row) => Key);
  filters?: ServerTableFilter[];
  /** Parameters sent with every request and not shown as filters, e.g. `{ kind: 'VENDOR_INVOICE' }`. */
  baseParams?: QueryParams;
  /** Order used until the user sorts a column, e.g. `-created_at`. */
  defaultSort?: string;
  defaultPageSize?: number;
  /** Shows the search box bound to `q`. Default: true. */
  searchable?: boolean;
  searchPlaceholder?: string;
  /** Right-hand side of the toolbar (create button, exports, ...). */
  toolbar?: ReactNode;
  onRowClick?: (row: Row) => void;
  selection?: ServerTableSelection<Row>;
  /**
   * Mirror page, sort, search and filters in the URL query string so that a reload, a shared link
   * or coming back from a detail page restores the list. Switch off for tables inside modals.
   */
  urlState?: boolean;
  /** Prefix of the query-string keys when a page shows more than one table. */
  urlPrefix?: string;
  /** Further props of the underlying Ant Design table (`expandable`, `summary`, `rowClassName`, ...). */
  tableProps?: Omit<
    TableProps<Row>,
    'columns' | 'dataSource' | 'rowKey' | 'loading' | 'pagination' | 'onChange' | 'rowSelection' | 'onRow'
  >;
}

const PAGE_SIZE_OPTIONS = [20, 50, 100, 200, MAX_PAGE_SIZE];
const SEARCH_DELAY_MS = 350;
const ISO_DATE = 'YYYY-MM-DD';
const INTERACTIVE = 'a, button, input, textarea, label, [role="button"], .ant-table-selection-column';

const BOOLEAN_OPTIONS = [
  { value: 'true', label: 'Evet' },
  { value: 'false', label: 'Hayır' },
];

function rangeNames(name: string): [string, string] {
  return [`${name}_from`, `${name}_to`];
}

function isComputed<Row>(column: ServerTableColumn<Row>): column is ComputedColumn<Row> {
  return column.dataIndex === undefined;
}

type UpdateTableState = (patch: Partial<TableState>) => void;

function useTableState(urlState: boolean, config: TableStateConfig): [TableState, UpdateTableState] {
  const [searchParams, setSearchParams] = useSearchParams();
  const [localState, setLocalState] = useState(() => initialTableState(config));
  const state = urlState ? readTableState(searchParams, config) : localState;

  const apply = (patch: Partial<TableState>): void => {
    const next = { ...state, ...patch };
    if (urlState) {
      setSearchParams(writeTableState(searchParams, next, config), { replace: true });
    } else {
      setLocalState(next);
    }
  };
  // Timers and effects go through a stable function that always applies to the current state.
  const latest = useRef(apply);
  useLayoutEffect(() => {
    latest.current = apply;
  });
  const update = useCallback((patch: Partial<TableState>) => latest.current(patch), []);

  return [state, update];
}

interface FilterControlProps {
  filter: ServerTableFilter;
  filters: Record<string, FilterValue>;
  onChange: (changes: Record<string, FilterValue | undefined>) => void;
}

function single(value: FilterValue | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

interface TextFilterProps {
  filter: FilterCommon;
  value: string;
  onCommit: (value: string) => void;
}

/** Free-text filter; applied on Enter or when the field is left, not on every keystroke. */
function TextFilter({ filter, value, onCommit }: TextFilterProps): ReactNode {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = (text: string): void => {
    if (text.trim() !== value) {
      onCommit(text.trim());
    }
  };

  return (
    <Input
      allowClear
      placeholder={filter.label}
      aria-label={filter.label}
      value={draft}
      style={{ width: filter.width ?? 160 }}
      onChange={(event) => setDraft(event.target.value)}
      onPressEnter={() => commit(draft)}
      onBlur={() => commit(draft)}
      onClear={() => commit('')}
    />
  );
}

function FilterControl({ filter, filters, onChange }: FilterControlProps): ReactNode {
  const value = filters[filter.name];
  const set = (next: FilterValue | null | undefined): void => onChange({ [filter.name]: next || undefined });

  switch (filter.type) {
    case 'text':
      return <TextFilter filter={filter} value={single(value) ?? ''} onCommit={set} />;
    case 'select':
      return filter.multiple ? (
        <Select<string[]>
          mode="multiple"
          allowClear
          showSearch
          optionFilterProp="label"
          maxTagCount="responsive"
          placeholder={filter.label}
          aria-label={filter.label}
          options={filter.options}
          value={value === undefined ? [] : Array.isArray(value) ? value : [value]}
          style={{ width: filter.width ?? 200 }}
          popupMatchSelectWidth={false}
          onChange={(next) => set(next.length === 0 ? undefined : next)}
        />
      ) : (
        <Select<string>
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder={filter.label}
          aria-label={filter.label}
          options={filter.options}
          value={single(value)}
          style={{ width: filter.width ?? 170 }}
          popupMatchSelectWidth={false}
          onChange={set}
        />
      );
    case 'boolean':
      return (
        <Select<string>
          allowClear
          placeholder={filter.label}
          aria-label={filter.label}
          options={BOOLEAN_OPTIONS}
          value={single(value)}
          style={{ width: filter.width ?? 140 }}
          popupMatchSelectWidth={false}
          onChange={set}
        />
      );
    case 'date':
      return (
        <DateInput
          placeholder={filter.label}
          aria-label={filter.label}
          value={single(value) ?? null}
          style={{ width: filter.width ?? 140 }}
          onChange={set}
        />
      );
    case 'dateRange': {
      const [fromName, toName] = rangeNames(filter.name);
      const from = single(filters[fromName]);
      const to = single(filters[toName]);
      return (
        <DatePicker.RangePicker
          allowEmpty={[true, true]}
          format="DD.MM.YYYY"
          placeholder={[`${filter.label} (ilk)`, `${filter.label} (son)`]}
          value={[from ? dayjs(from) : null, to ? dayjs(to) : null]}
          style={{ width: filter.width ?? 300 }}
          onChange={(range) =>
            onChange({
              [fromName]: range?.[0]?.format(ISO_DATE),
              [toName]: range?.[1]?.format(ISO_DATE),
            })
          }
        />
      );
    }
    case 'entity': {
      const id = Number(single(value));
      return (
        <EntitySelect
          endpoint={filter.endpoint}
          getLabel={filter.getLabel}
          params={filter.params}
          placeholder={filter.label}
          value={Number.isInteger(id) && id > 0 ? id : null}
          style={{ width: filter.width ?? 220 }}
          onChange={(next) => set(next === null ? undefined : String(next))}
        />
      );
    }
  }
}

/**
 * Table bound to a list endpoint (`{items, total, page, page_size}`): paging, sorting, the `q`
 * search box and the declared filters all run on the server.
 *
 *   <ServerTable<PurchaseOrder>
 *     endpoint="/mm/purchase-orders"
 *     defaultSort="-order_date"
 *     columns={[
 *       { dataIndex: 'number', title: 'Sipariş No', sortable: true, width: 130 },
 *       { dataIndex: 'order_date', title: 'Tarih', sortable: true, render: (value) => fmtDate(value) },
 *       { dataIndex: 'gross_total', title: 'Tutar', align: 'right', render: (value, row) => fmtMoney(value, row.currency_code) },
 *       { key: 'actions', title: '', render: (row) => <DownloadButton url={`/mm/purchase-orders/${row.id}/pdf`} format="pdf" /> },
 *     ]}
 *     filters={[
 *       { type: 'select', name: 'status', label: 'Durum', options: statusOptions, multiple: true },
 *       { type: 'dateRange', name: 'order_date', label: 'Sipariş tarihi' },
 *     ]}
 *     toolbar={<Button type="primary">Yeni sipariş</Button>}
 *     onRowClick={(row) => navigate(`/mm/siparis/${row.id}`)}
 *   />
 *
 * After a mutation refresh it with `queryClient.invalidateQueries({ queryKey: queryKeys.all(endpoint) })`.
 */
export function ServerTable<Row extends object>({
  endpoint,
  columns,
  rowKey = 'id' as keyof Row & string,
  filters = [],
  baseParams,
  defaultSort,
  defaultPageSize = 50,
  searchable = true,
  searchPlaceholder = 'Ara',
  toolbar,
  onRowClick,
  selection,
  urlState = true,
  urlPrefix = '',
  tableProps,
}: ServerTableProps<Row>): ReactNode {
  const [state, update] = useTableState(urlState, {
    prefix: urlPrefix,
    defaultPageSize,
    filterNames: filters.flatMap((filter) => (filter.type === 'dateRange' ? rangeNames(filter.name) : [filter.name])),
    multiValued: filters.flatMap((filter) => (filter.type === 'select' && filter.multiple ? [filter.name] : [])),
  });

  const [searchText, setSearchText] = useState(state.q);
  const searchTimer = useRef<number>();
  // Follows changes of `q` that did not come from typing (browser navigation, "Temizle").
  useEffect(() => setSearchText(state.q), [state.q]);
  useEffect(() => () => window.clearTimeout(searchTimer.current), []);

  const applySearch = (text: string, delayMs: number): void => {
    setSearchText(text);
    window.clearTimeout(searchTimer.current);
    searchTimer.current = window.setTimeout(() => update({ q: text.trim(), page: 1 }), delayMs);
  };

  const params = {
    ...baseParams,
    ...state.filters,
    page: state.page,
    page_size: state.pageSize,
    sort: state.sort ?? defaultSort,
    q: state.q,
  };
  const query = useQuery({
    queryKey: queryKeys.list(endpoint, params),
    queryFn: ({ signal }) => getList<Row>(endpoint, params, signal),
    placeholderData: keepPreviousData,
  });
  const { data } = query;

  // Deleting the last rows of the last page would otherwise leave an empty page behind.
  useEffect(() => {
    if (data && data.items.length === 0 && data.total > 0 && state.page > 1) {
      update({ page: Math.ceil(data.total / state.pageSize) });
    }
  }, [data, state.page, state.pageSize, update]);

  const activeSort = state.sort ?? defaultSort;
  const sortNames = new Map<string, string>();
  const tableColumns: ColumnsType<Row> = columns
    .filter((column) => !column.hidden)
    .map((column) => {
      const key = isComputed(column) ? column.key : (column.key ?? column.dataIndex);
      const sortName = column.sortable === true ? key : column.sortable || undefined;
      if (sortName !== undefined) {
        sortNames.set(key, sortName);
      }
      // The union ties each `render` to the type of its own field; here the value is just passed on.
      const renderValue = isComputed(column)
        ? undefined
        : (column.render as ((value: unknown, row: Row, index: number) => ReactNode) | undefined);
      return {
        key,
        title: column.title,
        dataIndex: column.dataIndex,
        width: column.width,
        align: column.align,
        ellipsis: column.ellipsis,
        fixed: column.fixed,
        sorter: sortName !== undefined,
        sortOrder:
          sortName === undefined
            ? undefined
            : activeSort === sortName
              ? 'ascend'
              : activeSort === `-${sortName}`
                ? 'descend'
                : null,
        render: isComputed(column) ? (_: unknown, row: Row, index: number) => column.render(row, index) : renderValue,
      };
    });

  const handleTableChange: TableProps<Row>['onChange'] = (pagination, _filters, sorter, extra) => {
    if (extra.action === 'paginate') {
      update({ page: pagination.current ?? 1, pageSize: pagination.pageSize ?? state.pageSize });
    } else if (extra.action === 'sort') {
      const { columnKey, order } = Array.isArray(sorter) ? (sorter[0] ?? {}) : sorter;
      const sortName = sortNames.get(String(columnKey));
      update({ sort: sortName && order ? `${order === 'descend' ? '-' : ''}${sortName}` : undefined, page: 1 });
    }
  };

  const handleFilterChange = (changes: Record<string, FilterValue | undefined>): void => {
    const next = { ...state.filters };
    for (const [name, value] of Object.entries(changes)) {
      if (value === undefined) {
        delete next[name];
      } else {
        next[name] = value;
      }
    }
    update({ filters: next, page: 1 });
  };

  const hasCriteria = state.q !== '' || Object.keys(state.filters).length > 0;
  const clearCriteria = (): void => {
    window.clearTimeout(searchTimer.current);
    setSearchText('');
    update({ q: '', filters: {}, page: 1 });
  };

  const handleRowClick = (row: Row, event: MouseEvent<HTMLElement>): void => {
    // Clicks on controls inside the row (links, buttons, checkboxes) belong to those controls.
    if (!(event.target as HTMLElement).closest(INTERACTIVE)) {
      onRowClick?.(row);
    }
  };

  return (
    <Flex vertical gap={8}>
      <Flex gap={8} wrap align="center" justify="space-between">
        <Flex gap={8} wrap align="center">
          {searchable && (
            <Input
              allowClear
              prefix={<SearchOutlined />}
              placeholder={searchPlaceholder}
              aria-label={searchPlaceholder}
              value={searchText}
              style={{ width: 220 }}
              onChange={(event) => applySearch(event.target.value, SEARCH_DELAY_MS)}
              onPressEnter={() => applySearch(searchText, 0)}
            />
          )}
          {filters.map((filter) => (
            <FilterControl key={filter.name} filter={filter} filters={state.filters} onChange={handleFilterChange} />
          ))}
          {hasCriteria && (
            <Button type="link" icon={<ClearOutlined />} onClick={clearCriteria}>
              Temizle
            </Button>
          )}
        </Flex>
        <Flex gap={8} wrap align="center" style={{ marginInlineStart: 'auto' }}>
          {toolbar}
          <Tooltip title="Yenile">
            <Button
              icon={<ReloadOutlined spin={query.isFetching} />}
              aria-label="Yenile"
              onClick={() => void query.refetch()}
            />
          </Tooltip>
        </Flex>
      </Flex>

      {query.isError && (
        <Alert
          type="error"
          showIcon
          message={errorMessage(query.error)}
          action={
            <Button size="small" onClick={() => void query.refetch()}>
              Tekrar dene
            </Button>
          }
        />
      )}

      <Table<Row>
        size="small"
        scroll={{ x: 'max-content' }}
        {...tableProps}
        rowKey={rowKey}
        columns={tableColumns}
        dataSource={data?.items ?? []}
        loading={query.isPending || query.isPlaceholderData}
        showSorterTooltip={false}
        locale={{
          emptyText: (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                query.isPending
                  ? 'Yükleniyor…'
                  : query.isError
                    ? 'Kayıtlar yüklenemedi'
                    : hasCriteria
                      ? 'Arama ölçütlerine uyan kayıt bulunamadı'
                      : 'Kayıt bulunmuyor'
              }
            />
          ),
        }}
        pagination={{
          current: state.page,
          pageSize: state.pageSize,
          total: data?.total ?? 0,
          showSizeChanger: true,
          pageSizeOptions: PAGE_SIZE_OPTIONS,
          showTotal: (total) => `Toplam ${total} kayıt`,
        }}
        rowSelection={
          selection && {
            selectedRowKeys: selection.selectedKeys,
            preserveSelectedRowKeys: true,
            onChange: selection.onChange,
            getCheckboxProps: selection.isDisabled && ((row) => ({ disabled: selection.isDisabled?.(row) })),
          }
        }
        onRow={
          onRowClick && ((row) => ({ onClick: (event) => handleRowClick(row, event), style: { cursor: 'pointer' } }))
        }
        onChange={handleTableChange}
      />
    </Flex>
  );
}
