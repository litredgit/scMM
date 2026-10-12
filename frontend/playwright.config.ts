import { defineConfig } from '@playwright/test'

const port = process.env.SCMM_E2E_PORT ?? '5117'
export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 1440, height: 1000 },
    launchOptions: process.env.SCMM_CHROMIUM ? { executablePath: process.env.SCMM_CHROMIUM } : {},
    trace: 'retain-on-failure',
  },
  webServer: {
    command: `${process.env.SCMM_TEST_PYTHON ?? '../.venv/bin/python'} tests/server.py`,
    url: `http://127.0.0.1:${port}/api/v1/health`,
    reuseExistingServer: false,
    timeout: 60_000,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 5000 },
  },
})
