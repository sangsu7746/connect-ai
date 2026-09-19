import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5175,
    proxy: {
      // 로컬 개발용: /api 요청을 server/(Express 프록시)로 전달
      '/api': 'http://localhost:8789',
    },
  },
});
