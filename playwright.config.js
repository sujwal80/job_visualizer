import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests_e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1, // Run sequentially to avoid rate limiting issues in tests
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:5011',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  // Spin up wrangler dev server before running E2E tests
  webServer: {
    command: 'npx wrangler dev --port 5011',
    url: 'http://127.0.0.1:5011/api/companies?limit=1',
    reuseExistingServer: !process.env.CI,
    timeout: 120000,
  },
});
