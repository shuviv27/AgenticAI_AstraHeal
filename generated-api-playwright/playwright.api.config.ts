import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ['html', { outputFolder: 'reports/html', open: 'never' }],
    ['json', { outputFile: 'reports/api-results.json' }],
    ['junit', { outputFile: 'reports/api-results.xml' }]
  ],
  use: {
    baseURL: process.env.API_BASE_URL,
    extraHTTPHeaders: process.env.API_AUTH_TOKEN ? { Authorization: `Bearer ${process.env.API_AUTH_TOKEN}` } : {},
    trace: 'retain-on-failure',
  },
});
