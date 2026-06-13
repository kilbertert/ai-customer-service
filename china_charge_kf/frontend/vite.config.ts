import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
//
// 后端端口由 VITE_BACKEND_PORT 控制（与 .env 同步）:
//   8011 = Coze 后端  (backend/app/main.py)
//   8012 = Dify 后端  (backend/app_dify/main.py)
// 默认 8011 兼容原 Coze 项目；切到 Dify 时在 frontend/.env 写 VITE_BACKEND_PORT=8012 即可。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendPort = env.VITE_BACKEND_PORT || '8011'

  return {
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      cors: true,
      allowedHosts: true,
      proxy: {
        '/api': {
          target: `http://127.0.0.1:${backendPort}`,
          changeOrigin: true,
          secure: false,
        },
      },
    },
    test: {
      environment: 'happy-dom',
      globals: false,
      include: ['src/**/__tests__/**/*.test.ts'],
    },
  }
})
