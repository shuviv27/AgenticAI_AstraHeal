import type { Locator, Page } from '@playwright/test';
import { SmartLocator, type SmartLocatorCandidate } from './SmartLocator';
// SmartLocator resolves placeholder candidates through page.getByPlaceholder().

export type LocatorDefinition =
  | { strategy: 'testId'; value: string; description?: string; fallbacks?: LocatorDefinition[] }
  | { strategy: 'role'; role: Parameters<Page['getByRole']>[0]; value: string; description?: string; fallbacks?: LocatorDefinition[] }
  | { strategy: 'label'; value: string; description?: string; fallbacks?: LocatorDefinition[] }
  | { strategy: 'placeholder'; value: string; description?: string; fallbacks?: LocatorDefinition[] }
  | { strategy: 'text'; value: string; description?: string; fallbacks?: LocatorDefinition[] }
  | { strategy: 'css'; value: string; description?: string; fallbacks?: LocatorDefinition[] }
  | { strategy: 'xpath'; value: string; description?: string; fallbacks?: LocatorDefinition[] };

export function resolveSmartLocator(page: Page, locator: LocatorDefinition): SmartLocator {
  validateDefinition(locator);
  const candidates: SmartLocatorCandidate[] = [locatorToCandidate(locator), ...((locator.fallbacks ?? []).map(locatorToCandidate))];
  return SmartLocator.fromCandidates(page, candidates, locator.description ?? locator.value);
}

function locatorToCandidate(locator: LocatorDefinition): SmartLocatorCandidate {
  switch (locator.strategy) {
    case 'testId': return { strategy: 'testId', value: locator.value, description: locator.description };
    case 'role': return { strategy: 'role', role: locator.role, value: locator.value, description: locator.description };
    case 'label': return { strategy: 'label', value: locator.value, description: locator.description };
    case 'placeholder': return { strategy: 'placeholder', value: locator.value, description: locator.description };
    case 'text': return { strategy: 'text', value: locator.value, description: locator.description };
    case 'css': return { strategy: 'css', value: locator.value, description: locator.description };
    case 'xpath': return { strategy: 'xpath', value: locator.value, description: locator.description };
  }
}

export function resolveLocator(page: Page, locator: LocatorDefinition): Locator {
  return resolveSmartLocator(page, locator).locator();
}

function validateDefinition(locator: LocatorDefinition): void {
  const value = String(locator.value || '').trim();
  if (!value || ['undefined', 'null', 'none'].includes(value.toLowerCase())) {
    throw new Error(`Invalid locator definition: strategy=${locator.strategy}, value=${JSON.stringify(locator.value)}.`);
  }
  if (locator.strategy === 'role' && !String(locator.role || '').trim()) {
    throw new Error(`Invalid role locator for ${locator.description ?? value}: role is undefined.`);
  }
  for (const fallback of locator.fallbacks ?? []) validateDefinition(fallback);
}
