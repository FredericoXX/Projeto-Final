/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// The dev server proxies /api to the backend so the browser makes
// same-origin calls and the backend never needs permissive CORS. The
// target is configurable via DEV_PROXY_TARGET (see .env.example).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const proxyTarget = env.DEV_PROXY_TARGET ?? 'http://127.0.0.1:8000';

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
        },
      },
    },
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      css: false,
      restoreMocks: true,
      // Absolute base URL in tests: jsdom + undici's fetch cannot resolve a
      // relative path, and MSW intercepts absolute requests.
      env: {
        VITE_API_BASE_URL: 'http://localhost/api/v1',
        VITE_APP_NAME: 'Institutional Assistant',
      },
    },
  };
});
