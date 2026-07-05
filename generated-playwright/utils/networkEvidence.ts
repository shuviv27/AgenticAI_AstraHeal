import type { Page, Response } from '@playwright/test';

export async function waitForHealthyApiResponse(
  page: Page,
  urlPart: string | RegExp,
  action: () => Promise<void>,
  options?: { timeout?: number; requireNonEmptyArrayKey?: string }
): Promise<Response> {
  const matcher = (response: Response) => {
    const url = response.url();
    const matchesUrl = typeof urlPart === 'string' ? url.includes(urlPart) : urlPart.test(url);
    return matchesUrl && response.request().resourceType() !== 'image';
  };
  const responsePromise = page.waitForResponse(matcher, { timeout: options?.timeout ?? 15_000 });
  await action();
  const response = await responsePromise;
  const status = response.status();
  if ([401, 403].includes(status)) throw new Error(`[RCA:AUTH_OR_PERMISSION_ISSUE] API ${response.url()} returned ${status}`);
  if (status >= 500) throw new Error(`[RCA:PRODUCT_OR_ENVIRONMENT_API_ISSUE] API ${response.url()} returned ${status}`);
  if (status >= 400) throw new Error(`[RCA:API_CONTRACT_ISSUE] API ${response.url()} returned ${status}`);

  if (options?.requireNonEmptyArrayKey) {
    const body = await response.json().catch(() => null) as any;
    const value = body?.[options.requireNonEmptyArrayKey];
    if (!Array.isArray(value) || value.length === 0) {
      throw new Error(`[RCA:TEST_DATA_ISSUE] API ${response.url()} returned no usable ${options.requireNonEmptyArrayKey}`);
    }
  }
  return response;
}
