import { describe, expect, it } from 'vitest';

import { fmtDate, fmtDateTime, fmtFileSize, fmtMoney, fmtPct, fmtPrice, fmtQty, formatDecimal, parseTrNumber } from './format';

describe('fmtMoney', () => {
  it('formats with Turkish separators and two decimals', () => {
    expect(fmtMoney('1234.5')).toBe('1.234,50');
    expect(fmtMoney('1234567.891')).toBe('1.234.567,89');
    expect(fmtMoney('0')).toBe('0,00');
    expect(fmtMoney(15)).toBe('15,00');
  });

  it('rounds half up like the backend', () => {
    expect(fmtMoney('2.345')).toBe('2,35');
    expect(fmtMoney('2.344')).toBe('2,34');
    expect(fmtMoney('1.005')).toBe('1,01');
    expect(fmtMoney('-2.345')).toBe('-2,35');
  });

  it('keeps large values exact', () => {
    expect(fmtMoney('9999999999999999.99')).toBe('9.999.999.999.999.999,99');
    expect(fmtMoney('0.1')).toBe('0,10');
  });

  it('formats negative amounts and never shows a negative zero', () => {
    expect(fmtMoney('-1234.5')).toBe('-1.234,50');
    expect(fmtMoney('-0.001')).toBe('0,00');
  });

  it('appends the currency when given', () => {
    expect(fmtMoney('1234.5', 'USD')).toBe('1.234,50 USD');
    expect(fmtMoney('1234.5', null)).toBe('1.234,50');
  });

  it('returns an empty string for missing or malformed values', () => {
    expect(fmtMoney(null)).toBe('');
    expect(fmtMoney(undefined)).toBe('');
    expect(fmtMoney('')).toBe('');
    expect(fmtMoney('abc')).toBe('');
    expect(fmtMoney(null, 'TRY')).toBe('');
  });
});

describe('fmtQty', () => {
  it('drops trailing zeros when no precision is given', () => {
    expect(fmtQty('12.000')).toBe('12');
    expect(fmtQty('12.500')).toBe('12,5');
    expect(fmtQty('1234.125')).toBe('1.234,125');
  });

  it('uses the fixed precision of the unit of measure', () => {
    expect(fmtQty('12', 3)).toBe('12,000');
    expect(fmtQty('12.500', 0)).toBe('13');
    expect(fmtQty('12.345', 2)).toBe('12,35');
  });
});

describe('fmtPrice', () => {
  it('shows at least two and at most six decimals', () => {
    expect(fmtPrice('12.500000')).toBe('12,50');
    expect(fmtPrice('0.123456')).toBe('0,123456');
    expect(fmtPrice('1250')).toBe('1.250,00');
    expect(fmtPrice('3.1234567')).toBe('3,123457');
  });
});

describe('fmtPct', () => {
  it('puts the percent sign first and trims zeros', () => {
    expect(fmtPct('20.0000')).toBe('%20');
    expect(fmtPct('12.5')).toBe('%12,5');
    expect(fmtPct('0')).toBe('%0');
    expect(fmtPct(null)).toBe('');
  });
});

describe('formatDecimal', () => {
  it('can leave out thousands separators for text that is being edited', () => {
    expect(formatDecimal('1234567.5', { minDecimals: 0, maxDecimals: 2, grouping: false })).toBe('1234567,5');
  });
});

describe('fmtDate / fmtDateTime', () => {
  it('formats ISO dates as DD.MM.YYYY', () => {
    expect(fmtDate('2025-03-07')).toBe('07.03.2025');
    expect(fmtDate('2024-12-31')).toBe('31.12.2024');
  });

  it('formats timestamps with hours and minutes', () => {
    expect(fmtDateTime('2025-03-07T09:05:00')).toBe('07.03.2025 09:05');
  });

  it('returns an empty string for missing or invalid values', () => {
    expect(fmtDate(null)).toBe('');
    expect(fmtDate(undefined)).toBe('');
    expect(fmtDate('')).toBe('');
    expect(fmtDate('not-a-date')).toBe('');
    expect(fmtDateTime(null)).toBe('');
  });
});

describe('fmtFileSize', () => {
  it('picks a readable unit', () => {
    expect(fmtFileSize(512)).toBe('512 B');
    expect(fmtFileSize(1536)).toBe('1,5 KB');
    expect(fmtFileSize(20 * 1024 * 1024)).toBe('20 MB');
  });
});

describe('parseTrNumber', () => {
  it('parses Turkish notation into a plain decimal string', () => {
    expect(parseTrNumber('1.234,56')).toBe('1234.56');
    expect(parseTrNumber('1234,56')).toBe('1234.56');
    expect(parseTrNumber('1.234.567')).toBe('1234567');
    expect(parseTrNumber('12')).toBe('12');
    expect(parseTrNumber('0,5')).toBe('0.5');
  });

  it('keeps the scale that was written', () => {
    expect(parseTrNumber('1,50')).toBe('1.50');
    expect(parseTrNumber('0,10')).toBe('0.10');
  });

  it('accepts shorthand while typing', () => {
    expect(parseTrNumber(',75')).toBe('0.75');
    expect(parseTrNumber('12,')).toBe('12');
    expect(parseTrNumber('007,5')).toBe('7.5');
    expect(parseTrNumber('  1.250,00 ')).toBe('1250.00');
    expect(parseTrNumber('1 250,5')).toBe('1250.5');
  });

  it('handles negative numbers and negative zero', () => {
    expect(parseTrNumber('-1.234,5')).toBe('-1234.5');
    expect(parseTrNumber('−3,2')).toBe('-3.2');
    expect(parseTrNumber('-0,00')).toBe('0.00');
  });

  it('rejects a dot that is not a thousands separator instead of guessing', () => {
    expect(parseTrNumber('12.5')).toBeNull();
    expect(parseTrNumber('1.23')).toBeNull();
    expect(parseTrNumber('1.2345')).toBeNull();
    expect(parseTrNumber('1,234.56')).toBeNull();
  });

  it('rejects empty and malformed text', () => {
    expect(parseTrNumber('')).toBeNull();
    expect(parseTrNumber(null)).toBeNull();
    expect(parseTrNumber(undefined)).toBeNull();
    expect(parseTrNumber('-')).toBeNull();
    expect(parseTrNumber(',')).toBeNull();
    expect(parseTrNumber('abc')).toBeNull();
    expect(parseTrNumber('1,2,3')).toBeNull();
    expect(parseTrNumber('12 TL')).toBeNull();
    expect(parseTrNumber('1e5')).toBeNull();
  });

  it('does not lose precision on long numbers', () => {
    expect(parseTrNumber('12.345.678.901.234.567,123456')).toBe('12345678901234567.123456');
  });
});
