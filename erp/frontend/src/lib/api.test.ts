import { AxiosError, AxiosHeaders, CanceledError, type InternalAxiosRequestConfig } from 'axios';
import { describe, expect, it } from 'vitest';

import {
  ApiError,
  apiErrorFromResponse,
  cleanParams,
  errorMessage,
  filenameFromDisposition,
  isSessionExpiry,
  normalizeError,
} from './api';

const config: InternalAxiosRequestConfig = { headers: new AxiosHeaders() };

function httpError(status: number, data: unknown): AxiosError {
  return new AxiosError(`Request failed with status code ${status}`, AxiosError.ERR_BAD_RESPONSE, config, null, {
    status,
    statusText: '',
    data,
    headers: {},
    config,
  });
}

async function normalized(error: unknown): Promise<ApiError> {
  const result = await normalizeError(error);
  expect(result).toBeInstanceOf(ApiError);
  return result as ApiError;
}

describe('apiErrorFromResponse', () => {
  it('takes code, message and details from the error contract', () => {
    const error = apiErrorFromResponse(409, {
      code: 'STALE_DATA',
      message: 'Kayıt başka bir kullanıcı tarafından değiştirildi.',
      details: { current_version: 4 },
    });
    expect(error).toBeInstanceOf(Error);
    expect(error.name).toBe('ApiError');
    expect(error.status).toBe(409);
    expect(error.code).toBe('STALE_DATA');
    expect(error.message).toBe('Kayıt başka bir kullanıcı tarafından değiştirildi.');
    expect(error.details).toEqual({ current_version: 4 });
  });

  it('normalises missing or non-object details to null', () => {
    expect(apiErrorFromResponse(400, { code: 'X', message: 'm' }).details).toBeNull();
    expect(apiErrorFromResponse(400, { code: 'X', message: 'm', details: null }).details).toBeNull();
    expect(apiErrorFromResponse(400, { code: 'X', message: 'm', details: ['a'] }).details).toBeNull();
  });

  it('falls back to a Turkish message per status when the body is not the contract shape', () => {
    expect(apiErrorFromResponse(403, '<html>Forbidden</html>')).toMatchObject({
      status: 403,
      code: 'FORBIDDEN',
      message: 'Bu işlem için yetkiniz yok.',
    });
    expect(apiErrorFromResponse(404, { detail: 'Not Found' })).toMatchObject({ code: 'NOT_FOUND', message: 'Kayıt bulunamadı.' });
    expect(apiErrorFromResponse(401, null).code).toBe('UNAUTHORIZED');
    expect(apiErrorFromResponse(413, '').code).toBe('PAYLOAD_TOO_LARGE');
    expect(apiErrorFromResponse(502, 'Bad Gateway')).toMatchObject({ status: 502, code: 'SERVER_ERROR' });
    expect(apiErrorFromResponse(418, undefined)).toMatchObject({ status: 418, code: 'HTTP_ERROR' });
  });

  it('ignores bodies that only look similar to the contract', () => {
    expect(apiErrorFromResponse(400, { code: 123, message: 'm' }).code).toBe('HTTP_ERROR');
    expect(apiErrorFromResponse(400, { code: 'X' }).code).toBe('HTTP_ERROR');
  });
});

describe('normalizeError', () => {
  it('converts an HTTP error response', async () => {
    const error = await normalized(httpError(400, { code: 'PERIOD_CLOSED', message: 'Dönem kapalı.', details: {} }));
    expect(error).toMatchObject({ status: 400, code: 'PERIOD_CLOSED', message: 'Dönem kapalı.', details: {} });
  });

  it('keeps the field details of validation errors', async () => {
    const fields = { 'lines.0.quantity': 'Miktar sıfırdan büyük olmalıdır' };
    const error = await normalized(
      httpError(422, { code: 'VALIDATION_ERROR', message: 'Girilen bilgiler geçersiz.', details: { fields } }),
    );
    expect(error.status).toBe(422);
    expect(error.details).toEqual({ fields });
  });

  it('reads error bodies of blob downloads', async () => {
    const blob = new Blob([JSON.stringify({ code: 'NOT_FOUND', message: 'Belge bulunamadı.' })], {
      type: 'application/json',
    });
    const error = await normalized(httpError(404, blob));
    expect(error).toMatchObject({ status: 404, code: 'NOT_FOUND', message: 'Belge bulunamadı.' });
  });

  it('falls back when a blob body is not JSON', async () => {
    const error = await normalized(httpError(500, new Blob(['<html>'], { type: 'text/html' })));
    expect(error).toMatchObject({ status: 500, code: 'SERVER_ERROR' });
  });

  it('reports a missing response as a network error with status 0', async () => {
    const error = await normalized(new AxiosError('Network Error', AxiosError.ERR_NETWORK, config));
    expect(error).toMatchObject({ status: 0, code: 'NETWORK_ERROR' });
    expect(error.message).toContain('Sunucuya ulaşılamıyor');
  });

  it('wraps anything else as an unexpected error', async () => {
    const error = await normalized(new TypeError('boom'));
    expect(error).toMatchObject({ status: 0, code: 'UNEXPECTED_ERROR', message: 'Beklenmeyen bir hata oluştu.' });
  });

  it('passes ApiError and cancellations through untouched', async () => {
    const apiError = new ApiError(400, 'X', 'm');
    expect(await normalizeError(apiError)).toBe(apiError);
    const cancelled = new CanceledError('canceled');
    expect(await normalizeError(cancelled)).toBe(cancelled);
  });
});

describe('isSessionExpiry', () => {
  it('is true for a rejected token only', () => {
    expect(isSessionExpiry(new ApiError(401, 'TOKEN_EXPIRED', 'm'))).toBe(true);
    expect(isSessionExpiry(new ApiError(401, 'INVALID_CREDENTIALS', 'm'))).toBe(false);
    expect(isSessionExpiry(new ApiError(403, 'FORBIDDEN', 'm'))).toBe(false);
    expect(isSessionExpiry(new Error('m'))).toBe(false);
  });
});

describe('errorMessage', () => {
  it('uses the server message of an ApiError and a generic text otherwise', () => {
    expect(errorMessage(new ApiError(400, 'X', 'Dönem kapalı.'))).toBe('Dönem kapalı.');
    expect(errorMessage(new Error('internal detail'))).toBe('Beklenmeyen bir hata oluştu.');
    expect(errorMessage('text')).toBe('Beklenmeyen bir hata oluştu.');
  });
});

describe('cleanParams', () => {
  it('drops empty values and keeps meaningful falsy ones', () => {
    expect(
      cleanParams({ q: '', page: 1, sort: undefined, plant_id: null, is_active: false, level: 0, status: ['A', 'B'], tags: [] }),
    ).toEqual({ page: 1, is_active: false, level: 0, status: ['A', 'B'] });
  });
});

describe('filenameFromDisposition', () => {
  it('reads quoted and bare filenames', () => {
    expect(filenameFromDisposition('attachment; filename="SIP0000042.pdf"')).toBe('SIP0000042.pdf');
    expect(filenameFromDisposition('attachment; filename=mizan-2025-03.xlsx')).toBe('mizan-2025-03.xlsx');
    expect(filenameFromDisposition('attachment; filename="a \\"b\\".pdf"')).toBe('a "b".pdf');
  });

  it('prefers the RFC 5987 form', () => {
    expect(
      filenameFromDisposition("attachment; filename=\"siparis.pdf\"; filename*=UTF-8''sipari%C5%9F%20%C3%B6zeti.pdf"),
    ).toBe('sipariş özeti.pdf');
  });

  it('falls back to the plain form when the encoded one is malformed', () => {
    expect(filenameFromDisposition("attachment; filename=\"yedek.pdf\"; filename*=UTF-8''%E0%A4%A")).toBe('yedek.pdf');
  });

  it('returns null without a filename', () => {
    expect(filenameFromDisposition(undefined)).toBeNull();
    expect(filenameFromDisposition('')).toBeNull();
    expect(filenameFromDisposition('inline')).toBeNull();
  });
});
