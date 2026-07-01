/**
 * One-off screenshot capture for PR/README documentation — not part of the e2e suite
 * (filename is not *.spec.ts). Run with:
 *   SHOT_DIR=../../docs/images npx playwright test screenshots.capture.ts \
 *     --config=screenshots.config.ts
 *
 * Captures the real flow: a firmware update surfacing as a Home Keeper task, then the
 * task tucked into the Monitored section after the firmware is installed.
 */
import { test, expect, Page } from '@playwright/test';
import { openPanel, setFirmwareAvailable } from './tests/helpers';

const OUT = process.env.SHOT_DIR || '/tmp/glue-shots';
const PRINTER_NAME = 'X1 Carbon';

async function reloadUntil(page: Page, predicate: () => Promise<boolean>, tries = 8): Promise<void> {
  for (let i = 0; i < tries; i++) {
    await openPanel(page);
    if (await predicate()) return;
    await page.waitForTimeout(1500);
  }
}

test('capture the firmware glue flow', async ({ page, request }) => {
  const panel = page.locator('home-keeper-panel').first();
  const card = panel.locator('ha-card.hk-card', { hasText: PRINTER_NAME }).first();

  // 1. Firmware update available → a due task appears, "Managed by Bambu Lab".
  await setFirmwareAvailable(request, true);
  await reloadUntil(page, async () => (await card.count()) > 0);
  await expect(card.locator('ha-assist-chip.hk-managed')).toContainText('Bambu Lab');
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/flow-1-firmware-available.png`, fullPage: true });

  // 2. Firmware installed → the task moves to the collapsed Monitored section. Expand it
  //    so the shot shows the dormant, history-bearing task.
  const monitored = panel.locator('details.hk-group[data-group-key="status:monitored"]');
  await setFirmwareAvailable(request, false);
  await reloadUntil(page, async () => (await monitored.count()) > 0);
  await monitored.locator('summary').click();
  await expect(monitored.locator('ha-card.hk-card', { hasText: PRINTER_NAME }).first()).toBeVisible();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/flow-2-monitored.png`, fullPage: true });
});
