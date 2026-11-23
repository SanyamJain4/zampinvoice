import { defineConfig } from '@playwright/test'

// Expects the full stack to be running (backend on :8000 serving the built UI, or `npm run dev` + backend).
// Run:  npx playwright install chromium && npm run test:e2e
export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  retries: 0,
  workers: 1, // the scenarios share one database and depend on order
  use: { baseURL: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:8000', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
})
