// Runs the calculator engine under the very Pyodide the phone uses (./pyodide) and checks every answer against
// the one desktop Python gave in Kuberlekha (tests/vectors.json, written by Kuberlekha's scripts/export_calc.py).
// Every value must match exactly, digit for digit. Also checks the engine files match MANIFEST.json.
//
//   node tests/run-vectors.mjs
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const { loadPyodide } = await import(pathToFileURL(join(root, 'pyodide', 'pyodide.mjs')).href);

let failures = 0;
const fail = (msg) => {
  failures += 1;
  console.error('FAIL', msg);
};

// 1. The copied engine is exactly what Kuberlekha exported.
const manifest = JSON.parse(readFileSync(join(root, 'py', 'MANIFEST.json'), 'utf8'));
for (const [file, sha] of Object.entries(manifest.files)) {
  const got = createHash('sha256').update(readFileSync(join(root, 'py', file))).digest('hex');
  if (got !== sha) fail(`${file} differs from Kuberlekha's copy`);
}
const onDisk = readdirSync(join(root, 'py', 'calc')).filter((f) => f.endsWith('.py'));
if (onDisk.length !== Object.keys(manifest.files).length) fail('py/calc has files the manifest does not list');
// GitHub Pages runs Jekyll unless .nojekyll exists, and Jekyll drops files starting with _ (calc/__init__.py).
try {
  readFileSync(join(root, '.nojekyll'));
} catch {
  fail('.nojekyll is missing: GitHub Pages would not publish py/calc/__init__.py');
}
// Offline: the service worker must keep every engine file and every Pyodide file.
const sw = readFileSync(join(root, 'sw.js'), 'utf8');
for (const f of [...Object.keys(manifest.files), 'phone.py', 'tax-defaults.json', 'MANIFEST.json'])
  if (!sw.includes(`'./py/${f}'`)) fail(`sw.js does not cache py/${f}`);
for (const f of readdirSync(join(root, 'pyodide')))
  if (!sw.includes(`'./pyodide/${f}'`) && f !== 'pyodide.js') fail(`sw.js does not cache pyodide/${f}`);

// 2. Load Pyodide from the local folder only (offline), and the engine the same way the app does.
const t0 = Date.now();
const py = await loadPyodide({ indexURL: join(root, 'pyodide') + '/' });
py.FS.mkdirTree('/home/pyodide/calc');
for (const f of onDisk) py.FS.writeFile(`/home/pyodide/calc/${f}`, readFileSync(join(root, 'py', 'calc', f)));
py.FS.writeFile('/home/pyodide/phone.py', readFileSync(join(root, 'py', 'phone.py')));
py.runPython('import sys; sys.path.insert(0, "/home/pyodide"); import phone');
const phone = py.globals.get('phone') ?? py.pyimport('phone');
console.log(`Pyodide ${py.version} (Python ${py.runPython('import sys; sys.version.split()[0]')}) loaded in ${Date.now() - t0} ms`);

const vectors = JSON.parse(readFileSync(join(root, 'tests', 'vectors.json'), 'utf8'));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

const cat = JSON.parse(phone.catalogue_json());
if (!same(cat, { ok: true, value: vectors.catalogue })) fail('catalogue differs');

for (const v of vectors.runs) {
  const got = JSON.parse(phone.run_json(v.key, JSON.stringify(v.inputs)));
  if (!same(got, v.expected)) fail(`run ${v.key} ${JSON.stringify(v.inputs).slice(0, 80)}\n  got  ${JSON.stringify(got).slice(0, 300)}\n  want ${JSON.stringify(v.expected).slice(0, 300)}`);
}
for (const v of vectors.expressions) {
  const got = JSON.parse(phone.evaluate_json(v.expression, JSON.stringify(v.registers)));
  if (!same(got, v.expected)) fail(`keypad ${v.expression}: got ${JSON.stringify(got)} want ${JSON.stringify(v.expected)}`);
}
const rules = JSON.parse(readFileSync(join(root, 'py', 'tax-defaults.json'), 'utf8'));
for (const v of vectors.taxes) {
  const r = rules.find((x) => x.fy === v.fy);
  const got = JSON.parse(phone.tax_json(JSON.stringify(r), JSON.stringify(v.amounts)));
  if (!same(got, v.expected)) fail(`tax ${v.fy} ${JSON.stringify(v.amounts)}`);
  // The same amounts typed the way people write them, grouped (12,75,000.00) and in lakhs (12.75L).
  for (const style of ['grouped', 'lakh']) {
    const typed = Object.fromEntries(
      Object.entries(v.amounts).map(([k, p]) => {
        const rupees = `${Math.trunc(p / 100)}.${String(p % 100).padStart(2, '0')}`;
        if (style === 'lakh') return [k, `${p / 1e7}L`]; // the test amounts are whole thousands, so this is exact
        return [k, rupees.replace(/\B(?=(\d{2})+(?!\d)(?=\d{3}\.))|\B(?=\d{3}\.)/g, ',')];
      }),
    );
    const viaText = JSON.parse(phone.tax_text_json(JSON.stringify(r), JSON.stringify(typed)));
    if (!same(viaText, v.expected)) fail(`typed tax ${style} ${JSON.stringify(typed)}: ${JSON.stringify(viaText).slice(0, 200)}`);
  }
}
const bad = JSON.parse(phone.tax_text_json(JSON.stringify(rules[0]), JSON.stringify({ salary: '12,5x' })));
if (bad.ok || bad.field !== 'salary') fail(`a wrong amount is not named: ${JSON.stringify(bad)}`);

const total = 2 + vectors.runs.length + vectors.expressions.length + vectors.taxes.length * 3;
if (failures) {
  console.error(`${failures} of ${total} checks failed.`);
  process.exit(1);
}
console.log(`All ${total} checks match Kuberlekha (${vectors.made_by}, Python ${vectors.python}) exactly.`);
