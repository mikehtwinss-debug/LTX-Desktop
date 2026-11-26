import { toDecimalString } from '@/lib/decimal';
import { formatDecimal, parseTrNumber } from '@/lib/format';

/** Text of a decimal field while it is edited: no thousands separators, no padding zeros. */
export function toEditText(value: string | null | undefined, decimals: number): string {
  return formatDecimal(value, { minDecimals: 0, maxDecimals: decimals, grouping: false });
}

/**
 * Cleans text typed into a decimal field. A dot is the decimal key of numeric keypads and is
 * turned into a comma (thousands separators are never typed, they appear when the field loses
 * the focus); anything but digits, one comma and a leading minus is dropped, and so are decimals
 * beyond the field's scale.
 */
export function sanitizeDecimalText(raw: string, decimals: number, allowNegative: boolean): string {
  const negative = allowNegative && /^\s*[-−]/.test(raw);
  const [integer = '', ...rest] = raw
    .replace(/\./g, ',')
    .replace(/[^\d,]/g, '')
    .split(',');
  const hasFraction = rest.length > 0 && decimals > 0;
  return `${negative ? '-' : ''}${integer}${hasFraction ? `,${rest.join('').slice(0, decimals)}` : ''}`;
}

/** Value of edited text at the field's scale (`"12,5"` → `"12.50"`), or `null` when it holds no number. */
export function parseEditText(text: string, decimals: number): string | null {
  const parsed = parseTrNumber(text);
  return parsed === null ? null : toDecimalString(parsed, decimals);
}

/** Reads a pasted number: Turkish notation (`1.234,56`) first, plain dot-decimal notation otherwise. */
export function parsePastedNumber(text: string): string | null {
  const trimmed = text.trim();
  return parseTrNumber(trimmed) ?? (/^-?\d+\.\d+$/.test(trimmed) ? trimmed : null);
}
