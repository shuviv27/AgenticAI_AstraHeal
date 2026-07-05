import { APIRequestContext, APIResponse, TestInfo } from '@playwright/test';

export type ApiRequestOptions = { headers?: Record<string, string>; data?: unknown; params?: Record<string, string | number | boolean> };

export class EnterpriseApiClient {
  constructor(private request: APIRequestContext, private baseUrl: string) {}

  url(path: string): string {
    if (/^https?:\/\//i.test(path)) return path;
    return `${this.baseUrl.replace(/\/$/, '')}/${path.replace(/^\//, '')}`;
  }

  async call(method: string, path: string, options: ApiRequestOptions = {}): Promise<APIResponse> {
    const url = this.url(path);
    const normalized = method.toUpperCase();
    if (normalized === 'GET') return this.request.get(url, options);
    if (normalized === 'POST') return this.request.post(url, options);
    if (normalized === 'PUT') return this.request.put(url, options);
    if (normalized === 'PATCH') return this.request.patch(url, options);
    if (normalized === 'DELETE') return this.request.delete(url, options);
    throw new Error(`[API_FRAMEWORK:UNSUPPORTED_METHOD] ${method}`);
  }

  async attachEvidence(testInfo: TestInfo, response: APIResponse, label: string): Promise<void> {
    const headers = await response.headers();
    let body = '';
    try { body = await response.text(); } catch { body = '<body unavailable>'; }
    await testInfo.attach(`${label}-status.txt`, { body: String(response.status()), contentType: 'text/plain' });
    await testInfo.attach(`${label}-headers.json`, { body: JSON.stringify(headers, null, 2), contentType: 'application/json' });
    await testInfo.attach(`${label}-body.txt`, { body: body.slice(0, 20000), contentType: 'text/plain' });
  }
}
