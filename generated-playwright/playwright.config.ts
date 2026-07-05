import { defineConfig, devices } from '@playwright/test';

const MAX_WAIT_MS = Math.min(Number(process.env.ASTRAHEAL_MAX_EXPLICIT_WAIT_MS || process.env.ASTRAHEAL_MAX_TEST_TIMEOUT_MS || '30000'), 30_000);
const EXPECT_WAIT_MS = Math.min(15_000, MAX_WAIT_MS);
const ACTION_WAIT_MS = Math.min(20_000, MAX_WAIT_MS);

export default defineConfig({
  testDir: './tests',
  fullyParallel: process.env.PW_FULLY_PARALLEL === 'true',
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: Number(process.env.PW_WORKERS || (process.env.CI ? '2' : '1')),
  timeout: MAX_WAIT_MS,
  expect: { timeout: EXPECT_WAIT_MS },
  reporter: [
    ['html', { open: 'never', outputFolder: 'reports/html' }],
    ['json', { outputFile: 'reports/results.json' }]
  ],
  use: {
    headless: false,
    baseURL: process.env.BASE_URL || process.env.TEST_BASE_URL,
    testIdAttribute: process.env.PLAYWRIGHT_TEST_ID_ATTRIBUTE ?? 'data-test',
    viewport: { width: 1920, height: 1080 },
    ignoreHTTPSErrors: true,
    locale: 'en-US',
    geolocation: { latitude: 40.7128, longitude: -74.0060 },
    permissions: ['geolocation', 'notifications'],
    actionTimeout: ACTION_WAIT_MS,
    navigationTimeout: MAX_WAIT_MS,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    launchOptions: {
      args: [
        '--use-fake-ui-for-media-stream',
        '--use-fake-device-for-media-stream',
        '--disable-notifications',
      ]
    }
  },
  projects: [
    { name: 'chromium', use: {
    headless: false, ...devices['Desktop Chrome'] } }
  ],
  outputDir: 'test-results'
});
