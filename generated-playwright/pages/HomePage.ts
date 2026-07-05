import type { Page } from '@playwright/test';
import { expect } from '@playwright/test';
import { BasePage } from './BasePage';
import { HomePageObjects } from '../pageObjects/HomePage.objects';

export class HomePage extends BasePage {
  constructor(page: Page) {
    super(page);
  }

  async fillEmail(value: string): Promise<void> {
    await this.getLocator(HomePageObjects.emailInput).fill(value);
  }

}
