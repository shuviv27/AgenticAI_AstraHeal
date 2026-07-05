import type { Page } from '@playwright/test';

export const popupCloseLocators = [
  '[aria-label="Close"]',
  '[data-testid="close"]',
  '[data-testid="modal-close"]',
  'button:has-text("Close")',
  'button:has-text("No thanks")',
  'button:has-text("Maybe later")',
  'button:has-text("Not now")',
  'button:has-text("Accept all")',
  'button:has-text("I agree")',
  'button:has-text("Got it")',
  '#onetrust-accept-btn-handler',
  '.modal-close',
  '.popup-close',
  '.close-button',
];

export async function closeUnexpectedPopups(page: Page, timeoutPerLocator = 800): Promise<string[]> {
  const closed: string[] = [];
  for (const selector of popupCloseLocators) {
    const closeButton = page.locator(selector).first();
    try {
      if (await closeButton.isVisible({ timeout: timeoutPerLocator })) {
        await closeButton.click({ timeout: 2000 });
        closed.push(selector);
        console.log(`[SELF_HEALING:POPUP_CLOSED] ${selector}`);
      }
    } catch {
      // Continue checking other popup patterns. Popup handling must never hide the original failure.
    }
  }
  return closed;
}
