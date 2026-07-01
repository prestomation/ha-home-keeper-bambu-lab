import { test, expect, Page } from '@playwright/test';
import { openPanel, setFirmwareAvailable, trackPanelErrors } from './helpers';

/**
 * End-to-end: drive the *real* stack. We toggle the Bambu Lab firmware update entity and
 * assert the glue's effect on the *real* Home Keeper panel — a read-only firmware task
 * appearing when an update is available and tucking into the Monitored section when it's
 * installed. This exercises the whole chain: firmware entity state → glue →
 * home_keeper.add_task / complete_task → panel.
 */

const PRINTER_NAME = 'X1 Carbon';
const TASK_TEXT = `Update firmware: ${PRINTER_NAME}`;

/** Reload the panel until *predicate* holds (the glue + HK reload run async). */
async function reloadUntil(page: Page, predicate: () => Promise<boolean>, tries = 8): Promise<void> {
  for (let i = 0; i < tries; i++) {
    await openPanel(page);
    if (await predicate()) return;
    await page.waitForTimeout(1500);
  }
  throw new Error('panel did not reach the expected state in time');
}

test('firmware available → glue creates a read-only due task; installed → Monitored', async ({
  page,
  request,
}) => {
  const errors = trackPanelErrors(page);
  const panel = page.locator('home-keeper-panel').first();
  const activeCard = panel.locator('ha-card.hk-card', { hasText: PRINTER_NAME }).first();

  // 1) Firmware update becomes available → the glue creates an armed (due-now) task.
  await setFirmwareAvailable(request, true);
  await reloadUntil(page, async () => (await activeCard.count()) > 0);

  await expect(activeCard).toContainText(TASK_TEXT);
  // The "Managed by Bambu Lab" chip carries its text in the label attribute.
  await expect(activeCard.locator('ha-assist-chip.hk-managed')).toHaveAttribute('label', /Bambu Lab/);
  // Read-only mirror: completion is blocked, so there's no "Done" button — instead the
  // panel shows a "Clears automatically" caption. It clears only when firmware installs.
  await expect(activeCard.locator('.done-btn')).toHaveCount(0);
  await expect(activeCard.locator('.hk-auto-clear')).toBeVisible();

  // 2) Firmware installed → the task records the change and goes dormant; it leaves the
  //    visible list and lands in the collapsed "Monitored" section.
  const monitored = panel.locator('details.hk-group[data-group-key="status:monitored"]');
  await setFirmwareAvailable(request, false);
  await reloadUntil(page, async () => (await monitored.count()) > 0);

  await expect(monitored).not.toHaveAttribute('open', /.*/);
  await monitored.locator('summary').click();
  const dormantCard = monitored.locator('ha-card.hk-card', { hasText: PRINTER_NAME }).first();
  await expect(dormantCard).toBeVisible();
  await expect(dormantCard).toContainText(TASK_TEXT);
  // Still read-only, and the install was recorded as a completion.
  await expect(dormantCard.locator('.done-btn')).toHaveCount(0);

  expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
});
