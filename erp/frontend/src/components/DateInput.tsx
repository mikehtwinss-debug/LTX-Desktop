import { DatePicker, type DatePickerProps } from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import type { ReactNode } from 'react';

const ISO_DATE = 'YYYY-MM-DD';

function toDayjs(value: string | null | undefined): Dayjs | undefined {
  if (!value) {
    return undefined;
  }
  const date = dayjs(value);
  return date.isValid() ? date : undefined;
}

export interface DateInputProps extends Pick<
  DatePickerProps,
  | 'id'
  | 'placeholder'
  | 'disabled'
  | 'allowClear'
  | 'size'
  | 'status'
  | 'variant'
  | 'style'
  | 'className'
  | 'autoFocus'
  | 'onBlur'
  | 'aria-label'
> {
  /** ISO date (`YYYY-MM-DD`) or `null`. */
  value?: string | null;
  onChange?: (value: string | null) => void;
  /** Earliest and latest selectable ISO dates. */
  min?: string | null;
  max?: string | null;
}

/**
 * Business date field. The value is an ISO date string; the user sees and types `GG.AA.YYYY`
 * (digits only, the separators are filled in).
 *
 *   <Form.Item name="posting_date" label="Kayıt tarihi"><DateInput /></Form.Item>
 */
export function DateInput({ value, onChange, min, max, style, ...pickerProps }: DateInputProps): ReactNode {
  return (
    <DatePicker
      placeholder="GG.AA.YYYY"
      {...pickerProps}
      style={{ width: '100%', ...style }}
      format={{ format: 'DD.MM.YYYY', type: 'mask' }}
      value={toDayjs(value) ?? null}
      minDate={toDayjs(min)}
      maxDate={toDayjs(max)}
      onChange={(date: Dayjs | null) => onChange?.(date ? date.format(ISO_DATE) : null)}
    />
  );
}
