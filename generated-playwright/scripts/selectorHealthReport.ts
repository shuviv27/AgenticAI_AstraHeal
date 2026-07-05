import fs from 'node:fs';
import path from 'node:path';

type ComponentScore = {
  component: string;
  locatorCount: number;
  fallbackCount: number;
  inlineLocatorRisk: number;
  stabilityScore: number;
};

const root = process.cwd();
const outDir = path.join(root, 'reports', 'selector-health');
fs.mkdirSync(outDir, { recursive: true });

const codeFiles = walk(root).filter(file => /\.(ts|tsx|js|jsx)$/.test(file) && !file.includes('node_modules'));
const scores: ComponentScore[] = [];
for (const file of codeFiles) {
  const rel = path.relative(root, file).replace(/\\/g, '/');
  const text = fs.readFileSync(file, 'utf8');
  const locatorCount = count(text, /\b(page|this\.page)\.locator\s*\(/g) + count(text, /getBy(Role|Text|TestId|Label|Placeholder|AltText|Title)\s*\(/g);
  const fallbackCount = count(text, /fallbacks\s*:/g) + count(text, /SmartLocator/g);
  const isSpec = /\.(spec|test)\.(ts|tsx|js|jsx)$/.test(rel);
  const inlineLocatorRisk = isSpec ? locatorCount : 0;
  if (locatorCount || fallbackCount || inlineLocatorRisk) {
    const stabilityScore = Math.max(0, Math.min(1, 1 - inlineLocatorRisk * 0.08 + Math.min(0.25, fallbackCount * 0.03)));
    scores.push({ component: rel, locatorCount, fallbackCount, inlineLocatorRisk, stabilityScore: Number(stabilityScore.toFixed(3)) });
  }
}

scores.sort((a, b) => a.stabilityScore - b.stabilityScore || b.inlineLocatorRisk - a.inlineLocatorRisk);
const shortlist = scores.filter(s => s.stabilityScore < 0.8 || s.inlineLocatorRisk > 0).slice(0, 25);
const payload = { generatedAt: new Date().toISOString(), componentScores: scores, shortlistForTestability: shortlist };
fs.writeFileSync(path.join(outDir, 'selector-health-report.json'), JSON.stringify(payload, null, 2));
fs.writeFileSync(path.join(outDir, 'selector-health-report.html'), render(payload));
console.log(`Selector health report generated: ${path.join(outDir, 'selector-health-report.html')}`);

function walk(dir: string): string[] {
  const ignored = new Set(['node_modules', '.git', 'reports', 'playwright-report', 'test-results', 'dist', 'build']);
  const output: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (ignored.has(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) output.push(...walk(full));
    else output.push(full);
  }
  return output;
}

function count(text: string, rx: RegExp): number {
  return [...text.matchAll(rx)].length;
}

function h(value: unknown): string {
  return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function render(payload: { generatedAt: string; componentScores: ComponentScore[]; shortlistForTestability: ComponentScore[] }): string {
  const rows = payload.componentScores.map(s => `<tr><td><code>${h(s.component)}</code></td><td>${s.locatorCount}</td><td>${s.fallbackCount}</td><td>${s.inlineLocatorRisk}</td><td>${s.stabilityScore}</td></tr>`).join('');
  const items = payload.shortlistForTestability.map(s => `<li><code>${h(s.component)}</code> — inline locator risk: ${s.inlineLocatorRisk}, fallback count: ${s.fallbackCount}, stability: ${s.stabilityScore}</li>`).join('') || '<li>No selector health risks found.</li>';
  return `<!doctype html><html><head><meta charset="utf-8"><title>Selector Health Report</title><style>body{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f8fafc;color:#0f172a}.card{background:white;border:1px solid #dbe3ef;border-radius:14px;padding:16px;margin:14px 0}table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #e2e8f0;padding:8px;text-align:left}code{background:#0f172a;color:#dbeafe;padding:3px 6px;border-radius:6px}</style></head><body><h1>Selector Health Report</h1><div class="card">Generated: ${h(payload.generatedAt)}</div><div class="card"><h2>Shortlist for Dev Testability Improvements</h2><ul>${items}</ul></div><div class="card"><h2>Component Stability Scores</h2><table><tr><th>Component</th><th>Locators</th><th>Fallbacks</th><th>Inline Spec Risk</th><th>Stability</th></tr>${rows}</table></div></body></html>`;
}
