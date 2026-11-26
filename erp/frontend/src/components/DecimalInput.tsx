import { Input, type InputProps, type InputRef } from 'antd';
import {
  type ChangeEvent,
  type ClipboardEvent,
  type FocusEvent,
  type ReactNode,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';

import { formatDecimal } from '@/lib/format';

import { parseEditText, parsePastedNumber, sanitizeDecimalText, toEditText } from './numberText';

export interface DecimalInputProps extends Omit<InputProps, 'value' | 'defaultValue' | 'onChange' | 'type'> {
  /** Plain decimal string as used by the API (`"1234.50"`), or `null` when empty. */
  value?: string | null;
  onChange?: (value: string | null) => void;
  /** Largest number of decimals that can be entered; emitted values always have this scale. */
  decimals: number;
  /** Decimals always shown while the field is not edited. Default: `decimals`. */
  minDecimals?: number;
  allowNegative?: boolean;
}

interface Draft {
  text: string;
  /** The value reported for `text`; a different `value` prop means it was changed from outside. */
  emitted: string | null;
}

/**
 * Base of the numeric inputs. Controlled (`value` + `onChange`, as provided by `Form.Item`); the
 * value is a decimal string and never a float. Shows Turkish notation (`1.234,56`), accepts a
 * comma or the keypad dot as decimal separator and understands pasted `1.234,56`.
 *
 *   <Form.Item name="exchange_rate" label="Kur"><DecimalInput decimals={6} minDecimals={4} /></Form.Item>
 */
export function DecimalInput({
  value,
  onChange,
  decimals,
  minDecimals = decimals,
  allowNegative = false,
  onFocus,
  onBlur,
  styles,
  ...inputProps
}: DecimalInputProps): ReactNode {
  const current = value ?? null;
  const inputRef = useRef<InputRef>(null);
  const pendingCaret = useRef<number | null>(null);
  const [focused, setFocused] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);

  const text = !focused
    ? formatDecimal(current, { minDecimals, maxDecimals: decimals })
    : draft !== null && draft.emitted === current
      ? draft.text
      : toEditText(current, decimals);

  // Entering the field selects its content, so typing replaces the old number.
  useLayoutEffect(() => {
    if (focused) {
      inputRef.current?.select();
    }
  }, [focused]);

  // Keeps the caret in place when typed text had to be corrected (React would move it to the end).
  useLayoutEffect(() => {
    if (pendingCaret.current !== null) {
      inputRef.current?.setSelectionRange(pendingCaret.current, pendingCaret.current);
      pendingCaret.current = null;
    }
  });

  const applyText = (nextText: string): void => {
    const emitted = parseEditText(nextText, decimals);
    setDraft({ text: nextText, emitted });
    if (emitted !== current) {
      onChange?.(emitted);
    }
  };

  const handleChange = (event: ChangeEvent<HTMLInputElement>): void => {
    const raw = event.target.value;
    const nextText = sanitizeDecimalText(raw, decimals, allowNegative);
    if (nextText !== raw) {
      const caret = event.target.selectionStart ?? raw.length;
      pendingCaret.current = sanitizeDecimalText(raw.slice(0, caret), decimals, allowNegative).length;
    }
    applyText(nextText);
  };

  const handlePaste = (event: ClipboardEvent<HTMLInputElement>): void => {
    const pasted = parsePastedNumber(event.clipboardData.getData('text'));
    if (pasted !== null) {
      event.preventDefault();
      applyText(sanitizeDecimalText(toEditText(pasted, decimals), decimals, allowNegative));
    }
  };

  const handleFocus = (event: FocusEvent<HTMLInputElement>): void => {
    setDraft(null);
    setFocused(true);
    onFocus?.(event);
  };

  const handleBlur = (event: FocusEvent<HTMLInputElement>): void => {
    setFocused(false);
    setDraft(null);
    onBlur?.(event);
  };

  return (
    <Input
      autoComplete="off"
      inputMode="decimal"
      {...inputProps}
      ref={inputRef}
      value={text}
      styles={{ ...styles, input: { textAlign: 'right', fontVariantNumeric: 'tabular-nums', ...styles?.input } }}
      onChange={handleChange}
      onPaste={handlePaste}
      onFocus={handleFocus}
      onBlur={handleBlur}
    />
  );
}
