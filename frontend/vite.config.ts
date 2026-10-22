import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } } },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('/node_modules/@fluentui/')) return 'fluent';
          if (id.includes('/node_modules/react-markdown/')) return 'markdown';
        },
      },
    },
  },
});
