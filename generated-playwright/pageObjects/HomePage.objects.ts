import type { LocatorDefinition } from '../utils/locatorFactory';

export const HomePageObjects = {
  emailInput: { strategy: 'label', value: 'Email', description: 'Email' },
} satisfies Record<string, LocatorDefinition>;
