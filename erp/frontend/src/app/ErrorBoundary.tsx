import { Button, Result, Space, Typography } from 'antd';
import type { ReactNode } from 'react';
import { useNavigate, useRouteError } from 'react-router-dom';

import { PATHS } from './paths';

/** A lazily loaded page chunk that is gone, typically because a new version was deployed. */
function isChunkLoadError(error: unknown): boolean {
  return (
    error instanceof Error &&
    /dynamically imported module|importing a module script failed|error loading dynamically/i.test(error.message)
  );
}

/**
 * Error boundary of the router (`errorElement`): catches errors thrown while a page renders or
 * while its code is loaded, and keeps the rest of the application usable.
 */
export function RouteErrorBoundary(): ReactNode {
  const error = useRouteError();
  const navigate = useNavigate();
  const outdated = isChunkLoadError(error);

  return (
    <Result
      status="error"
      title={outdated ? 'Sayfa yüklenemedi' : 'Beklenmeyen bir hata oluştu'}
      subTitle={
        outdated
          ? 'Uygulama güncellenmiş olabilir. Sayfayı yenileyip tekrar deneyin.'
          : 'Sayfa görüntülenirken bir sorun oluştu. Sorun devam ederse sistem yöneticinize aşağıdaki ayrıntıyı iletin.'
      }
      extra={
        <Space>
          <Button type="primary" onClick={() => window.location.reload()}>
            Sayfayı yenile
          </Button>
          <Button onClick={() => navigate(PATHS.home)}>Ana sayfaya dön</Button>
        </Space>
      }
    >
      {!outdated && error instanceof Error && (
        <Typography.Text type="secondary" code>
          {error.name}: {error.message}
        </Typography.Text>
      )}
    </Result>
  );
}
