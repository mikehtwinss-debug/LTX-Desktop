import { describe, expect, it } from 'vitest';

import { parseEditText, parsePastedNumber, sanitizeDecimalText, toEditText } from './numberText';

describe('toEditText', () => {
  it('shows the value without thousands separators or padding zeros', () => {
    expect(toEditText('1234.50', 2)).toBe('1234,5');
    expect(toEditText('12.000', 3)).toBe('12');
    expect(toEditText('-0.25', 2)).toBe('-0,25');
    expect(toEditText(null, 2)).toBe('');
  });
});

describe('sanitizeDecimalText', () => {
  it('turns the keypad dot into a decimal comma', () => {
    expect(sanitizeDecimalText('12.5', 2, false)).toBe('12,5');
    expect(sanitizeDecimalText('12.', 2, false)).toBe('12,');
  });

  it('drops everything that is not part of a number', () => {
    expect(sanitizeDecimalText('1a2b,3c', 2, false)).toBe('12,3');
    expect(sanitizeDecimalText('1,2,3', 3, false)).toBe('1,23');
    expect(sanitizeDecimalText('₺ 45', 2, false)).toBe('45');
  });

  it('cuts decimals beyond the scale of the field', () => {
    expect(sanitizeDecimalText('1,23456', 2, false)).toBe('1,23');
    expect(sanitizeDecimalText('1,2345678', 6, false)).toBe('1,234567');
    expect(sanitizeDecimalText('12,5', 0, false)).toBe('12');
    expect(sanitizeDecimalText('12,', 0, false)).toBe('12');
  });

  it('keeps a leading minus only where negatives are allowed', () => {
    expect(sanitizeDecimalText('-12,5', 2, true)).toBe('-12,5');
    expect(sanitizeDecimalText('-12,5', 2, false)).toBe('12,5');
    expect(sanitizeDecimalText('12-5', 2, true)).toBe('125');
    expect(sanitizeDecimalText('-', 2, true)).toBe('-');
  });
});

describe('parseEditText', () => {
  it('returns the value at the scale of the field', () => {
    expect(parseEditText('12,5', 2)).toBe('12.50');
    expect(parseEditText('12,', 2)).toBe('12.00');
    expect(parseEditText('8', 0)).toBe('8');
    expect(parseEditText(',5', 3)).toBe('0.500');
    expect(parseEditText('-3,25', 2)).toBe('-3.25');
  });

  it('is null while the text holds no number', () => {
    expect(parseEditText('', 2)).toBeNull();
    expect(parseEditText('-', 2)).toBeNull();
    expect(parseEditText(',', 2)).toBeNull();
  });
});

describe('parsePastedNumber', () => {
  it('reads Turkish notation', () => {
    expect(parsePastedNumber('1.234,56')).toBe('1234.56');
    expect(parsePastedNumber(' 1.250 ')).toBe('1250');
    expect(parsePastedNumber('12,5')).toBe('12.5');
  });

  it('reads plain dot-decimal notation when the text cannot be Turkish', () => {
    expect(parsePastedNumber('12.5')).toBe('12.5');
    expect(parsePastedNumber('-1234.5678')).toBe('-1234.5678');
  });

  it('rejects anything else', () => {
    expect(parsePastedNumber('1,234.56')).toBeNull();
    expect(parsePastedNumber('abc')).toBeNull();
    expect(parsePastedNumber('')).toBeNull();
  });
});
