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
