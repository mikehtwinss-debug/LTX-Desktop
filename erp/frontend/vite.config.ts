import { fileURLToPath, URL } from 'node:url';

import react from '@vitejs/plugin-react';
import { loadEnv } from 'vite';
import { defineConfig } from 'vitest/config';

const ANTD_PACKAGES = /node_modules[\\/](antd|@ant-design|rc-[^\\/]+|@rc-component)[\\/]/;
const REACT_PACKAGES = /node_modules[\\/](react|react-dom|react-router|react-router-dom|@remix-run|scheduler)[\\/]/;

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const port = Number(env.PORT) || 5173;
  const proxy = {
    '/api': { target: env.VITE_API_PROXY || 'http://127.0.0.1:8000', changeOrigin: true },
  };

  return {
    plugins: [react()],
    resolve: {
      alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
    // An inline PostCSS config stops Vite from picking up the unrelated config at the repository root.
    css: { postcss: { plugins: [] } },
    server: { port, strictPort: true, proxy },
    preview: { port, strictPort: true, proxy },
    build: {
      // The Ant Design chunk is one deliberately large, long-cached file.
      chunkSizeWarningLimit: 1200,
      rolldownOptions: {
        output: {
          // Keep the UI kit and the framework out of the entry chunk so that application releases do
          // not invalidate their browser cache entries. A group also takes the dependencies of its
          // modules, hence the order: React first, then Ant Design (which depends on it), then the rest.
          codeSplitting: {
            groups: [
              { name: 'react', test: REACT_PACKAGES, priority: 30 },
              { name: 'antd', test: ANTD_PACKAGES, priority: 20 },
              { name: 'vendor', test: /node_modules[\\/]/, priority: 10 },
            ],
          },
        },
      },
    },
    test: {
      environment: 'node',
      include: ['src/**/*.test.ts'],
    },
  };
});
