import type { Page } from '@playwright/test';
import { expect } from '@playwright/test';
import { BasePage } from './BasePage';
import { LoginPageObjects } from '../pageObjects/LoginPage.objects';

export class LoginPage extends BasePage {
  constructor(page: Page) {
    super(page);
  }

  async clickLoginButton(): Promise<void> {
    await this.healAwareClick(this.getLocator(LoginPageObjects.loginButton), 'Login button').catch(async () => {
      await this.smartClickByTextOrHref('Login button');
    });
  }

  async verifyDashboard(): Promise<void> {
    await this.healAwareVerifyVisible(this.getLocator(LoginPageObjects.dashboard), 'Dashboard').catch(async () => {
      await this.smartVerifyTextOrAction('Dashboard');
    });
  }

}
