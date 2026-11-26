import { BarcodeOutlined, LoadingOutlined } from '@ant-design/icons';
import { Input, type InputProps, type InputRef } from 'antd';
import { type KeyboardEvent, type ReactNode, useEffect, useRef, useState } from 'react';

export interface BarcodeInputProps
  extends Pick<InputProps, 'placeholder' | 'disabled' | 'autoFocus' | 'size' | 'style' | 'id' | 'aria-label'> {
  /** Called with every code completed by Enter. While a returned promise is pending a spinner is shown. */
  onScan: (code: string) => void | Promise<unknown>;
  /**
   * Also receive scans made while no input field has the focus, so that a warehouse user can scan
   * without clicking into the field first.
   */
  captureGlobal?: boolean;
}

function isEditable(element: Element | null): boolean {
  return (
    element instanceof HTMLInputElement ||
    element instanceof HTMLTextAreaElement ||
    element instanceof HTMLSelectElement ||
    (element instanceof HTMLElement && element.isContentEditable)
  );
}

/**
 * Field for keyboard-wedge barcode scanners, which type the code and finish with Enter. After
 * each scan the field is emptied and stays focused for the next one; codes can be typed by hand
 * as well.
 *
 *   <BarcodeInput autoFocus captureGlobal onScan={(code) => addMaterialByBarcode(code)} />
 */
export function BarcodeInput({
  onScan,
  captureGlobal = false,
  placeholder = 'Barkod okutun veya yazıp Enter’a basın',
  disabled,
  ...inputProps
}: BarcodeInputProps): ReactNode {
  const inputRef = useRef<InputRef>(null);
  const [text, setText] = useState('');
  const [pending, setPending] = useState(0);

  useEffect(() => {
    if (!captureGlobal || disabled) {
      return undefined;
    }
    // Focusing the field during keydown makes the character that is being typed land in it.
    const redirect = (event: globalThis.KeyboardEvent): void => {
      const printable = event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey;
      if (printable && !isEditable(document.activeElement)) {
        inputRef.current?.focus();
      }
    };
    document.addEventListener('keydown', redirect);
    return () => document.removeEventListener('keydown', redirect);
  }, [captureGlobal, disabled]);

  const handleEnter = (event: KeyboardEvent<HTMLInputElement>): void => {
    // Inside a form Enter must not submit; the scan is the action.
    event.preventDefault();
    const code = event.currentTarget.value.trim();
    setText('');
    if (code === '') {
      return;
    }
    setPending((count) => count + 1);
    void Promise.resolve(onScan(code))
      .catch(() => undefined)
      .finally(() => setPending((count) => count - 1));
  };

  return (
    <Input
      autoComplete="off"
      spellCheck={false}
      {...inputProps}
      ref={inputRef}
      disabled={disabled}
      placeholder={placeholder}
      prefix={<BarcodeOutlined />}
      suffix={pending > 0 ? <LoadingOutlined /> : undefined}
      value={text}
      onChange={(event) => setText(event.target.value)}
      onPressEnter={handleEnter}
    />
  );
}
