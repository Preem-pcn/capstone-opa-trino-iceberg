import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const backend = process.env.QAR_BACKEND_URL ?? 'http://localhost:8766';
const paths = ['/api', '/login', '/callback', '/logout', '/metabase'];
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: Object.fromEntries(paths.map(p => [p, { target: backend, changeOrigin: true }])) },
});
