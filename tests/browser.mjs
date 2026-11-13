// Drives Cash Log in a phone-sized Chromium: Add opens first, the Calc and Tax tabs give Kuberlekha's answers,
// the keypad keeps a tape and registers, a list from Kuberlekha brings its tax rates, and after one visit the
// calculator works with no network at all.
//
//   node tests/browser.mjs   (Playwright from Kuberlekha's frontend; set PLAYWRIGHT_BROWSERS_PATH)
import { createServer } from 'node:http';
import { readFileSync, statSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(process.env.PLAYWRIGHT_FROM || 'D:/PersonalBooks/app/frontend/package.json');
const { chromium, devices } = require('playwright');

const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.wasm': 'application/wasm', '.zip': 'application/zip', '.py': 'text/plain; charset=utf-8', '.webmanifest': 'application/manifest+json' };
const server = createServer((req, res) => {
  let path = normalize(decodeURIComponent(new URL(req.url, 'http://x').pathname)).replace(/^[\\/]+/, '');
  if (!path || path.endsWith('\\') || path.endsWith('/')) path = join(path, 'index.html');
  const file = join(root, path);
  try {
    if (!file.startsWith(root) || !statSync(file).isFile()) throw new Error();
    res.writeHead(200, { 'Content-Type': TYPES[extname(file)] || 'application/octet-stream' });
    res.end(readFileSync(file));
  } catch {
    res.writeHead(404);
    res.end();
  }
});
await new Promise((r) => server.listen(8124, 'localhost', r));

let failures = 0;
const check = async (name, fn) => {
  try {
    await fn();
    console.log('ok  ', name);
  } catch (e) {
    failures += 1;
    console.error('FAIL', name, '\n     ', String(e.message || e).split('\n').slice(0, 6).join('\n      '));
  }
};
const vectors = JSON.parse(readFileSync(join(root, 'tests', 'vectors.json'), 'utf8'));
const inr = (p) => {
  const s = String(p).padStart(3, '0');
  const w = s.slice(0, -2);
  return `₹ ${w.length > 3 ? w.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ',') + ',' + w.slice(-3) : w}.${s.slice(-2)}`;
};

const browser = await chromium.launch();
const context = await browser.newContext({ ...devices['iPhone 13'], serviceWorkers: 'allow' });
const page = await context.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
const { expect } = require('@playwright/test');
expect.configure({ timeout: 30_000 });

await check('Cash Log opens on Add', async () => {
  await page.goto('http://localhost:8124/');
  await expect(page.getByRole('button', { name: 'Add', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('button', { name: 'Calc' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Tax' })).toBeVisible();
});

await check('Calc: TVM defaults, then solving for PMT', async () => {
  await page.getByRole('button', { name: 'Calc' }).click();
  const answer = page.getByRole('region', { name: 'Answer' });
  await expect(answer).toContainText('₹ 23,00,386.89');
  await page.getByRole('radio', { name: 'PMT' }).click();
  await page.getByLabel('N (number of payments)').fill('240');
  await page.getByLabel('I/Y (annual rate, %)').fill('8.5');
  await page.getByLabel('PV (present value)').fill('50L');
  await page.getByLabel('FV (future value)').fill('0');
  await expect(answer).toContainText('-₹ 43,391.16');
  await expect(page.getByLabel('PMT (payment each period): the answer')).toHaveValue('-₹ 43,391.16');
});

await check('Calc: a wrong box is named, and fixing it brings the answer back with the cursor kept', async () => {
  const n = page.getByLabel('N (number of payments)');
  await n.fill('24x');
  await expect(page.getByRole('alert')).toContainText("'24x' is not a number");
  await n.press('Backspace');
  await page.keyboard.type('0');
  await expect(n).toHaveValue('240');
  await expect(n).toBeFocused();
  await expect(page.getByRole('region', { name: 'Answer' })).toContainText('-₹ 43,391.16');
});

await check('Calc: cash flows give Excel IRR and every root of a two-IRR project', async () => {
  await page.getByLabel('Calculator', { exact: true }).selectOption('cash_flows');
  await page.getByLabel('CF0 amount').fill('-1000');
  await page.getByLabel('CF1 amount').fill('300');
  await page.getByLabel('CF1 count').fill('5');
  await page.getByLabel('Discount rate per period (%)').fill('10');
  const answer = page.getByRole('region', { name: 'Answer' });
  await expect(answer).toContainText('₹ 137.24');
  await expect(answer).toContainText('15.2382%');
});

await check('Calc: keypad, tape and a register used in a box', async () => {
  await page.getByRole('button', { name: 'Keypad, registers and tape' }).click();
  const pad = page.getByRole('region', { name: 'Keypad' });
  await pad.getByLabel('Expression').fill('1,25,000 * 12% + 2^10');
  await pad.getByLabel('Expression').press('Enter');
  await expect(pad.getByLabel('Expression')).toHaveValue('16024');
  await expect(pad).toContainText('= 16,024');
  page.once('dialog', (d) => d.accept('3'));
  await page.getByRole('button', { name: 'Store NPV in a register' }).click();
  await expect(pad.getByRole('button', { name: /^M3: 137\.236/ })).toBeVisible();
  await page.getByLabel('CF1 amount').fill('m3');
  await expect(page.getByRole('region', { name: 'Answer' })).toContainText('NPV');
});

await check('Tax: built-in rates give Kuberlekha\u2019s figure', async () => {
  await page.getByRole('button', { name: 'Tax' }).click();
  const v = vectors.taxes.find((t) => t.fy === '2026-27' && t.amounts.ltcg_112a === 3_00_000_00);
  await expect(page.getByText('Built-in rates')).toBeVisible();
  await page.getByLabel('Salary and pension').fill('18L');
  await page.getByLabel('Long-term capital gains, listed equity and equity funds (112A)').fill('3,00,000');
  await page.getByLabel('Interest and other income').fill('50000');
  await expect(page.getByRole('region', { name: 'Tax payable' })).toContainText(inr(v.expected.value.rounded_tax_paise));
});

await check('Tax: a list from Kuberlekha brings its own rates', async () => {
  await page.getByRole('button', { name: 'Settings' }).click();
  const rules = JSON.parse(readFileSync(join(root, 'py', 'tax-defaults.json'), 'utf8')).map((r) => ({ ...r, cess_bp: 500 }));
  const list = { app: 'cashlog', version: 1, entity: 'Test', made: '2026-11-13', categories: [{ id: 1, name: 'Food and Dining', group: null }], people: [], accounts: [], tax_rules: rules };
  await page.locator('#list-file').setInputFiles({ name: 'list.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(list)) });
  await expect(page.getByText('The Tax tab uses the rates from this list')).toBeVisible();
  await page.getByRole('button', { name: 'Tax' }).click();
  await expect(page.getByText('Rates from your Kuberlekha list.')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Tax payable' }).locator('..')).toContainText('cess (5%)');
});

await check('Offline after one visit: the calculator still works with no network', async () => {
  await page.evaluate(() => navigator.serviceWorker.ready);
  await expect
    .poll(async () => page.evaluate(async () => (await caches.keys()).join(',')), { timeout: 60_000 })
    .toContain('cl-pyodide-314.0.7');
  await expect
    .poll(async () => page.evaluate(async () => !!(await caches.match('./pyodide/pyodide.asm.wasm'))), { timeout: 60_000 })
    .toBe(true);
  await context.setOffline(true);
  const fresh = await context.newPage();
  await fresh.goto('http://localhost:8124/');
  await fresh.getByRole('button', { name: 'Calc' }).click();
  await expect(fresh.getByRole('region', { name: 'Answer' })).toBeVisible();
  await fresh.close();
  await context.setOffline(false);
});

await check('no script errors', async () => {
  if (errors.length) throw new Error(errors.join('\n'));
});

await browser.close();
server.close();
if (failures) {
  console.error(`${failures} failed`);
  process.exit(1);
}
console.log('All browser checks passed.');
