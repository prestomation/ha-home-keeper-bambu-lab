import { test, expect } from '@playwright/test';
import { openOptionsFlow, submitFlowStep } from './helpers';

/**
 * End-to-end for the per-printer maintenance options flow, in a real browser.
 *
 * The flow-API tests in `tests/integration/test_options_flow.py` already pin the step
 * order and the pre-fill rules. What they can't see is whether Home Assistant actually
 * *renders* these steps — a translation key that doesn't exist, or a placeholder the
 * frontend's ICU parser chokes on, fails here and nowhere else (which is exactly how
 * `tests/unit/test_strings.py` came to exist).
 */
test('the options flow renders the model step and lists every catalog item', async ({
  page,
}) => {
  await openOptionsFlow(page);

  // Step 1: the firmware name template + the maintenance master switch. The container
  // is seeded with maintenance already on, so submitting unchanged goes forward.
  await expect(page.getByText(/task name template/i).first()).toBeVisible();
  await submitFlowStep(page);

  // Step 2: the model. One printer in the container, so the picker step is skipped —
  // and the description must name what we detected rather than showing a raw
  // `{detected}` placeholder.
  const model = page.getByText(/detected model/i).first();
  await expect(model).toBeVisible();
  await expect(model).toContainText('X1C');
  await expect(page.getByText(/\{detected\}|\{printer_name\}/)).toHaveCount(0);
  await submitFlowStep(page);

  // Step 3: every item is offered whatever the printer, which is what keeps an
  // unrecognised model configurable by hand.
  for (const label of [
    /clean and oil the linear rods/i,
    /grease the z-axis lead screws/i,
    /activated carbon air filter/i,
    /x-axis carbon rods/i,
    /anti-rust treatment/i,
    /clean the camera lens/i,
    /extruder gear/i,
    /toolhead fans/i,
  ]) {
    await expect(page.getByText(label).first()).toBeVisible();
  }

  // Submitting saves without error and closes the dialog.
  await submitFlowStep(page);
  await expect(page.getByText(/detected model/i)).toHaveCount(0);
});
