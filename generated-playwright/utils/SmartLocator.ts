import type { Locator, Page } from '@playwright/test';

export type SmartLocatorCandidate =
  | { strategy: 'testId'; value: string; description?: string }
  | { strategy: 'role'; role: Parameters<Page['getByRole']>[0]; value: string; description?: string }
  | { strategy: 'label'; value: string; description?: string }
  | { strategy: 'placeholder'; value: string; description?: string }
  | { strategy: 'text'; value: string; description?: string }
  | { strategy: 'css'; value: string; description?: string }
  | { strategy: 'xpath'; value: string; description?: string };

const VALID_ROLES = new Set<string>([
  'alert','alertdialog','application','article','banner','blockquote','button','caption','cell','checkbox','code',
  'columnheader','combobox','complementary','contentinfo','definition','deletion','dialog','directory','document',
  'emphasis','feed','figure','form','generic','grid','gridcell','group','heading','img','insertion','link','list',
  'listbox','listitem','log','main','marquee','math','meter','menu','menubar','menuitem','menuitemcheckbox',
  'menuitemradio','navigation','none','note','option','paragraph','presentation','progressbar','radio','radiogroup',
  'region','row','rowgroup','rowheader','scrollbar','search','searchbox','separator','slider','spinbutton','status',
  'strong','subscript','superscript','switch','tab','table','tablist','tabpanel','term','textbox','time','timer',
  'toolbar','tooltip','tree','treegrid','treeitem',
]);

export class SmartLocator {
  private readonly candidates: SmartLocatorCandidate[];
  private readonly description: string;

  constructor(
    private readonly page: Page,
    candidates: SmartLocatorCandidate[],
    description = 'smart locator target',
  ) {
    this.candidates = dedupeCandidates(candidates.map(normalizeCandidate).filter(isValidCandidate));
    this.description = normalizeLocatorText(description) || 'smart locator target';
    if (!this.candidates.length) {
      throw new Error(`SmartLocator requires at least one valid candidate for ${this.description}. Role and accessible name cannot be undefined.`);
    }
  }

  static fromCandidates(page: Page, candidates: SmartLocatorCandidate[], description?: string): SmartLocator {
    return new SmartLocator(page, candidates, description ?? candidates[0]?.description ?? 'smart locator target');
  }

  locator(): Locator {
    let resolved = this.resolve(this.candidates[0]);
    for (const candidate of this.candidates.slice(1)) resolved = resolved.or(this.resolve(candidate));
    return resolved.first();
  }

  async firstReachable(timeout = 10_000): Promise<Locator> {
    const deadline = Date.now() + timeout;
    let lastError = '';
    const diagnostics: Array<Record<string, unknown>> = [];
    await this.dismissCommonOverlays().catch(() => undefined);
    await this.waitForStableDom().catch(() => undefined);

    for (const candidate of this.candidates) {
      const resolved = this.resolve(candidate);
      const remaining = Math.max(500, deadline - Date.now());
      try {
        const count = await resolved.count().catch(() => -1);
        const first = resolved.first();
        const visible = count > 0 && await first.isVisible({ timeout: Math.min(1800, remaining) }).catch(() => false);
        diagnostics.push({
          strategy: candidate.strategy,
          role: candidate.strategy === 'role' ? candidate.role : undefined,
          value: candidate.value,
          count,
          visible,
          accepted: count === 1 && visible,
        });
        // Never silently select the first of several matches. A locator used to
        // generate automation must uniquely identify one live element.
        if (count === 1 && visible) {
          await first.scrollIntoViewIfNeeded().catch(() => undefined);
          return first;
        }
      } catch (err) {
        lastError = String(err);
        diagnostics.push({ strategy: candidate.strategy, value: candidate.value, error: lastError });
      }
    }

    await this.page.mouse.wheel(0, Math.floor((await this.page.viewportSize())?.height ?? 800) * 0.8).catch(() => undefined);
    await this.waitForStableDom().catch(() => undefined);
    for (const candidate of this.candidates) {
      const resolved = this.resolve(candidate);
      const count = await resolved.count().catch(() => -1);
      const first = resolved.first();
      const visible = count > 0 && await first.isVisible({ timeout: 1200 }).catch(() => false);
      if (count === 1 && visible) {
        await first.scrollIntoViewIfNeeded().catch(() => undefined);
        return first;
      }
    }

    const visibleControls = await this.visibleControlSummary().catch(() => []);
    throw new Error(
      `SmartLocator failed for ${this.description}. ` +
      `URL: ${this.page.url()}. ` +
      `Normalized candidates: ${JSON.stringify(this.candidates)}. ` +
      `Diagnostics: ${JSON.stringify(diagnostics)}. ` +
      `Visible controls: ${JSON.stringify(visibleControls)}. ` +
      `Last error: ${lastError || 'none'}`,
    );
  }

  async click(timeout = 10_000): Promise<void> {
    const target = await this.firstReachable(timeout);
    await target.click({ timeout }).catch(async firstError => {
      await this.dismissCommonOverlays().catch(() => undefined);
      await this.waitForStableDom().catch(() => undefined);
      await target.scrollIntoViewIfNeeded().catch(() => undefined);
      await target.click({ timeout }).catch(() => { throw firstError; });
    });
    await this.waitForStableDom().catch(() => undefined);
  }

  async fill(value: string, timeout = 10_000): Promise<void> {
    const target = await this.firstReachable(timeout);
    await target.fill(value, { timeout }).catch(async firstError => {
      await this.waitForStableDom().catch(() => undefined);
      await target.fill(value, { timeout }).catch(() => { throw firstError; });
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
        const clean = normalizeLocatorText(candidate.value);
        const rx = relaxedRegex(clean);
        let loc = this.page.getByRole(candidate.role, { name: rx });
        if (candidate.role === 'button') {
          const cssValue = cssAttributeValue(clean);
          loc = loc
            .or(this.page.getByRole('link', { name: rx }))
            .or(this.page.locator(`input[type="submit"][value*="${cssValue}" i], input[type="button"][value*="${cssValue}" i], button[title*="${cssValue}" i], [role="button"][aria-label*="${cssValue}" i]`));
          if (isLoginControl(clean)) loc = loc.or(this.page.locator(loginControlSelector()));
        }
        if (candidate.role === 'link') loc = loc.or(this.page.getByRole('button', { name: rx }));
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

  private async visibleControlSummary(): Promise<Array<Record<string, string>>> {
    return await this.page.locator('button,a,input,select,textarea,[role]').evaluateAll(nodes => nodes
      .filter(node => {
        const el = node as HTMLElement;
        const style = getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 1 && rect.height > 1;
      })
      .slice(0, 30)
      .map(node => {
        const el = node as HTMLInputElement;
        const type = (el.getAttribute('type') || '').toLowerCase();
        const controlValue = ['button','submit','reset','image'].includes(type) ? (el.getAttribute('value') || '') : '';
        return {
          tag: el.tagName.toLowerCase(),
          role: el.getAttribute('role') || '',
          name: el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder') || controlValue || el.innerText || '',
          id: el.id || '',
          controlName: el.getAttribute('name') || '',
          type,
        };
      }));
  }
}

function normalizeCandidate(candidate: SmartLocatorCandidate): SmartLocatorCandidate {
  const value = candidate.strategy === 'css' || candidate.strategy === 'xpath'
    ? String(candidate.value || '').trim()
    : normalizeLocatorText(candidate.value);
  return { ...candidate, value } as SmartLocatorCandidate;
}

function isValidCandidate(candidate: SmartLocatorCandidate): boolean {
  if (!candidate.value || ['undefined', 'null', 'none'].includes(candidate.value.trim().toLowerCase())) return false;
  if (candidate.strategy === 'role') return VALID_ROLES.has(String(candidate.role || '').toLowerCase());
  return true;
}

function normalizeLocatorText(value: string): string {
  let clean = String(value || '')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/[‹〈]/g, '<')
    .replace(/[›〉]/g, '>')
    .replace(/[“”]/g, '"')
    .replace(/[‘’]/g, "'")
    .trim();
  const wrapped = clean.match(/^<\s*([^<>]+?)\s*>$/);
  if (wrapped) clean = wrapped[1];
  clean = clean.replace(/[<>]/g, ' ').replace(/\s+/g, ' ').trim();
  clean = clean.replace(/\b(button|link|cta)\b\s*$/i, '').trim();
  if (/^log\s*in\s+to\s+sandbox$/i.test(clean)) return 'Log In to Sandbox';
  if (/^login\s+to\s+sandbox$/i.test(clean)) return 'Log In to Sandbox';
  return clean;
}

function relaxedRegex(value: string): RegExp {
  const clean = normalizeLocatorText(value);
  if (isLoginControl(clean)) return /(?:log\s*in(?:\s+to\s+sandbox)?|login(?:\s+to\s+sandbox)?|sign\s*in|continue)/i;
  const words = clean.split(/\s+/).filter(Boolean);
  const pattern = words.map(word => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+');
  return new RegExp(pattern || '.*', 'i');
}

function isLoginControl(value: string): boolean {
  return /^(?:log\s*in(?:\s+to\s+sandbox)?|login(?:\s+to\s+sandbox)?|sign\s*in|continue)$/i.test(normalizeLocatorText(value));
}

function loginControlSelector(): string {
  return '#Login, input[name="Login"], button[name="Login"], input[type="submit"][value*="log in" i], input[type="button"][value*="log in" i], button[type="submit"]';
}

function cssAttributeValue(value: string): string {
  return normalizeLocatorText(value).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
}

function dedupeCandidates(candidates: SmartLocatorCandidate[]): SmartLocatorCandidate[] {
  const seen = new Set<string>();
  return candidates.filter(candidate => {
    const key = JSON.stringify([candidate.strategy, candidate.strategy === 'role' ? candidate.role : '', candidate.value]);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
