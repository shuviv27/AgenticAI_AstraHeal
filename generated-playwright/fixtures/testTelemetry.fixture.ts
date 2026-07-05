import { test as base } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';

type NetworkEvent = {
  type: 'request' | 'response' | 'requestfailed';
  timestamp: string;
  method?: string;
  url: string;
  status?: number;
  contentType?: string | null;
  failure?: string | null;
};

export const test = base.extend({
  page: async ({ page }, use, testInfo) => {
    const networkEvents: NetworkEvent[] = [];
    const runId = process.env.QA_AI_RUN_ID || new Date().toISOString().replace(/[:.]/g, '-');
    const titlePath = typeof (testInfo as any).titlePath === 'function' ? (testInfo as any).titlePath() : ((testInfo as any).titlePath || [testInfo.title]);
    const testId = titlePath.join(' › ').replace(/[^a-z0-9._-]+/gi, '-').slice(0, 150) || 'unknown-test';
    const bundleDir = path.join(process.cwd(), 'failures', `run-${runId}`, testId);

    page.on('request', request => {
      networkEvents.push({ type: 'request', timestamp: new Date().toISOString(), method: request.method(), url: request.url() });
    });
    page.on('response', response => {
      networkEvents.push({
        type: 'response',
        timestamp: new Date().toISOString(),
        method: response.request().method(),
        url: response.url(),
        status: response.status(),
        contentType: response.headers()['content-type'] ?? null,
      });
    });
    page.on('requestfailed', request => {
      networkEvents.push({ type: 'requestfailed', timestamp: new Date().toISOString(), method: request.method(), url: request.url(), failure: request.failure()?.errorText ?? null });
    });

    await page.context().tracing.start({ screenshots: true, snapshots: true, sources: true }).catch(() => undefined);
    await use(page);

    if (testInfo.status !== testInfo.expectedStatus) {
      await fs.mkdir(bundleDir, { recursive: true });
      await page.screenshot({ path: path.join(bundleDir, 'failure.png'), fullPage: true }).catch(() => undefined);
      await fs.writeFile(path.join(bundleDir, 'dom-snapshot.html'), await page.content().catch(() => ''), 'utf8').catch(() => undefined);
      await fs.writeFile(path.join(bundleDir, 'network-events.har'), JSON.stringify({ log: { version: '1.2', creator: { name: 'qa-ai-test-telemetry', version: '1.0.0' }, entries: toHarEntries(networkEvents) } }, null, 2), 'utf8').catch(() => undefined);
      await fs.writeFile(path.join(bundleDir, 'network-events.json'), JSON.stringify(networkEvents, null, 2), 'utf8').catch(() => undefined);
      await fs.writeFile(path.join(bundleDir, 'url.txt'), page.url(), 'utf8').catch(() => undefined);
      await page.context().tracing.stop({ path: path.join(bundleDir, 'trace.zip') }).catch(() => undefined);
      await testInfo.attach('qa-ai-failure-bundle', { body: bundleDir, contentType: 'text/plain' }).catch(() => undefined);
    } else {
      await page.context().tracing.stop().catch(() => undefined);
    }
  },
});

export { expect } from '@playwright/test';

function toHarEntries(events: NetworkEvent[]) {
  const requests = new Map<string, NetworkEvent>();
  const entries: any[] = [];
  for (const event of events) {
    const key = `${event.method || 'GET'} ${event.url}`;
    if (event.type === 'request') requests.set(key, event);
    if (event.type === 'response' || event.type === 'requestfailed') {
      const request = requests.get(key) ?? event;
      entries.push({
        startedDateTime: request.timestamp,
        time: 0,
        request: { method: request.method || event.method || 'GET', url: event.url, httpVersion: 'HTTP/1.1', headers: [], queryString: [], cookies: [], headersSize: -1, bodySize: -1 },
        response: { status: event.status ?? 0, statusText: event.failure ?? '', httpVersion: 'HTTP/1.1', headers: event.contentType ? [{ name: 'content-type', value: event.contentType }] : [], cookies: [], content: { size: 0, mimeType: event.contentType ?? '' }, redirectURL: '', headersSize: -1, bodySize: -1 },
        cache: {},
        timings: { send: 0, wait: 0, receive: 0 },
      });
    }
  }
  return entries;
}
