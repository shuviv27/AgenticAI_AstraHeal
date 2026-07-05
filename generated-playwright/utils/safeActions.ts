import { expect, type Locator, type Page } from '@playwright/test';
import { closeUnexpectedPopups } from './popupHandler';

export type SafeActionOptions = {
  timeout?: number;
  allowForce?: boolean;
};

export async function diagnoseDisabledElement(locator: Locator) {
  return await locator.evaluate(el => ({
    tag: el.tagName,
    text: el.textContent?.trim(),
    disabled: (el as HTMLButtonElement).disabled,
    ariaDisabled: el.getAttribute('aria-disabled'),
    className: el.getAttribute('class'),
    title: el.getAttribute('title'),
    dataState: el.getAttribute('data-state'),
  })).catch(() => null);
}

export async function safeClick(page: Page, locator: Locator, actionName: string, options?: SafeActionOptions): Promise<void> {
  const timeout = options?.timeout ?? 15_000;
  await closeUnexpectedPopups(page);
  await expect(locator, `${actionName}: element attached`).toBeAttached({ timeout });
  await expect(locator, `${actionName}: element visible`).toBeVisible({ timeout });

  const enabled = await locator.isEnabled({ timeout }).catch(() => false);
  if (!enabled) {
    const metadata = await diagnoseDisabledElement(locator);
    throw new Error(`[RCA:ELEMENT_DISABLED] ${actionName} failed because element is disabled. Metadata=${JSON.stringify(metadata)}`);
  }

  try {
    await locator.scrollIntoViewIfNeeded();
    await locator.click({ timeout });
  } catch (error) {
    await closeUnexpectedPopups(page);
    if (options?.allowForce === true) {
      console.warn(`[SELF_HEALING:FORCE_CLICK_DIAGNOSTIC] ${actionName}`);
      await locator.click({ force: true, timeout });
      return;
    }
    throw new Error(`[RCA:ELEMENT_NOT_INTERACTABLE] ${actionName} failed. Original=${String(error)}`);
  }
}

export async function safeFill(page: Page, locator: Locator, value: string, actionName: string, timeout = 15_000): Promise<void> {
  await closeUnexpectedPopups(page);
  await expect(locator, `${actionName}: input visible`).toBeVisible({ timeout });
  await expect(locator, `${actionName}: input editable`).toBeEditable({ timeout });
  await locator.fill(value, { timeout });
}
