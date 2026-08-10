import { APIRequestContext, Page, expect } from '@playwright/test';
import { readFileSync } from 'fs';
import { resolve } from 'path';

/** Route for the Home Keeper sidebar panel (registered by the home_keeper integration). */
export const PANEL_URL = '/home-keeper';

const HA_URL = process.env.HA_URL || 'http://localhost:8123';

/** The access token global-setup persisted, for REST calls from specs. */
export function authToken(): string {
  return readFileSync(resolve(__dirname, '..', '.auth', 'token'), 'utf8').trim();
}

/**
 * Toggle whether the (fake) Bambu Lab printer has a firmware update available, over the
 * REST service API. The fake integration's `bambu_lab.set_firmware_available` service
 * flips its `update` entity between on/off — the same state transition the real firmware
 * entity makes — which is how the e2e drives the glue.
 */
export async function setFirmwareAvailable(
  request: APIRequestContext,
  available: boolean,
): Promise<void> {
  const r = await request.post(`${HA_URL}/api/services/bambu_lab/set_firmware_available`, {
    headers: { Authorization: `Bearer ${authToken()}` },
    data: { available },
  });
  expect(r.ok(), `set_firmware_available(${available}) failed: ${r.status()}`).toBeTruthy();
}

/**
 * Wind the fake printer's cumulative usage-hours counter forward.
 *
 * The maintenance catalog meters against `total_usage_hours`, so this is how the e2e
 * tiers make a usage task cross its target without waiting for real print time.
 */
export async function advanceUsageHours(
  request: APIRequestContext,
  hours: number,
): Promise<void> {
  const r = await request.post(`${HA_URL}/api/services/bambu_lab/advance_usage_hours`, {
    headers: { Authorization: `Bearer ${authToken()}` },
    data: { hours },
  });
  expect(r.ok(), `advance_usage_hours(${hours}) failed: ${r.status()}`).toBeTruthy();
}

/**
 * Open this integration's options dialog and land on its first step.
 *
 * The maintenance catalog is configured per printer, so the options flow is the surface
 * where the model detection becomes the user's decision — worth driving in a real
 * browser rather than only through the flow API. HA renders the integration page deep
 * inside nested shadow roots; Playwright's selectors pierce them, so matching the
 * "Configure" button by role is enough.
 */
export async function openOptionsFlow(page: Page): Promise<void> {
  await page.goto('/config/integrations/integration/home_keeper_bambu_lab', {
    waitUntil: 'domcontentloaded',
  });
  const configure = page.getByRole('button', { name: /^configure$/i }).first();
  await configure.waitFor({ state: 'visible', timeout: 45_000 });
  await configure.click();
  // Wait on the step's own Submit button rather than the dialog element: HA's
  // `ha-dialog` host box measures zero, so Playwright calls it hidden even while its
  // content is on screen.
  await page
    .getByRole('button', { name: /^submit$/i })
    .first()
    .waitFor({ state: 'visible', timeout: 20_000 });
}

/** Submit the options-flow step currently on screen. */
export async function submitFlowStep(page: Page): Promise<void> {
  await page.getByRole('button', { name: /^submit$/i }).first().click();
  await page.waitForTimeout(1200);
}

/** Navigate to the Home Keeper panel and wait for the custom element to upgrade. */
export async function openPanel(page: Page): Promise<void> {
  await page.goto(PANEL_URL, { waitUntil: 'domcontentloaded' });
  await page.locator('home-keeper-panel').first().waitFor({ state: 'attached', timeout: 45_000 });
  await expect(page.locator('home-keeper-panel').first()).toBeVisible();
}

/** Collect panel-relevant console/page errors. Attach BEFORE navigating. */
export function trackPanelErrors(page: Page): string[] {
  const errors: string[] = [];
  const isRelated = (s: string) => /home.?keeper|bambu/i.test(s);
  page.on('pageerror', (e) => {
    const text = `${e.message}\n${e.stack || ''}`;
    if (isRelated(text)) errors.push(`pageerror: ${text}`);
  });
  page.on('console', (msg) => {
    if (msg.type() === 'error' && isRelated(msg.text())) {
      errors.push(`console.error: ${msg.text()}`);
    }
  });
  return errors;
}
