import type { Locator, Page } from '@playwright/test';

export type SmartLocatorCandidate =
  | { strategy: 'testId'; value: string; description?: string }
  | { strategy: 'role'; role: Parameters<Page['getByRole']>[0]; value: string; description?: string }
  | { strategy: 'label'; value: string; description?: string }
  | { strategy: 'placeholder'; value: string; description?: string }
  | { strategy: 'text'; value: string; description?: string }
  | { strategy: 'css'; value: string; description?: string }
  | { strategy: 'xpath'; value: string; description?: string };

export class SmartLocator {
  constructor(
    private readonly page: Page,
    private readonly candidates: SmartLocatorCandidate[],
    private readonly description = 'smart locator target',
  ) {
    if (!candidates.length) throw new Error(`SmartLocator requires at least one candidate for ${description}`);
  }

  static fromCandidates(page: Page, candidates: SmartLocatorCandidate[], description?: string): SmartLocator {
    return new SmartLocator(page, candidates, description ?? candidates[0]?.description ?? 'smart locator target');
  }

  locator(): Locator {
    let resolved = this.resolve(this.candidates[0]);
    for (const candidate of this.candidates.slice(1)) {
      resolved = resolved.or(this.resolve(candidate));
    }
    return resolved.first();
  }

  async firstReachable(timeout = 10_000): Promise<Locator> {
    const deadline = Date.now() + timeout;
    let lastError = '';
    await this.dismissCommonOverlays().catch(() => undefined);
    await this.waitForStableDom().catch(() => undefined);

    for (const candidate of this.candidates) {
      const loc = this.resolve(candidate).first();
      const remaining = Math.max(500, deadline - Date.now());
      try {
        if (await loc.isVisible({ timeout: Math.min(1500, remaining) }).catch(() => false)) {
          await loc.scrollIntoViewIfNeeded().catch(() => undefined);
          return loc;
        }
      } catch (err) {
        lastError = String(err);
      }
    }

    await this.page.mouse.wheel(0, Math.floor((await this.page.viewportSize())?.height ?? 800) * 0.8).catch(() => undefined);
    await this.waitForStableDom().catch(() => undefined);
    for (const candidate of this.candidates.slice(1)) {
      const loc = this.resolve(candidate).first();
      if (await loc.isVisible({ timeout: 1200 }).catch(() => false)) {
        await loc.scrollIntoViewIfNeeded().catch(() => undefined);
        return loc;
      }
    }

    throw new Error(`SmartLocator failed for ${this.description}. Tried candidates: ${JSON.stringify(this.candidates)}. Last error: ${lastError}`);
  }

  async click(timeout = 10_000): Promise<void> {
    const target = await this.firstReachable(timeout);
    await target.click({ timeout }).catch(async firstError => {
      await this.dismissCommonOverlays().catch(() => undefined);
      await this.waitForStableDom().catch(() => undefined);
      await target.scrollIntoViewIfNeeded().catch(() => undefined);
      await target.click({ timeout }).catch(() => {
        throw firstError;
      });
    });
    await this.waitForStableDom().catch(() => undefined);
  }

  async fill(value: string, timeout = 10_000): Promise<void> {
    const target = await this.firstReachable(timeout);
    await target.fill(value, { timeout }).catch(async firstError => {
      await this.waitForStableDom().catch(() => undefined);
      await target.fill(value, { timeout }).catch(() => {
        throw firstError;
      });
    });
  }

  async expectVisible(timeout = 10_000): Promise<Locator> {
    return await this.firstReachable(timeout);
  }

  private resolve(candidate: SmartLocatorCandidate): Locator {
    switch (candidate.strategy) {
      case 'testId':
        return this.page.getByTestId(candidate.value);
      case 'role': {
        const rx = relaxedRegex(candidate.value);
        let loc = this.page.getByRole(candidate.role, { name: rx });
        if (candidate.role === 'button') loc = loc.or(this.page.getByRole('link', { name: rx })).or(this.page.getByText(rx));
        if (candidate.role === 'link') loc = loc.or(this.page.getByRole('button', { name: rx })).or(this.page.getByText(rx));
        return loc;
      }
      case 'label':
        return this.page.getByLabel(relaxedRegex(candidate.value));
      case 'placeholder':
        return this.page.getByPlaceholder(relaxedRegex(candidate.value));
      case 'text':
        return this.page.getByText(relaxedRegex(candidate.value));
      case 'css':
        return this.page.locator(candidate.value);
      case 'xpath':
        return this.page.locator(`xpath=${candidate.value}`);
    }
  }

  private async waitForStableDom(): Promise<void> {
    await this.page.waitForLoadState('domcontentloaded', { timeout: 20_000 }).catch(() => undefined);
    await this.page.locator('body').waitFor({ state: 'visible', timeout: 10_000 }).catch(() => undefined);
    await this.page.evaluate(async () => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))).catch(() => undefined);
  }

  private async dismissCommonOverlays(): Promise<void> {
    const buttons = [/accept all/i, /accept/i, /agree/i, /allow/i, /ok/i, /got it/i, /continue/i, /close/i, /no thanks/i];
    for (const name of buttons) {
      const button = this.page.getByRole('button', { name }).first();
      if (await button.isVisible({ timeout: 500 }).catch(() => false)) {
        await button.click({ timeout: 1000 }).catch(() => undefined);
        break;
      }
    }
  }
}

function relaxedRegex(value: string): RegExp {
  const escaped = String(value || '')
    .replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    .replace(/\s+/g, '\\s+');
  return new RegExp(escaped, 'i');
}
