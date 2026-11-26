import { LockOutlined, UserOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Flex, Form, Input, theme, Typography } from 'antd';
import { type ReactNode, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';

import { errorMessage } from '@/lib/api';

import { useAuth } from '../AuthProvider';
import type { LoginRedirectState } from '../guards';
import { PATHS } from '../paths';

interface LoginForm {
  username: string;
  password: string;
}

/** Only in-app paths are accepted as the place to return to after signing in. */
function returnPath(state: unknown): string {
  const from = (state as Partial<LoginRedirectState> | null)?.from;
  const internal = typeof from === 'string' && /^\/(?![/\\])/.test(from) && !from.startsWith(PATHS.login);
  return internal ? from : PATHS.home;
}

export function LoginPage(): ReactNode {
  const { status, login } = useAuth();
  const location = useLocation();
  const { token } = theme.useToken();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (status !== 'anonymous') {
    return <Navigate to={returnPath(location.state)} replace />;
  }

  const handleFinish = async ({ username, password }: LoginForm): Promise<void> => {
    setSubmitting(true);
    setError(null);
    try {
      await login(username.trim(), password);
    } catch (caught) {
      setError(errorMessage(caught));
      setSubmitting(false);
    }
  };

  return (
    <Flex align="center" justify="center" style={{ minHeight: '100vh', padding: 16, background: token.colorBgLayout }}>
      <Card style={{ width: 360 }}>
        <Typography.Title level={3} style={{ marginTop: 0, marginBottom: 4, letterSpacing: 1 }}>
          ERP
        </Typography.Title>
        <Typography.Paragraph type="secondary">Devam etmek için oturum açın.</Typography.Paragraph>
        {error !== null && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
        <Form<LoginForm> layout="vertical" requiredMark={false} onFinish={(values) => void handleFinish(values)}>
          <Form.Item name="username" label="Kullanıcı adı" rules={[{ required: true, message: 'Kullanıcı adınızı girin' }]}>
            <Input autoFocus autoComplete="username" autoCapitalize="none" prefix={<UserOutlined />} />
          </Form.Item>
          <Form.Item name="password" label="Şifre" rules={[{ required: true, message: 'Şifrenizi girin' }]}>
            <Input.Password autoComplete="current-password" prefix={<LockOutlined />} />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={submitting}>
            Giriş yap
          </Button>
        </Form>
      </Card>
    </Flex>
  );
}
