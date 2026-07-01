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
const TASK_TEXT = `Update firmware: ${PRINTER_NAME}`;

async function reloadUntil(page: Page, predicate: () => Promise<boolean>, tries = 8): Promise<void> {
  for (let i = 0; i < tries; i++) {
    await openPanel(page);
    if (await predicate()) return;
    await page.waitForTimeout(1500);
  }
}

/** Dismiss the first-run "Welcome to Home Keeper" banner so the card is the focus. */
async function dismissWelcome(page: Page): Promise<void> {
  const gotIt = page.getByRole('button', { name: /got it/i });
  if (await gotIt.count()) {
    await gotIt.first().click();
    await page.waitForTimeout(400);
  }
}

test('capture the firmware glue flow', async ({ page, request }) => {
  const panel = page.locator('home-keeper-panel').first();
  const card = panel.locator('ha-card.hk-card', { hasText: PRINTER_NAME }).first();

  // 1. Firmware update available → a due task appears, "Managed by Bambu Lab".
  await setFirmwareAvailable(request, true);
  await reloadUntil(page, async () => (await card.count()) > 0);
  await expect(card).toContainText(TASK_TEXT);
  // The "Managed by Bambu Lab" chip carries its text in the label attribute.
  await expect(card.locator('ha-assist-chip.hk-managed')).toHaveAttribute(
    'label',
    /Bambu Lab/,
  );
  await dismissWelcome(page);
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/flow-1-firmware-available.png`, fullPage: true });

  // 2. Firmware installed → the task moves to the collapsed Monitored section. Expand it
  //    so the shot shows the dormant, history-bearing task.
  const monitored = panel.locator('details.hk-group[data-group-key="status:monitored"]');
  await setFirmwareAvailable(request, false);
  await reloadUntil(page, async () => (await monitored.count()) > 0);
  await dismissWelcome(page);
  await monitored.locator('summary').click();
  await expect(monitored.locator('ha-card.hk-card', { hasText: PRINTER_NAME }).first()).toBeVisible();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/flow-2-monitored.png`, fullPage: true });
});
