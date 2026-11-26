import { Button, Result } from 'antd';
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';

import { PATHS } from '../paths';

export function NotFoundPage(): ReactNode {
  const navigate = useNavigate();
  return (
    <Result
      status="404"
      title="Sayfa bulunamadı"
      subTitle="Aradığınız sayfa taşınmış veya kaldırılmış olabilir."
      extra={
        <Button type="primary" onClick={() => navigate(PATHS.home)}>
          Ana sayfaya dön
        </Button>
      }
    />
  );
}
