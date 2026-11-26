import { Button, Result } from 'antd';
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';

import { PATHS } from '../paths';

export function ForbiddenPage(): ReactNode {
  const navigate = useNavigate();
  return (
    <Result
      status="403"
      title="Erişim yetkiniz yok"
      subTitle="Bu sayfayı görüntülemek için gerekli yetkiye sahip değilsiniz. Yetki talebi için sistem yöneticinize başvurun."
      extra={
        <Button type="primary" onClick={() => navigate(PATHS.home)}>
          Ana sayfaya dön
        </Button>
      }
    />
  );
}
