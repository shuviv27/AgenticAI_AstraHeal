import type { Locator, Page } from '@playwright/test';
import { SmartLocator, type SmartLocatorCandidate } from './SmartLocator';

export type LocatorDefinition =
  | { strategy: 'testId'; value: string; description?: string; fallbacks?: LocatorDefinition[] }
  | { strategy: 'role'; role: Parameters<Page['getByRole']>[0]; value: string; description?: string; fallbacks?: LocatorDefinition[] }
  | { strategy: 'label'; value: string; description?: string; fallbacks?: LocatorDefinition[] }
  | { strategy: 'text'; value: string; description?: string; fallbacks?: LocatorDefinition[] }
  | { strategy: 'css'; value: string; description?: string; fallbacks?: LocatorDefinition[] }
  | { strategy: 'xpath'; value: string; description?: string; fallbacks?: LocatorDefinition[] };

export function resolveSmartLocator(page: Page, locator: LocatorDefinition): SmartLocator {
  const candidates: SmartLocatorCandidate[] = [locatorToCandidate(locator), ...((locator.fallbacks ?? []).map(locatorToCandidate))];
  return SmartLocator.fromCandidates(page, candidates, locator.description ?? locator.value);
}

function locatorToCandidate(locator: LocatorDefinition): SmartLocatorCandidate {
  switch (locator.strategy) {
    case 'testId':
      return { strategy: 'testId', value: locator.value, description: locator.description };
    case 'role':
      return { strategy: 'role', role: locator.role, value: locator.value, description: locator.description };
    case 'label':
      return { strategy: 'label', value: locator.value, description: locator.description };
    case 'text':
      return { strategy: 'text', value: locator.value, description: locator.description };
    case 'css':
      return { strategy: 'css', value: locator.value, description: locator.description };
    case 'xpath':
      return { strategy: 'xpath', value: locator.value, description: locator.description };
  }
}

export function resolveLocator(page: Page, locator: LocatorDefinition): Locator {
  return resolveSmartLocator(page, locator).locator();
}

function resolveLocatorBase(page: Page, locator: LocatorDefinition): Locator {
  switch (locator.strategy) {
    case 'testId':
      return page.getByTestId(locator.value);
    case 'role': {
      const rx = relaxedRegex(locator.value);
      let loc = page.getByRole(locator.role, { name: rx });
      // Dynamic marketing sites often implement visual buttons as links, spans, or non-standard components.
      // Keep role as the first choice, but add safe fallbacks so simple visible text does not fail unnecessarily.
      if (locator.role === 'button') {
        loc = loc.or(page.getByRole('link', { name: rx })).or(page.getByText(rx));
      } else if (locator.role === 'link') {
        loc = loc.or(page.getByRole('button', { name: rx })).or(page.getByText(rx));
      } else if (locator.role === 'heading') {
        loc = loc.or(page.getByText(rx));
      }
      return loc;
    }
    case 'label':
      return page.getByLabel(relaxedRegex(locator.value)).or(page.getByPlaceholder(relaxedRegex(locator.value)));
    case 'text':
      return page.getByText(relaxedRegex(locator.value));
    case 'css':
      return page.locator(locator.value);
    case 'xpath':
      return page.locator(`xpath=${locator.value}`);
    default:
      throw new Error(`Unsupported locator strategy: ${(locator as LocatorDefinition).strategy}`);
  }
}

function relaxedRegex(value: string): RegExp {
  const clean = String(value || '')
    .replace(/[\u2010-\u2015]/g, '-')
    .replace(/\s+/g, ' ')
    .replace(/\b(button|link|cta)\b/gi, '')
    .trim();
  const escaped = escapeRegExp(clean).replace(/\s+/g, '\\s+');
  return new RegExp(escaped, 'i');
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
