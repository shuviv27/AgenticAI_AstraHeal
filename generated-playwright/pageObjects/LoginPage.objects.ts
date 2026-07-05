import type { LocatorDefinition } from '../utils/locatorFactory';

// Starter locator file. The Python reuse-aware generator will reuse existing locators
// or add new application-specific locators here after reading user requirements.
export const LoginPageObjects = {
  loginButton: { strategy: 'role', role: 'button', value: 'Login', description: 'Login button', fallbacks: [{ strategy: 'role', role: 'link', value: 'Login' }, { strategy: 'text', value: 'Login' }] },
  dashboard: { strategy: 'text', value: 'Dashboard', description: 'Dashboard', fallbacks: [{ strategy: 'role', role: 'heading', value: 'Dashboard' }, { strategy: 'role', role: 'button', value: 'Dashboard' }, { strategy: 'role', role: 'link', value: 'Dashboard' }] },
} satisfies Record<string, LocatorDefinition>;
