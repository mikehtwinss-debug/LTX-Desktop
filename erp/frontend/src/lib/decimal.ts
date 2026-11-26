import Big from 'big.js';

/**
 * Exact decimal helpers for UI previews (line amounts, running totals). The API sends decimals as
 * strings; they must never pass through binary floats. The server stays the authority for every
 * posted total, tax and valuation.
 */

export type DecimalLike = string | number | Big;
export type MaybeDecimal = DecimalLike | null | undefined;

/** Parses a decimal; `null` for empty or malformed input. */
export function parseDecimal(value: MaybeDecimal): Big | null {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  try {
    return new Big(value);
  } catch {
    return null;
  }
}

/** Like `parseDecimal`, but empty or malformed input counts as zero. */
export function toBig(value: MaybeDecimal): Big {
  return parseDecimal(value) ?? new Big(0);
}

export function sum(values: Iterable<MaybeDecimal>): Big {
  let total = new Big(0);
  for (const value of values) {
    total = total.plus(toBig(value));
  }
  return total;
}

export function mul(a: MaybeDecimal, b: MaybeDecimal): Big {
  return toBig(a).times(toBig(b));
}

/** Rounds half up, the rounding mode the backend uses for money, quantities and prices. */
export function round(value: MaybeDecimal, decimals: number): Big {
  return toBig(value).round(decimals, Big.roundHalfUp);
}

/** `amount × pct / 100` (discounts, tax previews), unrounded. */
export function pctOf(amount: MaybeDecimal, pct: MaybeDecimal): Big {
  return toBig(amount).times(toBig(pct)).div(100);
}

/** Rounded decimal as the plain string the API expects, e.g. `toDecimalString('2.5', 2)` → `"2.50"`. */
export function toDecimalString(value: MaybeDecimal, decimals: number): string {
  const rounded = round(value, decimals);
  // A value that rounds to zero must not keep its sign ("-0.00").
  return (rounded.eq(0) ? rounded.abs() : rounded).toFixed(decimals);
}
