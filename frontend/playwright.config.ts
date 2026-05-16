import { defineConfig, devices } from '@playwright/test';

/**
 * E2E config for the security-agent web app.
 *
 * By default Playwright brings the whole stack up via the root
 * `docker-compose.yml` (frontend + backend + nginx) and points the tests at
 * the nginx entrypoint. Set `E2E_BASE_URL` to test an already-running
 * deployment, and `E2E_NO_WEBSERVER=1` to skip the compose bring-up.
 */
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  timeout: 120_000,
  expect: { timeout: 20_000 },
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: process.env.E2E_NO_WEBSERVER
    ? undefined
    : {
        command: 'docker compose up --build',
        // Relative to this config file -> the repository root.
        cwd: '..',
        url: BASE_URL,
        reuseExistingServer: true,
        timeout: 360_000,
        stdout: 'pipe',
        stderr: 'pipe',
      },
});
