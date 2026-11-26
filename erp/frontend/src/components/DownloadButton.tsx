import { DownloadOutlined, FileExcelOutlined, FilePdfOutlined } from '@ant-design/icons';
import { App, Button, type ButtonProps } from 'antd';
import { type ReactNode, useState } from 'react';

import { downloadFile, errorMessage, type QueryParams } from '@/lib/api';

type DownloadFormat = 'pdf' | 'xlsx';

export interface DownloadButtonProps extends Omit<ButtonProps, 'onClick' | 'loading' | 'href' | 'icon'> {
  /** Download endpoint relative to `/api`, e.g. `/mm/purchase-orders/42/pdf`. */
  url: string;
  params?: QueryParams;
  /** Picks icon and default label. */
  format?: DownloadFormat;
}

const FORMATS: Record<DownloadFormat, { icon: ReactNode; label: string }> = {
  pdf: { icon: <FilePdfOutlined />, label: 'PDF' },
  xlsx: { icon: <FileExcelOutlined />, label: 'Excel' },
};

/**
 * Downloads a server-built file with the user's session and saves it under the server's filename.
 *
 *   <DownloadButton url={`/mm/purchase-orders/${id}/pdf`} format="pdf" />
 *   <DownloadButton url="/fi/reports/trial-balance/xlsx" params={{ year: 2025 }} format="xlsx">Excel'e aktar</DownloadButton>
 */
export function DownloadButton({ url, params, format, children, ...buttonProps }: DownloadButtonProps): ReactNode {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const preset = format ? FORMATS[format] : { icon: <DownloadOutlined />, label: 'İndir' };

  const handleClick = async (): Promise<void> => {
    setLoading(true);
    try {
      await downloadFile(url, params);
    } catch (error) {
      void message.error(errorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Button {...buttonProps} icon={preset.icon} loading={loading} onClick={() => void handleClick()}>
      {children ?? preset.label}
    </Button>
  );
}
