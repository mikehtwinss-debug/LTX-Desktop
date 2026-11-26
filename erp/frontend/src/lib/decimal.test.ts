import Big from 'big.js';
import { describe, expect, it } from 'vitest';

import { mul, parseDecimal, pctOf, round, sum, toBig, toDecimalString } from './decimal';

describe('parseDecimal / toBig', () => {
  it('parses decimal strings exactly', () => {
    expect(parseDecimal('0.1')?.plus('0.2').toString()).toBe('0.3');
    expect(parseDecimal('12345678901234567.89')?.toString()).toBe('12345678901234567.89');
  });

  it('returns null for empty or malformed input', () => {
    expect(parseDecimal(null)).toBeNull();
    expect(parseDecimal(undefined)).toBeNull();
    expect(parseDecimal('')).toBeNull();
    expect(parseDecimal('1,5')).toBeNull();
    expect(parseDecimal('abc')).toBeNull();
  });

  it('treats empty input as zero in arithmetic', () => {
    expect(toBig(null).toString()).toBe('0');
    expect(toBig('').toString()).toBe('0');
    expect(toBig(new Big('2.5')).toString()).toBe('2.5');
  });
});

describe('sum', () => {
  it('adds without binary rounding errors', () => {
    expect(sum(['0.1', '0.2']).toString()).toBe('0.3');
    expect(sum(Array.from({ length: 10 }, () => '0.1')).toString()).toBe('1');
  });

  it('skips empty values and accepts mixed input', () => {
    expect(sum(['10.50', null, undefined, '', 2, new Big('0.25')]).toString()).toBe('12.75');
    expect(sum([]).toString()).toBe('0');
  });
});

describe('mul', () => {
  it('multiplies exactly', () => {
    expect(mul('1.15', '100').toString()).toBe('115');
    expect(mul('125.500', '48.750000').toString()).toBe('6118.125');
  });

  it('is zero when a factor is missing', () => {
    expect(mul(null, '48.75').toString()).toBe('0');
    expect(mul('3', undefined).toString()).toBe('0');
  });
});

describe('round', () => {
  it('rounds half up at the given scale', () => {
    expect(round('6118.125', 2).toString()).toBe('6118.13');
    expect(round('2.345', 2).toString()).toBe('2.35');
    expect(round('2.5', 0).toString()).toBe('3');
    expect(round('1.0005', 3).toString()).toBe('1.001');
  });

  it('rounds negative values away from zero on a tie', () => {
    expect(round('-2.345', 2).toString()).toBe('-2.35');
  });
});

describe('pctOf', () => {
  it('computes a percentage of an amount', () => {
    expect(pctOf('1000', '20').toString()).toBe('200');
    expect(round(pctOf('6118.13', '5.0000'), 2).toString()).toBe('305.91');
    expect(pctOf('1000', null).toString()).toBe('0');
  });
});

describe('toDecimalString', () => {
  it('produces the plain fixed-scale string the API expects', () => {
    expect(toDecimalString('2.5', 2)).toBe('2.50');
    expect(toDecimalString('1234.5678', 2)).toBe('1234.57');
    expect(toDecimalString(new Big('7'), 3)).toBe('7.000');
    expect(toDecimalString('12', 0)).toBe('12');
  });

  it('never writes a negative zero or an exponent', () => {
    expect(toDecimalString('-0.001', 2)).toBe('0.00');
    expect(toDecimalString('1e21', 2)).toBe('1000000000000000000000.00');
    expect(toDecimalString('0.0000001', 6)).toBe('0.000000');
  });
});
