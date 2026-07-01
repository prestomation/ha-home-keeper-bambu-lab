import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for the glue's end-to-end tests.
 *
 * Drives a real Chromium against a Home Assistant container running the real Home
 * Keeper + a fake Bambu Lab + this glue (see tests/docker). global-setup completes HA
 * onboarding and writes an authenticated storage state + token so specs start logged in
 * and can drive the Bambu Lab firmware entity over the REST service API.
 *
 * CHROMIUM_EXEC lets a sandboxed/remote environment (where `playwright install` is
 * blocked) point at a pre-installed Chromium — set it to the absolute path of a
 * chrome binary under, e.g., /opt/pw-browsers.
 */
const HA_URL = process.env.HA_URL || 'http://localhost:8123';
const CHROMIUM_EXEC = process.env.CHROMIUM_EXEC;

export default defineConfig({
  testDir: './tests',
  globalSetup: require.resolve('./global-setup'),
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: HA_URL,
    storageState: './.auth/state.json',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        ...(CHROMIUM_EXEC ? { launchOptions: { executablePath: CHROMIUM_EXEC } } : {}),
      },
    },
  ],
});
