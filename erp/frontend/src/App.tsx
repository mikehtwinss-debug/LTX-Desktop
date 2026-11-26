import 'dayjs/locale/tr';

import { QueryClientProvider } from '@tanstack/react-query';
import { App as AntApp, ConfigProvider } from 'antd';
import trTR from 'antd/es/locale/tr_TR';
import dayjs from 'dayjs';
import { type ReactNode, useEffect } from 'react';
import { RouterProvider } from 'react-router-dom';

import { AuthProvider } from './app/AuthProvider';
import { router } from './app/router';
import { appTheme } from './app/theme';
import { bindMessage } from './lib/notify';
import { queryClient } from './lib/queryClient';

dayjs.locale('tr');

/** Hands the themed message API to code that runs outside React (see `lib/notify`). */
function MessageBinder(): null {
  const { message } = AntApp.useApp();
  useEffect(() => bindMessage(message), [message]);
  return null;
}

export function App(): ReactNode {
  return (
    <ConfigProvider locale={trTR} theme={appTheme} input={{ autoComplete: 'off' }}>
      <AntApp>
        <MessageBinder />
        <QueryClientProvider client={queryClient}>
          <AuthProvider>
            <RouterProvider router={router} future={{ v7_startTransition: true }} />
          </AuthProvider>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  );
}
