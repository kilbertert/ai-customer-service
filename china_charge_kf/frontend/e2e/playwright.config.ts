import { defineConfig, devices } from '@playwright/test'

// M7 e2e config — full-stack Playwright validation.
// webServer auto-starts: backend (Dify on :8012) + frontend (Vite on :5173).
// Tests assume the dev stack is otherwise idle; CI should run in a clean env.

const PYTHON_BIN = 'C:/Users/q1234/miniconda3/python'
const BACKEND_PORT = 8012
const FRONTEND_PORT = 5173
const BACKEND_HEALTH = `http://127.0.0.1:${BACKEND_PORT}/health`
const FRONTEND_BASE = `http://127.0.0.1:${FRONTEND_PORT}`

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  outputDir: 'test-results',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  use: {
    baseURL: FRONTEND_BASE,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    locale: 'en-US',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: [
    {
      // Dify backend on :8012 — miniconda python (project has no venv)
      command: `"${PYTHON_BIN}" -m uvicorn app_dify.main:app --app-dir ../backend --host 127.0.0.1 --port ${BACKEND_PORT}`,
      cwd: '..',
      url: BACKEND_HEALTH,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      stdout: 'ignore',
      stderr: 'pipe',
    },
    {
      // Vite dev server on :5173 — proxies /api to backend
      command: 'npm run dev -- --port 5173 --strictPort',
      url: FRONTEND_BASE,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      stdout: 'ignore',
      stderr: 'pipe',
    },
  ],
})
