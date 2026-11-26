import { Button, type ButtonProps, Popconfirm } from 'antd';
import type { ReactNode } from 'react';

export interface ConfirmButtonProps extends Omit<ButtonProps, 'onClick'> {
  /** The question asked before the action runs. */
  confirmTitle: ReactNode;
  confirmDescription?: ReactNode;
  /**
   * Runs after the user confirms. While a returned promise is pending the confirmation shows
   * progress. Failures are the caller's to report (mutations already do so globally).
   */
  onConfirm: () => void | Promise<unknown>;
  okText?: string;
  cancelText?: string;
}

/**
 * Button that asks before acting.
 *
 *   <ConfirmButton danger confirmTitle="Sipariş iptal edilsin mi?" onConfirm={() => cancel.mutateAsync(id)}>
 *     İptal et
 *   </ConfirmButton>
 */
export function ConfirmButton({
  confirmTitle,
  confirmDescription,
  onConfirm,
  okText = 'Evet',
  cancelText = 'Vazgeç',
  ...buttonProps
}: ConfirmButtonProps): ReactNode {
  const handleConfirm = async (): Promise<void> => {
    try {
      await onConfirm();
    } catch {
      // The popup only needs to close; the error has been reported by whoever raised it.
    }
  };

  return (
    <Popconfirm
      title={confirmTitle}
      description={confirmDescription}
      okText={okText}
      cancelText={cancelText}
      okButtonProps={{ danger: buttonProps.danger }}
      disabled={buttonProps.disabled}
      onConfirm={handleConfirm}
    >
      <Button {...buttonProps} />
    </Popconfirm>
  );
}
