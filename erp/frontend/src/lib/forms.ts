import type { FormInstance } from 'antd';

import { ApiError } from './api';

export type FieldPath = (string | number)[];

export interface FieldIssue {
  path: FieldPath;
  message: string;
}

/** Cell errors of a line grid: row index → column field → message (`LinesEditor` `errors` prop). */
export type LineErrors = Record<number, Record<string, string>>;

function toPath(key: string): FieldPath {
  return key.split('.').map((part) => (/^\d+$/.test(part) ? Number(part) : part));
}

/**
 * Field errors of a failed request: `details.fields` maps dotted paths to messages,
 * e.g. `{"vendor_id": "Bu alan zorunludur", "lines.0.quantity": "0 değerinden büyük olmalıdır"}`.
 */
export function fieldIssues(error: unknown): FieldIssue[] {
  const fields = error instanceof ApiError ? error.details?.fields : undefined;
  if (typeof fields !== 'object' || fields === null) {
    return [];
  }
  return Object.entries(fields).flatMap(([key, message]) =>
    typeof message === 'string' && message !== '' ? [{ path: toPath(key), message }] : [],
  );
}

function startsWith(path: FieldPath, prefix: FieldPath): boolean {
  return prefix.length <= path.length && prefix.every((part, index) => String(part) === String(path[index]));
}

/**
 * Shows the field errors of a failed request on an Ant Design form:
 *
 *   onError: (error) => applyApiErrorsToForm(form, error)
 *
 * An error below a registered field (`lines.2.quantity` when the form has a `lines` field holding
 * a `LinesEditor`) is attached to that field with its row number. Returns the messages that belong
 * to no field of the form, so that the caller can show them elsewhere.
 */
export function applyApiErrorsToForm(form: FormInstance, error: unknown): string[] {
  const registered = form.getFieldsError().map((field) => field.name as FieldPath);
  const byField = new Map<string, { name: FieldPath; errors: string[] }>();
  const unmatched: string[] = [];

  for (const issue of fieldIssues(error)) {
    const name = registered
      .filter((candidate) => candidate.length > 0 && startsWith(issue.path, candidate))
      .sort((a, b) => b.length - a.length)[0];
    if (name === undefined) {
      unmatched.push(issue.message);
      continue;
    }
    const row = issue.path[name.length];
    const text = typeof row === 'number' ? `${row + 1}. satır: ${issue.message}` : issue.message;
    const key = name.join('.');
    const entry = byField.get(key) ?? { name, errors: [] };
    entry.errors.push(text);
    byField.set(key, entry);
  }

  const fields = [...byField.values()];
  if (fields.length > 0) {
    form.setFields(fields);
    form.scrollToField(fields[0]!.name, { block: 'center' });
  }
  return unmatched;
}

/**
 * Cell errors for a `LinesEditor` bound to form field `field`: issues located at
 * `<field>.<row>.<column>`.
 */
export function lineErrorsFromApi(error: unknown, field: string): LineErrors {
  const errors: LineErrors = {};
  for (const { path, message } of fieldIssues(error)) {
    const [root, row, column] = path;
    if (root === field && typeof row === 'number' && typeof column === 'string') {
      const cells = (errors[row] ??= {});
      cells[column] ??= message;
    }
  }
  return errors;
}
