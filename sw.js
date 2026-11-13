/* Service worker: cache-first for the app shell so the app opens with no signal.
   Bump CACHE_VERSION on every deploy; old caches are deleted on activate.

   1.2: the calculator engine (py/) is part of the shell. Pyodide (pyodide/, about 13 MB) has its own cache named
   for its version: it is downloaded once, kept across app releases, and replaced only when PYODIDE changes. */
const CACHE_VERSION = 'cl-v6';
const PYODIDE = 'cl-pyodide-314.0.7';
const SHELL = [
  './',
  './index.html',
  './styles.css',
  './app.js',
  './tools.js',
  './manifest.webmanifest',
  './icons/icon.svg',
  './icons/icon-small.svg',
  './icons/logo-light.svg',
  './icons/logo-dark.svg',
  './icons/apple-touch-icon.png',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './py/MANIFEST.json',
  './py/phone.py',
  './py/tax-defaults.json',
  './py/calc/__init__.py',
  './py/calc/cashflow.py',
  './py/calc/core.py',
  './py/calc/expr.py',
  './py/calc/rates.py',
  './py/calc/returns.py',
  './py/calc/risk.py',
  './py/calc/stats.py',
  './py/calc/tax_engine.py',
  './py/calc/tvm.py',
  './py/calc/utils.py',
];
const PYODIDE_FILES = [
  './pyodide/pyodide.mjs',
  './pyodide/pyodide.asm.mjs',
  './pyodide/pyodide.asm.wasm',
  './pyodide/python_stdlib.zip',
  './pyodide/pyodide-lock.json',
];

async function fillPyodide() {
  const cache = await caches.open(PYODIDE);
  for (const url of PYODIDE_FILES) {
    if (!(await cache.match(url))) await cache.add(new Request(url, { cache: 'reload' }));
  }
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE_VERSION)
      // cache: 'reload' skips the browser's HTTP cache, so a release is never installed with older files.
      .then((cache) => cache.addAll(SHELL.map((url) => new Request(url, { cache: 'reload' }))))
      .then(fillPyodide)
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_VERSION && k !== PYODIDE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== self.location.origin) return;
  event.respondWith(
    caches.match(req, { ignoreSearch: true }).then((cached) => cached || fetch(req)),
  );
});
