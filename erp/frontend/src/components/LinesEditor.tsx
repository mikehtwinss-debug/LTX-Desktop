import './LinesEditor.css';

import { CopyOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { Button, Empty, Flex, Input, Select, Table, theme, Tooltip, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  type CSSProperties,
  type KeyboardEvent,
  memo,
  type ReactNode,
  useCallback,
  useLayoutEffect,
  useRef,
} from 'react';

import type { QueryParams } from '@/lib/api';
import type { LineErrors } from '@/lib/forms';
import { fmtDate, fmtMoney, fmtPct, fmtPrice, fmtQty } from '@/lib/format';

import { DateInput } from './DateInput';
import { DecimalInput } from './DecimalInput';
import { EntitySelect } from './EntitySelect';
import { MoneyInput, PctInput, PriceInput, QtyInput } from './NumberInputs';

type FieldOfType<Row, Value> = {
  [Field in keyof Row & string]-?: Row[Field] extends Value ? Field : never;
}[keyof Row & string];

type TextField<Row> = FieldOfType<Row, string | null | undefined>;
type NumberField<Row> = FieldOfType<Row, number | null | undefined>;

export interface LineSelectOption {
  value: string | number;
  label: string;
}

interface ColumnCommon<Row> {
  title: ReactNode;
  /** Width in pixels (default 160). Columns share extra space; narrower containers scroll sideways. */
  width?: number;
  align?: 'left' | 'right' | 'center';
  /** Marks the column header as mandatory. */
  required?: boolean;
  /** Makes single cells read-only, e.g. the quantity of a line that is already received. */
  isDisabled?: (row: Row, index: number) => boolean;
  /** Footer cell, e.g. `(rows) => fmtMoney(sum(rows.map((row) => row.net_amount)))`. */
  total?: (rows: Row[]) => ReactNode;
}

interface FieldColumnCommon<Row> extends ColumnCommon<Row> {
  /** Defaults to `field`. */
  key?: string;
}

/**
 * Column of a `LinesEditor`. `field` must be a row field whose type fits the editor: decimal
 * strings for `money`, `qty`, `price` and `pct`, ISO date strings for `date`, numbers for
 * `number` (integers) and `entity` (ids).
 */
export type LineColumn<Row> =
  | (FieldColumnCommon<Row> & { editor: 'text'; field: TextField<Row>; maxLength?: number })
  | (FieldColumnCommon<Row> & { editor: 'number'; field: NumberField<Row> })
  | (FieldColumnCommon<Row> & { editor: 'money' | 'price' | 'pct' | 'date'; field: TextField<Row> })
  | (FieldColumnCommon<Row> & {
      editor: 'qty';
      field: TextField<Row>;
      /** Decimals of the row's unit of measure. Default: 3. */
      decimals?: number | ((row: Row) => number);
    })
  | (FieldColumnCommon<Row> & {
      editor: 'select';
      field: FieldOfType<Row, string | number | null | undefined>;
      options: LineSelectOption[] | ((row: Row) => LineSelectOption[]);
    })
  | (FieldColumnCommon<Row> & {
      editor: 'entity';
      field: NumberField<Row>;
      endpoint: string;
      // Methods, so that functions typed for the concrete item are accepted.
      getLabel(item: { id: number }): ReactNode;
      params?: QueryParams | ((row: Row) => QueryParams);
      /** Values to copy into the row when an item is chosen (unit, description, last price, ...). */
      onSelect?(item: { id: number } | null, row: Row): Partial<Row>;
    })
  /** Display-only column, typically computed from other cells of the row. */
  | (ColumnCommon<Row> & { editor: 'readonly'; key: string; render: (row: Row, index: number) => ReactNode });

export interface LinesEditorProps<Row extends object> {
  columns: LineColumn<Row>[];
  value?: Row[];
  onChange?: (rows: Row[]) => void;
  /** Builds the row added by the "Satır ekle" button and by Enter in the last cell. */
  createRow: () => Row;
  /** Builds the copy for the duplicate action. Default: a copy of the row without its `id`. */
  duplicateRow?: (row: Row) => Row;
  /** Messages per row index and field, e.g. from `lineErrorsFromApi(error, 'lines')`. */
  errors?: LineErrors;
  /** Shows the lines without any way to change them. */
  disabled?: boolean;
  allowAdd?: boolean;
  allowDuplicate?: boolean;
  allowRemove?: boolean;
  id?: string;
}

type Direction = 'next' | 'previous' | 'up' | 'down' | 'left' | 'right';

interface CellPosition {
  row: number;
  column: number;
}

const DEFAULT_QTY_DECIMALS = 3;
const DEFAULT_COLUMN_WIDTH = 160;
const INDEX_COLUMN_WIDTH = 40;
const ACTION_BUTTON_WIDTH = 28;
const FOCUSABLE = 'input:not([disabled]), textarea:not([disabled])';

function columnKey<Row>(column: LineColumn<Row>): string {
  return column.editor === 'readonly' ? column.key : (column.key ?? column.field);
}

function withoutId<Row extends object>(row: Row): Row {
  const copy: Row & { id?: unknown } = { ...row };
  delete copy.id;
  return copy;
}

function resolve<Row, Value>(source: Value | ((row: Row) => Value), row: Row): Value {
  return typeof source === 'function' ? (source as (row: Row) => Value)(row) : source;
}

interface CellProps<Row> {
  column: LineColumn<Row>;
  row: Row;
  index: number;
  editable: boolean;
  error: string | undefined;
  onPatch: (index: number, patch: Partial<Row>) => void;
}

/** Plain text of a cell that cannot be edited. */
function displayValue<Row>(column: Exclude<LineColumn<Row>, { editor: 'readonly' | 'entity' }>, row: Row): ReactNode {
  const value = (row as Record<string, unknown>)[column.field];
  const text = typeof value === 'string' ? value : null;
  switch (column.editor) {
    case 'money':
      return fmtMoney(text);
    case 'price':
      return fmtPrice(text);
    case 'pct':
      return fmtPct(text);
    case 'qty':
      return fmtQty(text, column.decimals === undefined ? undefined : resolve(column.decimals, row));
    case 'date':
      return fmtDate(text);
    case 'select':
      return resolve(column.options, row).find((option) => option.value === value)?.label ?? '';
    case 'number':
      return typeof value === 'number' ? String(value) : '';
    case 'text':
      return text ?? '';
  }
}

function CellInner<Row>({ column, row, index, editable, error, onPatch }: CellProps<Row>): ReactNode {
  if (column.editor === 'readonly') {
    return <div className="erp-lines-text">{column.render(row, index)}</div>;
  }

  const { field } = column;
  const value = (row as Record<string, unknown>)[field];
  const text = typeof value === 'string' ? value : null;
  const set = (next: unknown): void => onPatch(index, { [field]: next } as Partial<Row>);
  const shared = {
    variant: 'borderless',
    status: error ? 'error' : undefined,
    'aria-label': typeof column.title === 'string' ? `${column.title}, ${index + 1}. satır` : undefined,
  } as const;
  let editor: ReactNode;

  if (column.editor === 'entity') {
    editor = (
      <EntitySelect
        {...shared}
        disabled={!editable}
        placeholder={editable ? undefined : ''}
        endpoint={column.endpoint}
        getLabel={column.getLabel}
        params={column.params && resolve(column.params, row)}
        value={typeof value === 'number' ? value : null}
        onChange={(id, item) => onPatch(index, { ...column.onSelect?.(item, row), [field]: id } as Partial<Row>)}
      />
    );
  } else if (!editable) {
    editor = <div className="erp-lines-text">{displayValue(column, row)}</div>;
  } else {
    switch (column.editor) {
      case 'text':
        editor = (
          <Input
            {...shared}
            autoComplete="off"
            maxLength={column.maxLength}
            value={text ?? ''}
            onChange={(event) => set(event.target.value)}
          />
        );
        break;
      case 'number':
        editor = (
          <DecimalInput
            {...shared}
            decimals={0}
            value={typeof value === 'number' ? String(value) : null}
            onChange={(next) => set(next === null ? null : Number(next))}
          />
        );
        break;
      case 'money':
        editor = <MoneyInput {...shared} value={text} onChange={set} />;
        break;
      case 'price':
        editor = <PriceInput {...shared} value={text} onChange={set} />;
        break;
      case 'pct':
        editor = <PctInput {...shared} value={text} onChange={set} />;
        break;
      case 'qty':
        editor = (
          <QtyInput
            {...shared}
            decimals={column.decimals === undefined ? DEFAULT_QTY_DECIMALS : resolve(column.decimals, row)}
            value={text}
            onChange={set}
          />
        );
        break;
      case 'date':
        editor = <DateInput {...shared} value={text} onChange={set} />;
        break;
      case 'select':
        editor = (
          <Select<string | number>
            {...shared}
            allowClear
            showSearch
            optionFilterProp="label"
            popupMatchSelectWidth={false}
            style={{ width: '100%' }}
            options={resolve(column.options, row)}
            value={typeof value === 'string' || typeof value === 'number' ? value : undefined}
            onChange={(next) => set(next ?? null)}
          />
        );
        break;
    }
  }

  // The message of a marked cell appears on hover and while the cell has the focus.
  return error ? (
    <Tooltip title={error} placement="topLeft" trigger={['hover', 'focus']}>
      <div>{editor}</div>
    </Tooltip>
  ) : (
    editor
  );
}

const Cell = memo(CellInner) as typeof CellInner;

interface GridRow<Row> {
  key: number;
  index: number;
  row: Row;
}

function caretAt(input: HTMLInputElement, edge: 'start' | 'end'): boolean {
  let start: number | null;
  let end: number | null;
  try {
    start = input.selectionStart;
    end = input.selectionEnd;
  } catch {
    // Inputs without a text selection (e.g. the read-only input of a plain select).
    return true;
  }
  if (start === null || end === null || input.readOnly) {
    return true;
  }
  const length = input.value.length;
  const everythingSelected = start === 0 && end === length;
  return everythingSelected || (start === end && start === (edge === 'start' ? 0 : length));
}

/**
 * Editable line grid of a document, usable as an Ant Design form field:
 *
 *   <Form.Item name="lines" rules={[{ required: true, message: 'En az bir satır girin' }]}>
 *     <LinesEditor<OrderLine>
 *       createRow={() => ({ material_id: null, quantity: null, unit_price: null })}
 *       errors={lineErrors}
 *       columns={[
 *         { editor: 'entity', field: 'material_id', title: 'Malzeme', required: true, width: 260,
 *           endpoint: '/mm/materials', getLabel: (m: Material) => `${m.code} — ${m.name}`,
 *           onSelect: (m: Material | null) => ({ uom_id: m?.base_uom_id ?? null }) },
 *         { editor: 'qty', field: 'quantity', title: 'Miktar', required: true, width: 110 },
 *         { editor: 'price', field: 'unit_price', title: 'Birim fiyat', width: 130 },
 *         { editor: 'readonly', key: 'amount', title: 'Tutar', align: 'right', width: 130,
 *           render: (row) => fmtMoney(mul(row.quantity, row.unit_price)),
 *           total: (rows) => fmtMoney(sum(rows.map((row) => mul(row.quantity, row.unit_price)))) },
 *       ]}
 *     />
 *   </Form.Item>
 *
 * Keyboard: Enter moves to the next cell and adds a row after the last one, Shift+Enter moves
 * back, Tab follows the normal focus order, the arrow keys move between rows and (at the edge
 * of the text) between cells. Open dropdowns and the date editor keep their own arrow keys.
 */
export function LinesEditor<Row extends object>({
  columns,
  value,
  onChange,
  createRow,
  duplicateRow = withoutId,
  errors,
  disabled = false,
  allowAdd = true,
  allowDuplicate = true,
  allowRemove = true,
  id,
}: LinesEditorProps<Row>): ReactNode {
  const { token } = theme.useToken();
  const rows = value ?? [];
  const containerRef = useRef<HTMLDivElement>(null);
  const pendingFocus = useRef<number | null>(null);

  // React keys must survive edits and row removal, and the rows themselves carry no stable id.
  const nextKey = useRef(0);
  const keys = useRef<number[]>([]);
  if (keys.current.length !== rows.length) {
    keys.current = rows.map(() => nextKey.current++);
  }

  const latest = useRef({ rows, onChange });
  useLayoutEffect(() => {
    latest.current = { rows, onChange };
  });

  const emit = useCallback((nextRows: Row[], nextKeys: number[]) => {
    keys.current = nextKeys;
    latest.current.onChange?.(nextRows);
  }, []);

  const patchRow = useCallback(
    (index: number, patch: Partial<Row>) => {
      const current = latest.current.rows;
      const target = current[index];
      if (target !== undefined) {
        emit(
          current.map((row, position) => (position === index ? { ...target, ...patch } : row)),
          keys.current,
        );
      }
    },
    [emit],
  );

  const insertRow = (index: number, row: Row): void => {
    pendingFocus.current = index;
    emit(
      [...rows.slice(0, index), row, ...rows.slice(index)],
      [...keys.current.slice(0, index), nextKey.current++, ...keys.current.slice(index)],
    );
  };

  const removeRow = (index: number): void => {
    emit(
      rows.filter((_, position) => position !== index),
      keys.current.filter((_, position) => position !== index),
    );
  };

  const focusCell = (position: CellPosition): boolean => {
    const cell = containerRef.current?.querySelector<HTMLElement>(
      `td[data-row="${position.row}"][data-column="${position.column}"]`,
    );
    const target = cell?.querySelector<HTMLInputElement>(FOCUSABLE);
    if (!target) {
      return false;
    }
    target.focus();
    if (!target.readOnly) {
      target.select();
    }
    return true;
  };

  const focusFirstCell = (row: number): boolean => columns.some((_, column) => focusCell({ row, column }));

  // A row added by the user receives the focus once it has been rendered.
  useLayoutEffect(() => {
    if (pendingFocus.current !== null && pendingFocus.current < rows.length) {
      focusFirstCell(pendingFocus.current);
      pendingFocus.current = null;
    }
  });

  const move = (from: CellPosition, direction: Direction): void => {
    const lastRow = rows.length - 1;
    const lastColumn = columns.length - 1;
    const step = direction === 'next' || direction === 'right' || direction === 'down' ? 1 : -1;

    if (direction === 'up' || direction === 'down') {
      for (let row = from.row + step; row >= 0 && row <= lastRow; row += step) {
        if (focusCell({ row, column: from.column })) {
          return;
        }
      }
      return;
    }

    const wraps = direction === 'next' || direction === 'previous';
    let { row, column } = from;
    for (;;) {
      column += step;
      if (column < 0 || column > lastColumn) {
        if (!wraps) {
          return;
        }
        row += step;
        column = step > 0 ? 0 : lastColumn;
      }
      if (row < 0) {
        return;
      }
      if (row > lastRow) {
        if (allowAdd && !disabled) {
          insertRow(rows.length, createRow());
        }
        return;
      }
      if (focusCell({ row, column })) {
        return;
      }
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.nativeEvent.isComposing) {
      return;
    }
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) {
      return;
    }
    const cell = target.closest<HTMLElement>('td[data-row]');
    // An open dropdown uses Enter and the arrow keys itself.
    if (!cell || target.getAttribute('aria-expanded') === 'true') {
      return;
    }
    const inDateEditor = target.closest('.ant-picker') !== null;

    let direction: Direction | null = null;
    if (event.key === 'Enter') {
      direction = event.shiftKey ? 'previous' : 'next';
    } else if (!event.shiftKey && !inDateEditor) {
      // The date editor steps through day, month and year with the arrow keys.
      if (event.key === 'ArrowUp') {
        direction = 'up';
      } else if (event.key === 'ArrowDown') {
        direction = 'down';
      } else if (event.key === 'ArrowLeft' && caretAt(target, 'start')) {
        direction = 'left';
      } else if (event.key === 'ArrowRight' && caretAt(target, 'end')) {
        direction = 'right';
      }
    }
    if (direction === null) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    move({ row: Number(cell.dataset.row), column: Number(cell.dataset.column) }, direction);
  };

  const editable = !disabled;
  const showActions = editable && (allowDuplicate || allowRemove);
  const actionsWidth = showActions
    ? (allowDuplicate ? ACTION_BUTTON_WIDTH : 0) + (allowRemove ? ACTION_BUTTON_WIDTH : 0) + 8
    : 0;
  const totalWidth =
    INDEX_COLUMN_WIDTH +
    actionsWidth +
    columns.reduce((total, column) => total + (column.width ?? DEFAULT_COLUMN_WIDTH), 0);
  const tableColumns: ColumnsType<GridRow<Row>> = [
    {
      key: '#',
      title: '#',
      width: INDEX_COLUMN_WIDTH,
      align: 'right',
      render: (_: unknown, record) => <Typography.Text type="secondary">{record.index + 1}</Typography.Text>,
    },
    ...columns.map((column, columnIndex) => {
      const key = columnKey(column);
      return {
        key,
        width: column.width ?? DEFAULT_COLUMN_WIDTH,
        align: column.align,
        title: column.required ? (
          <>
            {column.title} <Typography.Text type="danger">*</Typography.Text>
          </>
        ) : (
          column.title
        ),
        onCell: (record: GridRow<Row>) => ({
          className: errors?.[record.index]?.[key] ? 'erp-lines-cell erp-lines-cell-error' : 'erp-lines-cell',
          'data-row': record.index,
          'data-column': columnIndex,
        }),
        render: (_: unknown, record: GridRow<Row>) => (
          <Cell<Row>
            column={column}
            row={record.row}
            index={record.index}
            editable={editable && !column.isDisabled?.(record.row, record.index)}
            error={errors?.[record.index]?.[key]}
            onPatch={patchRow}
          />
        ),
      };
    }),
    ...(showActions
      ? [
          {
            key: 'actions',
            title: '',
            width: actionsWidth,
            align: 'center' as const,
            fixed: 'right' as const,
            render: (_: unknown, record: GridRow<Row>) => (
              <Flex justify="center">
                {allowDuplicate && (
                  <Tooltip title="Satırı kopyala">
                    <Button
                      type="text"
                      size="small"
                      tabIndex={-1}
                      icon={<CopyOutlined />}
                      aria-label="Satırı kopyala"
                      onClick={() => insertRow(record.index + 1, duplicateRow(record.row))}
                    />
                  </Tooltip>
                )}
                {allowRemove && (
                  <Tooltip title="Satırı sil">
                    <Button
                      type="text"
                      size="small"
                      danger
                      tabIndex={-1}
                      icon={<DeleteOutlined />}
                      aria-label="Satırı sil"
                      onClick={() => removeRow(record.index)}
                    />
                  </Tooltip>
                )}
              </Flex>
            ),
          },
        ]
      : []),
  ];

  const hasTotals = columns.some((column) => column.total !== undefined);
  const style = {
    '--erp-lines-focus': token.colorPrimary,
    '--erp-lines-error': token.colorError,
    '--erp-lines-error-bg': token.colorErrorBg,
  } as CSSProperties;

  return (
    <div id={id} ref={containerRef} className="erp-lines" style={style} onKeyDownCapture={handleKeyDown}>
      <Table<GridRow<Row>>
        size="small"
        bordered
        pagination={false}
        rowKey="key"
        tableLayout="fixed"
        scroll={{ x: totalWidth }}
        columns={tableColumns}
        dataSource={rows.map((row, index) => ({ key: keys.current[index] ?? index, index, row }))}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Henüz satır yok" /> }}
        summary={
          hasTotals
            ? () => (
                <Table.Summary.Row>
                  <Table.Summary.Cell index={0} />
                  {columns.map((column, columnIndex) => (
                    <Table.Summary.Cell key={columnKey(column)} index={columnIndex + 1} align={column.align}>
                      {column.total && <Typography.Text strong>{column.total(rows)}</Typography.Text>}
                    </Table.Summary.Cell>
                  ))}
                  {showActions && <Table.Summary.Cell index={columns.length + 1} />}
                </Table.Summary.Row>
              )
            : undefined
        }
      />
      {editable && allowAdd && (
        <Button
          type="dashed"
          size="small"
          icon={<PlusOutlined />}
          style={{ marginTop: 8 }}
          onClick={() => insertRow(rows.length, createRow())}
        >
          Satır ekle
        </Button>
      )}
    </div>
  );
}
