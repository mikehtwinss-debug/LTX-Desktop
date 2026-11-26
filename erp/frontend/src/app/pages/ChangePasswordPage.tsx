import { useMutation } from '@tanstack/react-query';
import { Alert, App, Button, Card, Flex, Form, Input, theme, Typography } from 'antd';
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';

import { ApiError, apiPost } from '@/lib/api';
import { applyApiErrorsToForm } from '@/lib/forms';

import { useAuth, useMe } from '../AuthProvider';
import { PATHS } from '../paths';

interface PasswordForm {
  current_password: string;
  new_password: string;
  confirm_password: string;
}

export function ChangePasswordPage(): ReactNode {
  const me = useMe();
  const { logout, reloadMe } = useAuth();
  const { message } = App.useApp();
  const { token } = theme.useToken();
  const navigate = useNavigate();
  const [form] = Form.useForm<PasswordForm>();

  const change = useMutation({
    mutationFn: (values: PasswordForm) =>
      apiPost<void>('/auth/change-password', {
        current_password: values.current_password,
        new_password: values.new_password,
      }),
    onSuccess: async () => {
      void message.success('Şifreniz değiştirildi');
      await reloadMe();
      navigate(PATHS.home, { replace: true });
    },
    onError: (error) => {
      applyApiErrorsToForm(form, error);
      if (error instanceof ApiError && error.code === 'INVALID_CREDENTIALS') {
        form.setFields([{ name: 'current_password', errors: [error.message] }]);
      }
    },
  });

  return (
    <Flex align="center" justify="center" style={{ minHeight: '100vh', padding: 16, background: token.colorBgLayout }}>
      <Card style={{ width: 400 }}>
        <Typography.Title level={4} style={{ marginTop: 0 }}>
          Şifre değiştir
        </Typography.Title>
        {me.must_change_password && (
          <Alert
            type="info"
            showIcon
            message="Devam edebilmek için şifrenizi değiştirmeniz gerekiyor."
            style={{ marginBottom: 16 }}
          />
        )}
        <Form<PasswordForm> form={form} layout="vertical" requiredMark={false} onFinish={(values) => change.mutate(values)}>
          <Form.Item
            name="current_password"
            label="Mevcut şifre"
            rules={[{ required: true, message: 'Mevcut şifrenizi girin' }]}
          >
            <Input.Password autoFocus autoComplete="current-password" />
          </Form.Item>
          <Form.Item
            name="new_password"
            label="Yeni şifre"
            dependencies={['current_password']}
            rules={[
              { required: true, message: 'Yeni şifrenizi girin' },
              ({ getFieldValue }) => ({
                validator: (_, value: string | undefined) =>
                  value && value === getFieldValue('current_password')
                    ? Promise.reject(new Error('Yeni şifre mevcut şifreden farklı olmalı'))
                    : Promise.resolve(),
              }),
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="confirm_password"
            label="Yeni şifre (tekrar)"
            dependencies={['new_password']}
            rules={[
              { required: true, message: 'Yeni şifrenizi tekrar girin' },
              ({ getFieldValue }) => ({
                validator: (_, value: string | undefined) =>
                  !value || value === getFieldValue('new_password')
                    ? Promise.resolve()
                    : Promise.reject(new Error('Şifreler birbiriyle aynı değil')),
              }),
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Flex gap={8} justify="flex-end">
            {me.must_change_password ? (
              <Button onClick={logout}>Çıkış yap</Button>
            ) : (
              <Button onClick={() => navigate(-1)}>Vazgeç</Button>
            )}
            <Button type="primary" htmlType="submit" loading={change.isPending}>
              Şifreyi değiştir
            </Button>
          </Flex>
        </Form>
      </Card>
    </Flex>
  );
}
