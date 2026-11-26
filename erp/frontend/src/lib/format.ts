import dayjs from 'dayjs';

import { type MaybeDecimal, parseDecimal, round } from './decimal';

/**
 * Turkish display formats. Numbers use `.` for thousands and `,` for decimals; every formatter
 * returns an empty string for empty or malformed input.
 */

interface DecimalFormat {
  minDecimals: number;
  maxDecimals: number;
  /** Thousands separators; switched off for text that is being edited. */
  grouping?: boolean;
}

export function formatDecimal(value: MaybeDecimal, { minDecimals, maxDecimals, grouping = true }: DecimalFormat): string {
  if (parseDecimal(value) === null) {
    return '';
  }
  const rounded = round(value, maxDecimals);
  const [integer = '0', fraction = ''] = rounded.abs().toFixed(maxDecimals).split('.');
  const decimals = fraction.replace(/0+$/, '').padEnd(minDecimals, '0');
  const grouped = grouping ? integer.replace(/\B(?=(\d{3})+(?!\d))/g, '.') : integer;
  return `${rounded.lt(0) ? '-' : ''}${grouped}${decimals ? `,${decimals}` : ''}`;
}

/** `fmtMoney('1234.5')` → `1.234,50`; with a currency: `1.234,50 USD`. */
export function fmtMoney(value: MaybeDecimal, currency?: string | null): string {
  const text = formatDecimal(value, { minDecimals: 2, maxDecimals: 2 });
  return text && currency ? `${text} ${currency}` : text;
}

/**
 * Quantity. With `decimals` (the unit's precision) the scale is fixed: `fmtQty('12', 3)` → `12,000`.
 * Without it trailing zeros are dropped: `fmtQty('12.500')` → `12,5`.
 */
export function fmtQty(value: MaybeDecimal, decimals?: number): string {
  return formatDecimal(value, { minDecimals: decimals ?? 0, maxDecimals: decimals ?? 3 });
}

/** Unit price: at least two, at most six decimals. `fmtPrice('12.500000')` → `12,50`. */
export function fmtPrice(value: MaybeDecimal): string {
  return formatDecimal(value, { minDecimals: 2, maxDecimals: 6 });
}

/** Percentage in Turkish notation: `fmtPct('20.0000')` → `%20`, `fmtPct('12.5')` → `%12,5`. */
export function fmtPct(value: MaybeDecimal): string {
  const text = formatDecimal(value, { minDecimals: 0, maxDecimals: 4 });
  return text ? `%${text}` : '';
}

function formatDate(value: string | null | undefined, template: string): string {
  if (!value) {
    return '';
  }
  const date = dayjs(value);
  return date.isValid() ? date.format(template) : '';
}

/** ISO date or timestamp → `DD.MM.YYYY`. */
export function fmtDate(value: string | null | undefined): string {
  return formatDate(value, 'DD.MM.YYYY');
}

/** ISO timestamp → `DD.MM.YYYY HH:mm` in the browser's time zone. */
export function fmtDateTime(value: string | null | undefined): string {
  return formatDate(value, 'DD.MM.YYYY HH:mm');
}

const TR_NUMBER = /^(?:\d{1,3}(?:\.\d{3})+|\d+)?(?:,\d*)?$/;

/**
 * Parses a number written the Turkish way (`1.234,56`, `1234,56`, `-0,5`, `,75`) into the plain
 * decimal string the API expects (`1234.56`). Returns `null` for empty or malformed text; a dot
 * is only accepted as a thousands separator, so `12.5` is rejected rather than guessed at.
 */
export function parseTrNumber(text: string | null | undefined): string | null {
  const compact = (text ?? '').replace(/[\s ]/g, '').replace(/^−/, '-');
  const negative = compact.startsWith('-');
  const body = negative ? compact.slice(1) : compact;
  if (!/\d/.test(body) || !TR_NUMBER.test(body)) {
    return null;
  }
  const [integerPart = '', fraction = ''] = body.split(',');
  const integer = integerPart.replace(/\./g, '').replace(/^0+(?=\d)/, '') || '0';
  const isZero = /^0*$/.test(integer) && /^0*$/.test(fraction);
  return `${negative && !isZero ? '-' : ''}${integer}${fraction ? `.${fraction}` : ''}`;
}

const FILE_SIZE_UNITS = ['B', 'KB', 'MB', 'GB'];

/** File size with a binary unit: `fmtFileSize(1536)` → `1,5 KB`. */
export function fmtFileSize(bytes: number): string {
  let size = bytes;
  let unit = 0;
  while (size >= 1024 && unit < FILE_SIZE_UNITS.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${formatDecimal(size.toFixed(1), { minDecimals: 0, maxDecimals: 1 })} ${FILE_SIZE_UNITS[unit]}`;
}
