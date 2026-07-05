import type { Page } from '@playwright/test';

export function attachDialogHandler(page: Page): void {
  page.on('dialog', async dialog => {
    console.log(`[DIALOG_DETECTED] ${dialog.type()} - ${dialog.message()}`);
    try {
      if (dialog.type() === 'confirm') {
        await dialog.accept();
      } else {
        await dialog.dismiss();
      }
    } catch (error) {
      console.warn(`[DIALOG_HANDLER_FAILED] ${String(error)}`);
    }
  });
}
