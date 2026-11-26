import type { FormInstance } from 'antd';
import { describe, expect, it } from 'vitest';

import { ApiError } from './api';
import { applyApiErrorsToForm, fieldIssues, lineErrorsFromApi } from './forms';

function validationError(fields: unknown): ApiError {
  return new ApiError(422, 'VALIDATION_ERROR', 'Girilen bilgiler geçersiz.', { fields });
}

interface AppliedField {
  name: (string | number)[];
  errors: string[];
}

/** The slice of an Ant Design form instance that `applyApiErrorsToForm` relies on. */
function fakeForm(registered: (string | number)[][]): { form: FormInstance; applied: AppliedField[]; scrolledTo: unknown[] } {
  const applied: AppliedField[] = [];
  const scrolledTo: unknown[] = [];
  const form = {
    getFieldsError: () => registered.map((name) => ({ name, errors: [], warnings: [] })),
    setFields: (fields: AppliedField[]) => applied.push(...fields),
    scrollToField: (name: unknown) => scrolledTo.push(name),
  } as unknown as FormInstance;
  return { form, applied, scrolledTo };
}

describe('fieldIssues', () => {
  it('reads a map of dotted paths, with one or several messages', () => {
    const issues = fieldIssues(validationError({ name: 'Ad zorunludur', 'lines.0.quantity': ['Geçersiz miktar', 'Çok büyük'] }));
    expect(issues).toEqual([
      { path: ['name'], message: 'Ad zorunludur' },
      { path: ['lines', 0, 'quantity'], message: 'Geçersiz miktar' },
      { path: ['lines', 0, 'quantity'], message: 'Çok büyük' },
    ]);
  });

  it('reads a list of field/message objects and Pydantic locations', () => {
    const issues = fieldIssues(
      validationError([
        { field: 'vendor_id', message: 'Satıcı seçilmelidir' },
        { loc: ['body', 'lines', 2, 'unit_price'], msg: 'Fiyat girilmelidir' },
      ]),
    );
    expect(issues).toEqual([
      { path: ['vendor_id'], message: 'Satıcı seçilmelidir' },
      { path: ['lines', 2, 'unit_price'], message: 'Fiyat girilmelidir' },
    ]);
  });

  it('keeps a field that is itself called body', () => {
    expect(fieldIssues(validationError({ body: 'Metin zorunludur' }))).toEqual([{ path: ['body'], message: 'Metin zorunludur' }]);
  });

  it('is empty for errors without field details', () => {
    expect(fieldIssues(new ApiError(400, 'PERIOD_CLOSED', 'Dönem kapalı.'))).toEqual([]);
    expect(fieldIssues(new ApiError(422, 'VALIDATION_ERROR', 'm', { fields: 'oops' }))).toEqual([]);
    expect(fieldIssues(new Error('x'))).toEqual([]);
    expect(fieldIssues(validationError({ name: 42, code: [null, ''] }))).toEqual([]);
  });
});

describe('applyApiErrorsToForm', () => {
  it('sets the errors on the matching fields and scrolls to the first one', () => {
    const { form, applied, scrolledTo } = fakeForm([['code'], ['name'], ['address', 'city']]);
    const unmatched = applyApiErrorsToForm(
      form,
      validationError({ name: 'Ad zorunludur', 'address.city': 'Şehir zorunludur' }),
    );
    expect(unmatched).toEqual([]);
    expect(applied).toEqual([
      { name: ['name'], errors: ['Ad zorunludur'] },
      { name: ['address', 'city'], errors: ['Şehir zorunludur'] },
    ]);
    expect(scrolledTo).toEqual([['name']]);
  });

  it('attaches line errors to the field holding the lines, with the row number', () => {
    const { form, applied } = fakeForm([['vendor_id'], ['lines']]);
    applyApiErrorsToForm(form, validationError({ 'lines.1.quantity': 'Miktar sıfırdan büyük olmalıdır', lines: 'En az bir satır girin' }));
    expect(applied).toEqual([
      { name: ['lines'], errors: ['2. satır: Miktar sıfırdan büyük olmalıdır', 'En az bir satır girin'] },
    ]);
  });

  it('prefers the most specific registered field', () => {
    const { form, applied } = fakeForm([['lines'], ['lines', 0, 'quantity']]);
    applyApiErrorsToForm(form, validationError({ 'lines.0.quantity': 'Geçersiz' }));
    expect(applied).toEqual([{ name: ['lines', 0, 'quantity'], errors: ['Geçersiz'] }]);
  });

  it('returns the messages that belong to no field of the form', () => {
    const { form, applied, scrolledTo } = fakeForm([['name']]);
    expect(applyApiErrorsToForm(form, validationError({ tax_number: 'Vergi numarası geçersiz' }))).toEqual([
      'Vergi numarası geçersiz',
    ]);
    expect(applied).toEqual([]);
    expect(scrolledTo).toEqual([]);
  });

  it('does nothing for errors without field details', () => {
    const { form, applied } = fakeForm([['name']]);
    expect(applyApiErrorsToForm(form, new ApiError(409, 'STALE_DATA', 'm'))).toEqual([]);
    expect(applied).toEqual([]);
  });
});

describe('lineErrorsFromApi', () => {
  it('collects cell errors by row and column, first message wins', () => {
    const error = validationError({
      'lines.0.quantity': ['Geçersiz miktar', 'İkinci mesaj'],
      'lines.2.material_id': 'Malzeme seçilmelidir',
      'other.0.quantity': 'Başka bir tablo',
      lines: 'En az bir satır girin',
      vendor_id: 'Satıcı seçilmelidir',
    });
    expect(lineErrorsFromApi(error, 'lines')).toEqual({
      0: { quantity: 'Geçersiz miktar' },
      2: { material_id: 'Malzeme seçilmelidir' },
    });
  });
});
