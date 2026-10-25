import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import { mockBackend } from './mock/backend';

// `npm run dev` proxies to the real backend (backend/, default http://localhost:8766, or
// QAR_BACKEND_URL), so sign-in goes through Google. `npm run dev:mock` (mode "mock") uses the
// mock backend instead, for working without the Docker stack.
const BACKEND_PATHS = ['/api', '/login', '/callback', '/logout', '/metabase'];

export default defineConfig(({ mode }) => {
  const mock = mode === 'mock';
  const backend = process.env.QAR_BACKEND_URL ?? 'http://localhost:8766';
  return {
    plugins: [react(), ...(mock ? [mockBackend()] : [])],
    server: {
      port: 5173,
      // changeOrigin: the backend only answers requests addressed to its own host.
      proxy: mock ? undefined : Object.fromEntries(BACKEND_PATHS.map(p => [p, { target: backend, changeOrigin: true }])),
    },
  };
});
