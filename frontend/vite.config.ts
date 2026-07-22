/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// O servidor de desenvolvimento encaminha /api para o backend, permitindo
// pedidos de mesma origem sem CORS permissivo. O destino é configurável por
// DEV_PROXY_TARGET (consulte .env.example).
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
      // URL-base absoluta nos testes: o fetch do jsdom + undici não resolve
      // caminhos relativos, e o MSW interceta pedidos absolutos.
      env: {
        VITE_API_BASE_URL: 'http://localhost/api/v1',
        VITE_APP_NAME: 'Institutional Assistant',
      },
    },
  };
});
