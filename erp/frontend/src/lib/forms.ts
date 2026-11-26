import type { FormInstance } from 'antd';

import { ApiError } from './api';

export type FieldPath = (string | number)[];

export interface FieldIssue {
  path: FieldPath;
  message: string;
}

/** Cell errors of a line grid: row index → column field → message (`LinesEditor` `errors` prop). */
export type LineErrors = Record<number, Record<string, string>>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function toPath(raw: unknown): FieldPath | null {
  const parts: unknown[] | null = typeof raw === 'string' ? raw.split('.') : Array.isArray(raw) ? raw : null;
  if (parts === null) {
    return null;
  }
  const path = parts
    .filter((part): part is string | number => typeof part === 'string' || typeof part === 'number')
    .map((part) => (typeof part === 'string' && /^\d+$/.test(part) ? Number(part) : part));
  // Pydantic locations of request bodies start with "body".
  if (path.length > 1 && path[0] === 'body') {
    path.shift();
  }
  return path.length > 0 ? path : null;
}

function toMessages(raw: unknown): string[] {
  const values = Array.isArray(raw) ? raw : [raw];
  return values.filter((value): value is string => typeof value === 'string' && value !== '');
}

/**
 * Reads `details.fields` of a validation error. Both representations of field errors are
 * understood: a map (`{"lines.0.quantity": "..."}`, values may be lists) and a list of
 * `{field | loc, message | msg}` objects.
 */
export function fieldIssues(error: unknown): FieldIssue[] {
  const fields = error instanceof ApiError ? error.details?.fields : undefined;
  const issues: FieldIssue[] = [];
  const add = (rawPath: unknown, rawMessages: unknown): void => {
    const path = toPath(rawPath);
    if (path !== null) {
      toMessages(rawMessages).forEach((message) => issues.push({ path, message }));
    }
  };
  if (Array.isArray(fields)) {
    fields.filter(isRecord).forEach((item) => add(item.field ?? item.loc, item.message ?? item.msg));
  } else if (isRecord(fields)) {
    Object.entries(fields).forEach(([key, value]) => add(key, value));
  }
  return issues;
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
