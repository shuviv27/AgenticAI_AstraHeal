import { test, expect } from '@playwright/test';

test('framework smoke test without external application', async ({ page }) => {
  await page.setContent(`
    <html>
      <body>
        <label>Username <input aria-label="Username" value="" /></label>
        <label>Password <input aria-label="Password" value="" /></label>
        <button>Login</button>
        <h1>Dashboard</h1>
      </body>
    </html>
  `);
  await expect(page.getByText('Dashboard')).toBeVisible();
});
