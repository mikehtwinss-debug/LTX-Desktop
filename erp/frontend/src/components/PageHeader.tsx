import { ArrowLeftOutlined } from '@ant-design/icons';
import { Button, Flex, Typography } from 'antd';
import { type ReactNode, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

export interface PageHeaderProps {
  /** Page title; also becomes the browser tab title. */
  title: string;
  subtitle?: ReactNode;
  /** Route the back arrow leads to, e.g. the list a document belongs to. */
  backTo?: string;
  /** Shown next to the title, typically a `StatusTag`. */
  tags?: ReactNode;
  /** Actions on the right-hand side. */
  extra?: ReactNode;
  /** Content below the title row. */
  children?: ReactNode;
}

const APP_TITLE = 'ERP';

/**
 * Title bar of a page.
 *
 *   <PageHeader
 *     title="SIP0000042"
 *     subtitle="Satınalma siparişi"
 *     backTo="/mm/siparis"
 *     tags={<StatusTag map={PO_STATUS} value={order.status} />}
 *     extra={<Button type="primary">Onaya gönder</Button>}
 *   />
 */
export function PageHeader({ title, subtitle, backTo, tags, extra, children }: PageHeaderProps): ReactNode {
  const navigate = useNavigate();

  useEffect(() => {
    document.title = `${title} · ${APP_TITLE}`;
    return () => {
      document.title = APP_TITLE;
    };
  }, [title]);

  return (
    <div style={{ marginBottom: 12 }}>
      <Flex align="center" justify="space-between" gap={12} wrap>
        <Flex align="center" gap={8} wrap style={{ minWidth: 0 }}>
          {backTo !== undefined && (
            <Button type="text" icon={<ArrowLeftOutlined />} aria-label="Geri" onClick={() => navigate(backTo)} />
          )}
          <Typography.Title level={4} style={{ margin: 0 }}>
            {title}
          </Typography.Title>
          {subtitle !== undefined && <Typography.Text type="secondary">{subtitle}</Typography.Text>}
          {tags}
        </Flex>
        {extra !== undefined && (
          <Flex align="center" gap={8} wrap>
            {extra}
          </Flex>
        )}
      </Flex>
      {children !== undefined && <div style={{ marginTop: 8 }}>{children}</div>}
    </div>
  );
}
