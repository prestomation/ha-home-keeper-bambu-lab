/**
 * One-off screenshot capture for PR/README documentation — not part of the e2e suite
 * (filename is not *.spec.ts). Run with:
 *   SHOT_DIR=../../docs/images npx playwright test screenshots.capture.ts \
 *     --config=screenshots.config.ts
 *
 * Captures the real flow: a firmware update surfacing as a Home Keeper task, then the
 * task tucked into the Monitored section after the firmware is installed, and finally
 * the maintenance catalog's usage task coming due as the printer's hours climb.
 */
import { test, expect, Page } from '@playwright/test';
import {
  advanceUsageHours,
  openOptionsFlow,
  openPanel,
  setFirmwareAvailable,
  submitFlowStep,
} from './tests/helpers';

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
  // Match the firmware task by name — the container also seeds a maintenance task on
  // the same printer, so filtering on the printer name alone is ambiguous.
  const card = panel.locator('ha-card.hk-card', { hasText: TASK_TEXT }).first();

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
  await expect(monitored.locator('ha-card.hk-card', { hasText: TASK_TEXT }).first()).toBeVisible();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/flow-2-monitored.png`, fullPage: true });
});

test('capture the maintenance catalog', async ({ page, request }) => {
  const panel = page.locator('home-keeper-panel').first();

  // The container is seeded with the catalog on and one item enabled (Z-axis lead
  // screws, target 5 h — see tests/docker/ha_config/.storage/core.config_entries), so
  // this shot is about one task with a readable progress bar rather than a wall of them.
  const monitored = panel.locator('details.hk-group[data-group-key="status:monitored"]');
  await reloadUntil(page, async () => (await monitored.count()) > 0);
  await dismissWelcome(page);
  await monitored.locator('summary').click();
  const maintenance = monitored
    .locator('ha-card.hk-card', { hasText: /lead screws/i })
    .first();
  await expect(maintenance).toBeVisible();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/flow-3-maintenance-monitored.png`, fullPage: true });

  // 4. Open its detail page. Advance the meter first so the progress bar has something
  //    to show (Home Keeper stamps the baseline on the first reading it sees after the
  //    task is created, so the first nudge anchors and the second one accumulates).
  await advanceUsageHours(request, 1);
  await page.waitForTimeout(2000);
  await advanceUsageHours(request, 3);
  await page.waitForTimeout(2000);
  await openPanel(page);
  await dismissWelcome(page);
  const group = panel.locator('details.hk-group[data-group-key="status:monitored"]');
  if ((await group.count()) > 0) await group.locator('summary').click();
  await panel.locator('.detail-open', { hasText: /lead screws/i }).first().click();
  await expect(panel.locator('.hk-meter').first()).toBeVisible();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/flow-4-maintenance-detail.png`, fullPage: true });
});

test('capture the per-printer options flow', async ({ page }) => {
  // The argument for the per-model design is visual: every item listed for every
  // printer, with only the ones this model actually has ticked. One printer in the
  // container, so the picker is skipped and we land straight on the model step.
  await openOptionsFlow(page);
  await submitFlowStep(page); // init: keep the name template, maintenance already on
  await expect(page.getByText(/detected model/i).first()).toBeVisible();

  // Pick the X1 series. The container is seeded as an unrecognised printer, so this is
  // the "correct the model" path — which is also why the items step then shows that
  // family's clean defaults instead of the container's saved answers.
  await page.locator('ha-select').first().click();
  await page
    .locator('ha-dropdown-item', { hasText: /X1 series/i })
    .first()
    .click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/flow-5-options-model.png` });

  // The items step is a long scrolling form; a tall viewport gets several items into
  // one shot instead of two-and-a-half.
  await page.setViewportSize({ width: 1280, height: 1500 });
  await submitFlowStep(page);
  await expect(page.getByText(/activated carbon air filter/i).first()).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/flow-6-options-items.png` });
});
