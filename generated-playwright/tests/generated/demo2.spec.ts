import { test } from '@playwright/test';
import { HomePage } from '../../pages/HomePage';
import { LoginPage } from '../../pages/LoginPage';

test.describe('demo2 generated scenarios', () => {
  test('D2 - Login', async ({ page }) => {
    // Source traceability: D2
    const homePage = new HomePage(page);
    const loginPage = new LoginPage(page);
    await loginPage.goto('https://example.com');
    // Page context switched to HomePage after navigation/action.
    await homePage.fillEmail('a@b.com');
    // Page context switched to LoginPage after navigation/action.
    await loginPage.clickLoginButton();
    await loginPage.verifyDashboard();
  });

});
