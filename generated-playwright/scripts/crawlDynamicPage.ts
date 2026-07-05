import { chromium, type BrowserContext, type Page } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'fs';
import { join } from 'path';

function arg(name: string, fallback = ''): string {
  const idx = process.argv.indexOf(`--${name}`);
  return idx >= 0 && process.argv[idx + 1] ? process.argv[idx + 1] : fallback;
}

const url = arg('url', process.env.BASE_URL ?? '');
const feature = arg('feature', 'feature');
const headed = process.argv.includes('--headed');
const reportsDir = join(process.cwd(), 'reports');
mkdirSync(reportsDir, { recursive: true });

async function prepareContext(context: BrowserContext, targetUrl: string): Promise<void> {
  const origin = new URL(targetUrl).origin;
  await context.grantPermissions(['geolocation', 'notifications'], { origin }).catch(() => undefined);
  await context.setGeolocation({ latitude: 40.7128, longitude: -74.0060 }).catch(() => undefined);
}

async function dismissCommonOverlays(page: Page): Promise<void> {
  const candidates = [
    /accept all/i,
    /accept/i,
    /agree/i,
    /allow all/i,
    /ok/i,
    /got it/i,
    /close/i,
    /continue/i,
  ];
  for (const name of candidates) {
    const button = page.getByRole('button', { name }).first();
    if (await button.isVisible({ timeout: 700 }).catch(() => false)) {
      await button.click({ timeout: 1500 }).catch(() => undefined);
      break;
    }
  }
}

async function autoScrollFullPage(page: Page): Promise<void> {
  await page.evaluate(async () => {
    await new Promise<void>((resolve) => {
      let total = 0;
      const distance = Math.max(320, Math.floor(window.innerHeight * 0.75));
      const timer = window.setInterval(() => {
        window.scrollBy(0, distance);
        total += distance;
        if (total >= document.body.scrollHeight - window.innerHeight) {
          window.clearInterval(timer);
          window.scrollTo(0, 0);
          resolve();
        }
      }, 120);
    });
  });
  // Do not wait for networkidle; modern apps may keep analytics/streaming calls active.
  await page.waitForTimeout(500).catch(() => undefined);
}

if (!url) {
  console.error('Missing --url or BASE_URL');
  process.exit(2);
}

const browser = await chromium.launch({
  headless: !headed,
  args: [
    '--use-fake-ui-for-media-stream',
    '--use-fake-device-for-media-stream',
    '--disable-notifications',
  ],
});
const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  geolocation: { latitude: 40.7128, longitude: -74.0060 },
  permissions: ['geolocation', 'notifications'],
  ignoreHTTPSErrors: true,
  locale: 'en-US',
});
await prepareContext(context, url);
const page = await context.newPage();
page.on('dialog', async dialog => dialog.accept().catch(() => undefined));
await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
await dismissCommonOverlays(page);
await autoScrollFullPage(page);
await dismissCommonOverlays(page);

const data = await page.evaluate(() => {
  function textOf(el: Element): string {
    return (el.textContent || '').replace(/[\u2010-\u2015]/g, '-').replace(/\s+/g, ' ').trim().slice(0, 300);
  }
  function attrs(el: Element): Record<string, string> {
    const out: Record<string, string> = {};
    for (const attr of ['id', 'class', 'href', 'aria-label', 'aria-labelledby', 'role', 'data-test', 'data-testid', 'data-qa', 'name', 'type', 'alt', 'title', 'placeholder']) {
      const v = el.getAttribute(attr);
      if (v) out[attr] = v.slice(0, 300);
    }
    return out;
  }
  function cssPath(el: Element): string {
    const parts: string[] = [];
    let cur: Element | null = el;
    while (cur && cur.nodeType === 1 && parts.length < 6) {
      let part = cur.tagName.toLowerCase();
      const id = cur.getAttribute('id');
      const testid = cur.getAttribute('data-testid') || cur.getAttribute('data-test') || cur.getAttribute('data-qa');
      if (testid) part += `[data-testid-or-test="${testid.slice(0,80).replace(/"/g, '')}"]`;
      else if (id) part += `#${id.replace(/[^a-zA-Z0-9_-]/g, '')}`;
      parts.unshift(part);
      cur = cur.parentElement;
    }
    return parts.join(' > ');
  }
  const baseSelector = 'a,button,input,select,textarea,[role],h1,h2,h3,h4,img,main,section,footer,header,iframe,[aria-label],[data-testid],[data-test],[data-qa]';
  const elements: any[] = [];
  const shadowHosts: any[] = [];
  function collect(root: Document | ShadowRoot, source: string): void {
    Array.from(root.querySelectorAll(baseSelector)).forEach((el) => {
      const html = el as HTMLElement;
      if ((el as any).shadowRoot) shadowHosts.push({ tag: el.tagName.toLowerCase(), text: textOf(el), attrs: attrs(el), cssPath: cssPath(el) });
      elements.push({
        index: elements.length,
        source,
        tag: el.tagName.toLowerCase(),
        text: textOf(el),
        attrs: attrs(el),
        cssPath: cssPath(el),
        boundingBox: (() => { const r = html.getBoundingClientRect(); return { x:r.x, y:r.y, width:r.width, height:r.height }; })(),
        visible: !!(html.offsetParent || html.getClientRects().length) || el.tagName.toLowerCase() === 'body',
      });
      const sr = (el as any).shadowRoot as ShadowRoot | undefined;
      if (sr) collect(sr, `${source}::shadow(${el.tagName.toLowerCase()})`);
    });
  }
  collect(document, 'document');
  const frames = Array.from(document.querySelectorAll('iframe')).map((f, idx) => ({ index: idx, attrs: attrs(f), text: textOf(f), cssPath: cssPath(f) }));
  const links = elements.filter(e => e.tag === 'a' || e.attrs.href);
  const buttons = elements.filter(e => e.tag === 'button' || e.attrs.role === 'button');
  const headings = elements.filter(e => /^h[1-4]$/.test(e.tag) || e.attrs.role === 'heading');
  const formControls = elements.filter(e => ['input','select','textarea'].includes(e.tag) || e.attrs.role === 'textbox' || e.attrs.role === 'combobox');
  const locatorCandidates = elements
    .filter(e => e.visible && (e.attrs['data-testid'] || e.attrs['data-test'] || e.attrs['data-qa'] || e.attrs['aria-label'] || e.attrs.href || e.text))
    .slice(0, 500)
    .map(e => ({ tag: e.tag, text: e.text, attrs: e.attrs, cssPath: e.cssPath, source: e.source }));
  return {
    url: location.href,
    title: document.title,
    viewport: { width: window.innerWidth, height: window.innerHeight },
    bodyTextPreview: (document.body?.innerText || '').replace(/[\u2010-\u2015]/g, '-').replace(/\s+/g, ' ').trim().slice(0, 6000),
    summary: {
      elements: elements.length,
      links: links.length,
      buttons: buttons.length,
      headings: headings.length,
      formControls: formControls.length,
      images: elements.filter(e => e.tag === 'img').length,
      shadowHosts: shadowHosts.length,
      iframes: frames.length,
    },
    links,
    buttons,
    headings,
    formControls,
    shadowHosts,
    iframes: frames,
    locatorCandidates,
    elements: elements.slice(0, 2000),
  };
});

await page.screenshot({ path: join(reportsDir, `${feature}-full-page.png`), fullPage: true }).catch(() => undefined);
writeFileSync(join(reportsDir, 'dynamic-dom-map.json'), JSON.stringify({ feature, crawledAt: new Date().toISOString(), ...data }, null, 2), 'utf-8');
await browser.close();
console.log(JSON.stringify({ ok: true, feature, url, summary: data.summary }, null, 2));
