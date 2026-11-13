/* Kuberlekha Cash Log: the Calculator and Tax tabs (Kuberlekha decision #120).

   Every answer is worked out by Kuberlekha's own Python engine (py/calc, copied unchanged by Kuberlekha's
   scripts/export_calc.py) running on the phone under Pyodide (pyodide/, Python 3.14 compiled to WebAssembly).
   So a figure here is the figure Kuberlekha shows, to the last digit; tests/run-vectors.mjs checks that.
   Nothing is sent anywhere, and after the first visit everything works without a signal.

   This file draws only inside <div id="tool">, and uses data-t-* attributes so Cash Log's own handlers in
   app.js never see its clicks. Python loads the first time one of the two tabs opens, not when Cash Log opens. */
'use strict';

const CashTools = (() => {
  const STORE = 'cl.tools';
  const PY_FILES = ['phone.py'];
  const NUMERIC = /^-?\d+(\.\d+)?$/;
  const REGISTER = /^\s*(-?)\s*(m\d|ans)\s*$/i;

  const saved = (() => {
    try {
      return JSON.parse(localStorage.getItem(STORE) || '{}');
    } catch {
      return {};
    }
  })();
  const T = {
    view: null,
    root: null,
    py: null, // the phone.py module, once loaded
    loading: null,
    loadError: null,
    catalogue: null,
    current: saved.current || 'tvm',
    inputs: saved.inputs || {},
    registers: saved.registers || {},
    tape: saved.tape || [],
    sheets: saved.sheets || {}, // calculator key -> [{name, inputs}]
    keypad: false,
    expr: '',
    exprError: null,
    taxFy: saved.taxFy || null,
    taxAmounts: saved.taxAmounts || {},
    taxDefaults: null,
    result: null,
    timer: null,
    storing: null, // the value waiting for a register
  };

  function persist() {
    try {
      localStorage.setItem(
        STORE,
        JSON.stringify({
          current: T.current,
          inputs: T.inputs,
          registers: T.registers,
          tape: T.tape.slice(-200),
          sheets: T.sheets,
          taxFy: T.taxFy,
          taxAmounts: T.taxAmounts,
        }),
      );
    } catch {
      /* not remembered; the calculator still works */
    }
  }

  const esc = (s) =>
    String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

  // ---- Python ----------------------------------------------------------------------------------------------

  async function python() {
    if (T.py) return T.py;
    if (!T.loading) {
      T.loading = (async () => {
        const base = new URL('./', location.href);
        const { loadPyodide } = await import(new URL('pyodide/pyodide.mjs', base).href);
        const py = await loadPyodide({ indexURL: new URL('pyodide/', base).href });
        const manifest = await (await fetch(new URL('py/MANIFEST.json', base))).json();
        py.FS.mkdirTree('/home/pyodide/calc');
        for (const file of [...Object.keys(manifest.files), ...PY_FILES]) {
          const res = await fetch(new URL(`py/${file}`, base));
          if (!res.ok) throw new Error(`Could not load ${file}.`);
          py.FS.writeFile(`/home/pyodide/${file}`, await res.text());
        }
        py.runPython('import sys\nif "/home/pyodide" not in sys.path: sys.path.insert(0, "/home/pyodide")\nimport phone');
        T.py = py.pyimport('phone');
        T.catalogue = call('catalogue_json').value;
        T.taxDefaults = await (await fetch(new URL('py/tax-defaults.json', base))).json();
        return T.py;
      })().catch((err) => {
        T.loading = null;
        T.loadError = err && err.message ? err.message : String(err);
        throw err;
      });
    }
    return T.loading;
  }

  /** Calls a phone.py function with JSON text; returns {ok, value} or {ok: false, code, message, field}. */
  function call(name, ...args) {
    return JSON.parse(T.py[name](...args));
  }

  // ---- formatting (by string: never through a float) -------------------------------------------------------

  function groupIndian(digits) {
    if (digits.length <= 3) return digits;
    return digits.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ',') + ',' + digits.slice(-3);
  }
  function groupDecimal(text) {
    const m = /^(-?)(\d+)(\.\d+)?$/.exec(text);
    return m ? `${m[1]}${groupIndian(m[2])}${m[3] || ''}` : text;
  }
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function fmt(v) {
    const { value, unit } = v;
    if (unit === 'text') return value;
    if (unit === 'date') {
      const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
      return m ? `${m[3]}-${MONTHS[Number(m[2]) - 1]}-${m[1]}` : value;
    }
    if (!NUMERIC.test(value)) return value;
    if (unit === 'money') {
      const neg = value.startsWith('-');
      return `${neg ? '-' : ''}₹ ${groupDecimal(neg ? value.slice(1) : value)}`;
    }
    const suffix = { percent: '%', periods: ' periods', years: ' years', days: value === '1' ? ' day' : ' days' }[unit] || '';
    return groupDecimal(value) + suffix;
  }
  /** Integer paise -> ₹ 12,34,567.00 (from the tax engine, which works in paise). */
  function inrPaise(p) {
    const neg = p < 0;
    const s = String(Math.abs(p)).padStart(3, '0');
    return `${neg ? '-' : ''}₹ ${groupIndian(s.slice(0, -2))}.${s.slice(-2)}`;
  }
  /** Whole rupees without paise when there are none (slab limits): ₹ 12,00,000. */
  const inrShort = (p) => (p % 100 === 0 ? `₹ ${groupIndian(String(Math.abs(p) / 100))}` : inrPaise(p));
  const pct = (bp) => `${(bp / 100).toFixed(2).replace(/\.?0+$/, '')}%`; // display only: basis points to text

  // ---- calculator ------------------------------------------------------------------------------------------

  const allCalcs = () => (T.catalogue ? T.catalogue.families.flatMap((f) => f.calculators) : []);
  const calcDef = () => allCalcs().find((c) => c.key === T.current) || allCalcs()[0];

  function todayText() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  function defaultsOf(c) {
    const out = {};
    const riskFree = window.cashLogRiskFree ? window.cashLogRiskFree() : null;
    for (const f of c.fields) {
      if (f.kind === 'table') out[f.key] = (f.rows || []).map((r) => ({ ...r }));
      else if (f.default_from === 'risk_free' && riskFree) out[f.key] = riskFree;
      else if (f.kind === 'flows') out[f.key] = [{ amount: '-100000', count: '1' }, { amount: '30000', count: '5' }];
      else if (f.kind === 'dated_flows')
        out[f.key] = [
          { date: '2025-04-01', amount: '-100000' },
          { date: todayText(), amount: '112000' },
        ];
      else if (f.kind === 'date') out[f.key] = f.default || (f.optional ? '' : todayText());
      else out[f.key] = f.default;
    }
    return out;
  }

  function values(c) {
    if (!T.inputs[c.key]) T.inputs[c.key] = defaultsOf(c);
    return T.inputs[c.key];
  }

  function isShown(f, vals, defs) {
    return Object.entries(f.show_when || {}).every(([k, allowed]) => {
      const raw = vals[k];
      const v = typeof raw === 'string' ? raw : (defs.find((d) => d.key === k) || {}).default || '';
      return allowed.includes(v);
    });
  }

  function withRegisters(vals) {
    const sub = (t) => {
      const m = REGISTER.exec(t);
      if (!m) return t;
      const v = T.registers[m[2].toLowerCase()] || '';
      if (!m[1] || !v) return v;
      return v.startsWith('-') ? v.slice(1) : `-${v}`;
    };
    const out = {};
    for (const [k, v] of Object.entries(vals))
      out[k] = typeof v === 'string' ? sub(v) : v.map((r) => Object.fromEntries(Object.entries(r).map(([ck, cv]) => [ck, ck === 'date' ? cv : sub(cv)])));
    return out;
  }

  function compute() {
    const c = calcDef();
    T.result = call('run_json', c.key, JSON.stringify(withRegisters(values(c))));
  }

  function fieldHtml(c, f, vals, solving) {
    const id = `t-${c.key}-${f.key}`;
    const err = T.result && !T.result.ok && T.result.field === f.key ? T.result.message : '';
    const errHtml = err ? `<p class="t-err" role="alert">${esc(err)}</p>` : '';
    const hint = f.hint ? `<p class="small muted">${esc(f.hint)}</p>` : '';
    if (f.kind === 'solve')
      return `<div class="field"><div class="label">${esc(f.label)}</div><div class="seg" role="radiogroup" aria-label="${esc(f.label)}">${f.options
        .map((o) => `<button type="button" role="radio" aria-checked="${solving === o.value}" class="${solving === o.value ? 'on' : ''}" data-t-solve="${esc(o.value)}" data-t-key="${esc(f.key)}">${esc(o.label)}</button>`)
        .join('')}</div></div>`;
    if (f.kind === 'table') {
      const rows = vals[f.key] || [];
      const cols = f.columns || [];
      const head = `<div class="t-row t-head"><span class="t-cf">#</span>${cols.map((c) => `<span class="t-col">${esc(c.label)}${c.optional ? '<span class="muted"> (opt.)</span>' : ''}</span>`).join('')}<span class="t-x"></span></div>`;
      const body = rows
        .map(
          (r, i) => `<div class="t-row"><span class="t-cf">${i + 1}</span>${cols
            .map((c) => `<input class="input${c.kind === 'text' || c.kind === 'date' ? '' : ' num'} t-col" ${c.kind === 'date' ? 'type="date"' : c.kind === 'text' ? 'autocomplete="off"' : 'inputmode="decimal" autocomplete="off"'} aria-label="Row ${i + 1} ${esc(c.label)}" value="${esc(r[c.key] || '')}" data-t-row="${esc(f.key)}" data-t-i="${i}" data-t-col="${esc(c.key)}">`)
            .join('')}<button type="button" class="t-x" aria-label="Remove row ${i + 1}" data-t-del="${esc(f.key)}" data-t-i="${i}">✕</button></div>`,
        )
        .join('');
      return `<div class="field"><div class="label">${esc(f.label)}</div>${hint}${head}${body}${errHtml}
        <button type="button" class="ghost" data-t-add="${esc(f.key)}">+ Add a row</button>
        <details class="t-paste"><summary>Paste rows (from Excel or a list)</summary>
          <p class="small muted">One row a line: ${cols.map((c) => esc(c.label)).join(', ')}; columns split by a tab or a semicolon.</p>
          <textarea class="input" rows="6" aria-label="Rows to paste" data-t-paste-text="${esc(f.key)}"></textarea>
          <button type="button" class="ghost" data-t-paste="${esc(f.key)}">Replace the rows</button></details></div>`;
    }
    if (f.kind === 'flows' || f.kind === 'dated_flows') {
      const dated = f.kind === 'dated_flows';
      const rows = vals[f.key] || [];
      const body = rows
        .map(
          (r, i) => `<div class="t-row">
          <span class="t-cf">${dated ? i + 1 : `CF${i}`}</span>
          ${dated ? `<input class="input" type="date" aria-label="Row ${i + 1} date" value="${esc(r.date || '')}" data-t-row="${esc(f.key)}" data-t-i="${i}" data-t-col="date">` : ''}
          <input class="input num" inputmode="decimal" autocomplete="off" aria-label="${dated ? `Row ${i + 1}` : `CF${i}`} amount" value="${esc(r.amount)}" data-t-row="${esc(f.key)}" data-t-i="${i}" data-t-col="amount">
          ${dated ? '' : `<input class="input num t-count" inputmode="numeric" aria-label="CF${i} count" value="${esc(i === 0 ? '1' : r.count || '1')}" ${i === 0 ? 'disabled' : ''} data-t-row="${esc(f.key)}" data-t-i="${i}" data-t-col="count">`}
          <button type="button" class="t-x" aria-label="Remove row ${i + 1}" ${rows.length <= 2 ? 'disabled' : ''} data-t-del="${esc(f.key)}" data-t-i="${i}">✕</button>
        </div>`,
        )
        .join('');
      return `<div class="field"><div class="label">${esc(f.label)}${dated ? '' : ' <span class="muted small">(amount, times)</span>'}</div>${hint}${body}${errHtml}
        <button type="button" class="ghost" data-t-add="${esc(f.key)}">+ Add a row</button></div>`;
    }
    if (solving === f.key) {
      const a = T.result && T.result.ok && T.result.value.answer.key === f.key ? fmt(T.result.value.answer) : '…';
      return `<div class="field"><label class="label" for="${id}">${esc(f.label)}: the answer</label><input id="${id}" class="input num t-solved" readonly value="${esc(a)}" data-t-solved="${esc(f.key)}"></div>`;
    }
    if (f.kind === 'choice')
      return `<div class="field"><label class="label" for="${id}">${esc(f.label)}</label><select id="${id}" class="select" data-t-choice="${esc(f.key)}">${f.options
        .map((o) => `<option value="${esc(o.value)}"${String(vals[f.key] ?? f.default) === o.value ? ' selected' : ''}>${esc(o.label)}</option>`)
        .join('')}</select>${hint}${errHtml}</div>`;
    const unit = f.kind === 'percent' ? '%' : f.kind === 'money' ? '₹' : '';
    return `<div class="field"><label class="label" for="${id}">${esc(f.label)}${f.optional ? ' <span class="muted small">(optional)</span>' : ''}</label>
      <div class="t-input">${unit === '₹' ? '<span class="t-pre">₹</span>' : ''}<input id="${id}" class="input${f.kind === 'date' ? '' : ' num'}${unit === '₹' ? ' t-pad-l' : ''}${unit === '%' ? ' t-pad-r' : ''}" ${f.kind === 'date' ? 'type="date"' : 'inputmode="decimal" autocomplete="off"'} value="${esc(vals[f.key] ?? '')}" data-t-field="${esc(f.key)}" aria-invalid="${!!err}">${unit === '%' ? '<span class="t-post">%</span>' : ''}</div>${hint}${errHtml}</div>`;
  }

  function resultHtml() {
    const r = T.result;
    if (!r) return '';
    if (!r.ok) return r.field ? '<p class="muted small">Fix the box marked above to see the answer.</p>' : `<p class="t-err" role="alert">${esc(r.message)}</p>`;
    const v = r.value;
    const store = (x) => (NUMERIC.test(x.exact) ? `<button type="button" class="t-sto" aria-label="Store ${esc(x.label)} in a register" data-t-store="${esc(x.exact)}">M+</button>` : '');
    let html = `<section class="card t-answer" aria-label="Answer"><div class="small muted">${esc(v.answer.label)}</div>
      <div class="t-big"><span class="num">${esc(fmt(v.answer))}</span>${store(v.answer)}</div>${v.answer.note ? `<p class="small muted">${esc(v.answer.note)}</p>` : ''}`;
    if (v.values.length)
      html += `<dl class="t-values">${v.values
        .map((x) => `<div><dt>${esc(x.label)}${x.note ? `<span class="small muted"> ${esc(x.note)}</span>` : ''}</dt><dd><span class="num">${esc(fmt(x))}</span>${store(x)}</dd></div>`)
        .join('')}</dl>`;
    html += '</section>';
    if (v.warnings.length) html += `<section class="card t-warn">${v.warnings.map((w) => `<p>⚠ ${esc(w)}</p>`).join('')}</section>`;
    if (v.steps.length) html += `<details class="card"><summary>How it is worked out</summary><ul class="t-steps">${v.steps.map((s) => `<li>${esc(s)}</li>`).join('')}</ul></details>`;
    for (const t of v.tables) {
      const left = (u) => u === 'text' || u === 'date';
      html += `<details class="card"><summary>${esc(t.title)} (${t.rows.length} rows)</summary><div class="t-scroll"><table class="t-table"><thead><tr>${t.columns
        .map((c) => `<th class="${left(c.unit) ? '' : 'r'}">${esc(c.label)}</th>`)
        .join('')}</tr></thead><tbody>${t.rows
        .map((row) => `<tr>${row.map((cell, j) => `<td class="${left(t.columns[j].unit) ? '' : 'r num'}">${esc(fmt({ value: cell, unit: t.columns[j].unit }))}</td>`).join('')}</tr>`)
        .join('')}</tbody></table></div></details>`;
    }
    return html;
  }

  function sheetsHtml(c) {
    const list = T.sheets[c.key] || [];
    return `<div class="t-sheets">
      <select class="select" aria-label="Saved on this phone" data-t-open-sheet><option value="">${list.length ? 'Open a saved one…' : 'Nothing saved yet'}</option>${list
        .map((s, i) => `<option value="${i}">${esc(s.name)}</option>`)
        .join('')}</select>
      <button type="button" class="ghost" data-t-save-sheet>Save as…</button>
      ${list.length ? '<button type="button" class="ghost" data-t-del-sheet>Delete one…</button>' : ''}
      <button type="button" class="ghost" data-t-reset>Start again</button>
    </div>`;
  }

  function keypadHtml() {
    const keys = ['7', '8', '9', '÷', '(', '4', '5', '6', '×', ')', '1', '2', '3', '−', '^', '0', '.', '%', '+', 'sqrt('];
    const regs = Array.from({ length: 10 }, (_, i) => `m${i}`);
    return `<section class="card" aria-label="Keypad">
      <input class="input num t-expr" aria-label="Expression" value="${esc(T.expr)}" placeholder="0" data-t-expr autocomplete="off">
      ${T.exprError ? `<p class="t-err" role="alert">${esc(T.exprError)}</p>` : `<p class="small muted r">ANS ${esc(groupDecimal(T.registers.ans || '0'))}</p>`}
      <div class="t-keys">${keys.map((k) => `<button type="button" data-t-key-in="${esc(k)}">${esc(k === 'sqrt(' ? '√' : k === '^' ? 'xʸ' : k)}</button>`).join('')}
        <button type="button" data-t-clear>C</button><button type="button" data-t-back aria-label="Delete one character">⌫</button><button type="button" data-t-key-in="ANS">ANS</button><button type="button" class="t-eq" data-t-eq>=</button></div>
      <div class="t-fns">${['ln(', 'log(', 'exp(', 'abs(', 'round(', 'fact(', 'comb(', 'perm(', 'pi', 'e'].map((f) => `<button type="button" data-t-key-in="${f}">${f.replace('(', '')}</button>`).join('')}</div>
      <div class="label">Registers <span class="small muted">tap to use; M+ beside an answer stores it</span></div>
      <div class="t-regs">${regs.map((m) => `<button type="button" data-t-key-in="${m.toUpperCase()}" aria-label="${m.toUpperCase()}: ${esc(T.registers[m] || 'empty')}"><b>${m.toUpperCase()}</b> <span class="num">${esc(T.registers[m] ? groupDecimal(T.registers[m]) : '·')}</span></button>`).join('')}</div>
      <div class="label">Tape ${T.tape.length ? '<button type="button" class="link" data-t-clear-tape>clear</button>' : ''}</div>
      ${T.tape.length ? `<ol class="t-tape">${[...T.tape].reverse().slice(0, 50).map((t) => `<li><button type="button" data-t-key-in="${esc(t.value)}"><span class="small muted">${esc(t.expr)}</span><br><span class="num">= ${esc(groupDecimal(t.value))}</span></button></li>`).join('')}</ol>` : '<p class="small muted">Each calculation is listed here.</p>'}
    </section>`;
  }

  function calcHtml() {
    const c = calcDef();
    const vals = values(c);
    const solveField = c.fields.find((f) => f.kind === 'solve');
    const solving = solveField ? String(vals[solveField.key] ?? solveField.default) : null;
    const options = T.catalogue.families
      .map((fam) => `<optgroup label="${esc(fam.title)}">${fam.calculators.map((x) => `<option value="${esc(x.key)}"${x.key === c.key ? ' selected' : ''}>${esc(x.title)}</option>`).join('')}</optgroup>`)
      .join('');
    return `<section class="card">
        <label class="label" for="t-calc">Calculator</label>
        <select id="t-calc" class="select" data-t-calc>${options}</select>
        <p class="small muted">${esc(c.description)}</p>
        ${sheetsHtml(c)}
      </section>
      <section class="card"><form data-t-form onsubmit="return false">${c.fields
        .filter((f) => isShown(f, vals, c.fields))
        .map((f) => fieldHtml(c, f, vals, solving))
        .join('')}
        <p class="small muted">Amounts take 1,25,000, 2.5L or 1.2cr. Type M0 to M9 or ANS to use a register.</p></form></section>
      <button type="button" class="ghost t-padbtn" aria-pressed="${T.keypad}" data-t-keypad>${T.keypad ? 'Hide keypad' : 'Keypad, registers and tape'}</button>
      ${T.keypad ? keypadHtml() : ''}
      <div id="t-result">${resultHtml()}</div>`;
  }

  const MON = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
  /** 2026-04-01, 01-04-2026, 01/04/2026 or 01-Apr-2026 -> 2026-04-01; null if not a date. */
  function toIsoDate(text) {
    const t = text.trim();
    const iso = (y, m, d) => (+m >= 1 && +m <= 12 && +d >= 1 && +d <= 31 ? `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}` : null);
    let m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(t);
    if (m) return iso(m[1], m[2], m[3]);
    m = /^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$/.exec(t);
    if (m) return iso(m[3], m[2], m[1]);
    m = /^(\d{1,2})[-/ ]([a-z]{3})[a-z]*[-/ ,]+(\d{4})$/i.exec(t);
    if (m && MON.indexOf(m[2].toLowerCase()) >= 0) return iso(m[3], MON.indexOf(m[2].toLowerCase()) + 1, m[1]);
    return null;
  }

  /** Rows pasted for a table: cells in column order, dates in any common style; a heading row is skipped. */
  function parsePastedTable(text, columns) {
    const rows = [];
    for (const line of text.split(/\r?\n/)) {
      if (!line.trim()) continue;
      const cells = line.split(/\t|;|\s{2,}/).map((c) => c.trim());
      const row = {};
      let bad = false;
      columns.forEach((c, i) => {
        const cell = cells[i] || '';
        if (c.kind === 'date') {
          const d = toIsoDate(cell);
          if (cell && !d) bad = true;
          row[c.key] = d || '';
        } else row[c.key] = cell.replace(/%$/, '');
      });
      const header = columns.some((c, i) => c.kind !== 'text' && c.kind !== 'date' && /[a-z]{3}/i.test(cells[i] || ''));
      if (!bad && !header) rows.push(row);
    }
    return rows;
  }

  // ---- tax --------------------------------------------------------------------------------------------------

  function taxRules() {
    const fromList = window.cashLogTaxRules ? window.cashLogTaxRules() : null;
    return fromList && fromList.length ? { sets: fromList, source: 'kuberlekha' } : { sets: T.taxDefaults || [], source: 'built-in' };
  }

  function taxHtml() {
    const { sets, source } = taxRules();
    if (!sets.length) return '<section class="card"><p>No tax rates.</p></section>';
    const rules = sets.find((r) => r.fy === T.taxFy) || sets[sets.length - 1];
    T.taxFy = rules.fy;
    const typed = T.taxAmounts[rules.fy] || {};
    const groups = new Map();
    for (const k of rules.kinds) {
      if (!groups.has(k.group || 'Other')) groups.set(k.group || 'Other', []);
      groups.get(k.group || 'Other').push(k);
    }
    return `<section class="card">
        <label class="label" for="t-fy">Financial year</label>
        <select id="t-fy" class="select" data-t-fy>${sets.map((r) => `<option value="${esc(r.fy)}"${r.fy === rules.fy ? ' selected' : ''}>FY ${esc(r.fy)}</option>`).join('')}</select>
        <p class="small muted">${esc(rules.name)}. ${source === 'kuberlekha' ? 'Rates from your Kuberlekha list.' : 'Built-in rates; load the list from Kuberlekha (Settings) to use the rates you keep there.'} For a resident individual. Type each income net of its own expenses and losses.</p>
        <button type="button" class="ghost" data-t-tax-clear>Clear amounts</button>
      </section>
      <section class="card"><form data-t-taxform onsubmit="return false">${[...groups.entries()]
        .map(([g, kinds]) => `<div class="label t-group">${esc(g)}</div>${kinds
          .map((k) => {
            const id = `t-tax-${k.key}`;
            const err = T.result && !T.result.ok && T.result.field === k.key ? `<p class="t-err" role="alert">${esc(T.result.message)}</p>` : '';
            const hint = [k.treatment === 'special' ? `${pct(k.rate_bp)} flat` : 'Slab rates', k.standard_deduction ? `Standard deduction ${inrShort(rules.standard_deduction_paise)}` : '', k.exemption_paise ? `First ${inrShort(k.exemption_paise)} exempt` : '']
              .filter(Boolean)
              .join('. ');
            return `<div class="field"><label class="label" for="${id}">${esc(k.label)}</label><div class="t-input"><span class="t-pre">₹</span><input id="${id}" class="input num t-pad-l" inputmode="decimal" autocomplete="off" placeholder="0" value="${esc(typed[k.key] || '')}" data-t-tax="${esc(k.key)}"></div><p class="small muted">${esc(hint)}</p>${err}</div>`;
          })
          .join('')}`)
        .join('')}</form></section>
      <div id="t-result">${taxResultHtml(rules)}</div>`;
  }

  function computeTax() {
    const { sets } = taxRules();
    const rules = sets.find((r) => r.fy === T.taxFy) || sets[sets.length - 1];
    T.result = call('tax_text_json', JSON.stringify(rules), JSON.stringify(T.taxAmounts[rules.fy] || {}));
  }

  function taxResultHtml(rules) {
    const r = T.result;
    if (!r) return '';
    if (!r.ok) return r.field ? '<p class="muted small">Fix the amount marked above.</p>' : `<p class="t-err" role="alert">${esc(r.message)}</p>`;
    const t = r.value;
    const row = (label, p, strong, minus) => `<div class="${strong ? 'strong' : ''}"><dt>${esc(label)}</dt><dd class="num">${minus && p ? '− ' : ''}${inrPaise(p)}</dd></div>`;
    const deductions = t.kinds.reduce((s, k) => s + (k.treatment === 'slab' ? k.deduction_paise : 0), 0);
    const special = t.kinds.filter((k) => k.treatment === 'special' && k.amount_paise);
    let html = `<section class="card t-answer" aria-label="Tax payable"><div class="small muted">Tax payable for FY ${esc(t.fy)}</div>
      <div class="t-big"><span class="num">${inrPaise(t.rounded_tax_paise)}</span></div>
      <p class="small muted">Effective rate ${pct(t.effective_rate_bp)} of gross income</p>
      <dl class="t-values">${row('Gross income', t.gross_paise)}${deductions ? row('Standard deduction', deductions, false, true) : ''}${row('Total income', t.total_income_paise, true)}</dl></section>`;
    html += `<section class="card"><div class="label">Slab-rate income: ${inrPaise(t.slab_income_paise)}</div><div class="t-scroll"><table class="t-table"><thead><tr><th>Slab</th><th class="r">Rate</th><th class="r">Income</th><th class="r">Tax</th></tr></thead><tbody>${t.slabs
      .map((s) => `<tr class="${s.income_paise ? '' : 'muted'}"><td class="w">${s.upto_paise === null ? `Above ${inrShort(s.from_paise)}` : `${inrShort(s.from_paise)} – ${inrShort(s.upto_paise)}`}</td><td class="r num">${pct(s.rate_bp)}</td><td class="r num">${inrPaise(s.income_paise)}</td><td class="r num">${inrPaise(s.tax_paise)}</td></tr>`)
      .join('')}</tbody></table></div>`;
    if (special.length)
      html += `<div class="label">Special-rate income</div><div class="t-scroll"><table class="t-table"><thead><tr><th>Income</th><th class="r">Taxable</th><th class="r">Rate</th><th class="r">Tax</th></tr></thead><tbody>${special
        .map((k) => `<tr><td class="w">${esc(k.label)}${k.deduction_paise ? `<br><span class="small muted">${inrPaise(k.deduction_paise)} exempt</span>` : ''}${k.basic_exemption_used_paise ? `<br><span class="small muted">${inrPaise(k.basic_exemption_used_paise)} covered by unused basic exemption</span>` : ''}</td><td class="r num">${inrPaise(k.taxable_paise)}</td><td class="r num">${pct(k.rate_bp || 0)}</td><td class="r num">${inrPaise(k.tax_paise)}</td></tr>`)
        .join('')}</tbody></table></div>`;
    html += `<dl class="t-values">${row('Tax on slab income', t.slab_tax_paise)}${t.special_tax_paise ? row('Tax on special-rate income', t.special_tax_paise) : ''}${t.rebate_paise ? row('Rebate under section 87A', t.rebate_paise, false, true) : ''}${row('Tax after rebate', t.tax_after_rebate_paise, true)}${t.surcharge_rate_bp ? row(`Surcharge (${pct(t.surcharge_rate_bp)}, capped where the law caps it)`, t.surcharge_paise + t.surcharge_relief_paise) : ''}${t.surcharge_relief_paise ? row('Marginal relief on surcharge', t.surcharge_relief_paise, false, true) : ''}${row(`Health and education cess (${pct(rules.cess_bp)})`, t.cess_paise)}${row('Total tax', t.total_tax_paise, true)}${row('Rounded to the nearest ₹10', t.rounded_tax_paise, true)}</dl>`;
    if (t.notes.length) html += `<ul class="small muted">${t.notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>`;
    html += '<p class="small muted">An estimate before TDS and advance tax already paid. Not tax advice.</p></section>';
    return html;
  }

  // ---- drawing and events ----------------------------------------------------------------------------------

  function draw() {
    if (!T.root) return;
    if (!T.py) {
      T.root.innerHTML = T.loadError
        ? `<section class="card"><h2>The calculator could not start</h2><p>${esc(T.loadError)}</p><p class="small muted">Open Cash Log once with a signal so it can keep the calculator on this phone; after that it works offline.</p><button type="button" class="primary" data-t-retry>Try again</button></section>`
        : `<section class="card"><h2>Starting the calculator…</h2><p class="small muted">Python is loading on this phone. The first time takes a few seconds; after that it opens without a signal.</p>${
            T.slow ? '<p>Still loading. With a weak signal the first start can take a minute or two.</p><button type="button" class="ghost" data-t-retry>Try again</button>' : ''
          }</section>`;
      return;
    }
    try {
      if (T.view === 'calc') {
        compute();
        T.root.innerHTML = calcHtml();
      } else {
        computeTax();
        T.root.innerHTML = taxHtml();
      }
    } catch (err) {
      T.root.innerHTML = `<section class="card"><p class="t-err">${esc(err.message || err)}</p></section>`;
    }
  }

  /** After typing: work out the answer again and refresh only the answer and error marks, keeping focus. */
  function refresh() {
    clearTimeout(T.timer);
    T.timer = setTimeout(() => {
      const hadFieldError = T.result && !T.result.ok && T.result.field;
      if (T.view === 'calc') compute();
      else computeTax();
      const fieldError = T.result && !T.result.ok && T.result.field;
      if (hadFieldError || fieldError) {
        // An error mark appears or goes away: redraw, then put the cursor back where it was.
        const active = document.activeElement;
        const sel = active && active.id ? { id: active.id, start: active.selectionStart, end: active.selectionEnd } : null;
        const scroll = window.scrollY;
        T.root.innerHTML = T.view === 'calc' ? calcHtml() : taxHtml();
        if (sel) {
          const el = document.getElementById(sel.id);
          if (el) {
            el.focus({ preventScroll: true });
            try {
              el.setSelectionRange(sel.start, sel.end);
            } catch {
              /* date inputs have no selection */
            }
          }
        }
        window.scrollTo(0, scroll);
        return;
      }
      const box = document.getElementById('t-result');
      if (box) {
        if (T.view === 'calc') box.innerHTML = resultHtml();
        else {
          const { sets } = taxRules();
          box.innerHTML = taxResultHtml(sets.find((r) => r.fy === T.taxFy) || sets[sets.length - 1]);
        }
      }
      for (const el of T.root.querySelectorAll('[data-t-solved]')) {
        const r = T.result;
        el.value = r && r.ok && r.value.answer.key === el.dataset.tSolved ? fmt(r.value.answer) : '…';
      }
    }, 120);
  }

  function evaluateKeypad() {
    if (!T.expr.trim()) return;
    const r = call('evaluate_json', T.expr, JSON.stringify(T.registers));
    if (r.ok) {
      T.tape.push({ expr: T.expr, value: r.value });
      T.registers.ans = r.value;
      T.expr = r.value;
      T.exprError = null;
    } else T.exprError = r.message;
    persist();
    draw();
  }

  function insertKey(text) {
    const el = T.root.querySelector('[data-t-expr]');
    const start = el ? el.selectionStart ?? T.expr.length : T.expr.length;
    const end = el ? el.selectionEnd ?? T.expr.length : T.expr.length;
    T.expr = T.expr.slice(0, start) + text + T.expr.slice(end);
    T.exprError = null;
    draw();
    const again = T.root.querySelector('[data-t-expr]');
    if (again) again.setSelectionRange(start + text.length, start + text.length);
  }

  function onClick(e) {
    const el = e.target.closest('button, [data-t-solve]');
    if (!el || !T.root.contains(el)) return;
    const d = el.dataset;
    const c = T.py && T.view === 'calc' ? calcDef() : null;
    if ('tRetry' in d) {
      if (T.loading && !T.py) location.reload(); // a stuck download: start afresh
      return start();
    }
    if (d.tSolve !== undefined && c) {
      values(c)[d.tKey] = d.tSolve;
      persist();
      return draw();
    }
    if (d.tPaste && c) {
      const box = T.root.querySelector(`[data-t-paste-text="${d.tPaste}"]`);
      const f = c.fields.find((x) => x.key === d.tPaste);
      const rows = box && f ? parsePastedTable(box.value, f.columns || []) : [];
      if (!rows.length) {
        if (window.toast) window.toast('No rows could be read.');
        return;
      }
      values(c)[d.tPaste] = rows;
      persist();
      return draw();
    }
    if (d.tAdd && c) {
      const rows = values(c)[d.tAdd];
      const f = c.fields.find((x) => x.key === d.tAdd);
      if (f && f.kind === 'table') rows.push(Object.fromEntries((f.columns || []).map((col) => [col.key, ''])));
      else rows.push(rows[0] && 'date' in rows[0] ? { date: rows[rows.length - 1].date, amount: '' } : { amount: '', count: '1' });
      persist();
      return draw();
    }
    if (d.tDel && c) {
      values(c)[d.tDel].splice(Number(d.tI), 1);
      persist();
      return draw();
    }
    if ('tKeypad' in d) {
      T.keypad = !T.keypad;
      return draw();
    }
    if (d.tKeyIn !== undefined) return insertKey(d.tKeyIn);
    if ('tEq' in d) return evaluateKeypad();
    if ('tClear' in d) {
      T.expr = '';
      T.exprError = null;
      return draw();
    }
    if ('tBack' in d) {
      T.expr = T.expr.slice(0, -1);
      return draw();
    }
    if ('tClearTape' in d) {
      T.tape = [];
      persist();
      return draw();
    }
    if (d.tStore !== undefined) {
      const choice = prompt(`Store ${d.tStore} in which register? Type 0 to 9.`, '0');
      if (choice !== null && /^\s*[0-9]\s*$/.test(choice)) {
        T.registers[`m${choice.trim()}`] = d.tStore;
        persist();
        if (T.keypad) draw();
        if (window.toast) window.toast(`Stored in M${choice.trim()}.`);
      }
      return;
    }
    if ('tSaveSheet' in d && c) {
      const name = (prompt('Name for these inputs (kept on this phone):', '') || '').trim();
      if (!name) return;
      const list = (T.sheets[c.key] = (T.sheets[c.key] || []).filter((s) => s.name !== name));
      list.push({ name, inputs: JSON.parse(JSON.stringify(values(c))) });
      list.sort((a, b) => a.name.localeCompare(b.name));
      persist();
      return draw();
    }
    if ('tDelSheet' in d && c) {
      const list = T.sheets[c.key] || [];
      const name = prompt(`Delete which one? Type its name:\n${list.map((s) => s.name).join('\n')}`, '');
      if (name && list.some((s) => s.name === name.trim())) {
        T.sheets[c.key] = list.filter((s) => s.name !== name.trim());
        persist();
        draw();
      }
      return;
    }
    if ('tReset' in d && c) {
      T.inputs[c.key] = defaultsOf(c);
      persist();
      return draw();
    }
    if ('tTaxClear' in d) {
      T.taxAmounts[T.taxFy] = {};
      persist();
      return draw();
    }
  }

  function onInput(e) {
    const el = e.target;
    if (!T.root.contains(el) || !T.py) return;
    const d = el.dataset;
    if (d.tExpr !== undefined) {
      T.expr = el.value;
      return;
    }
    if (T.view === 'tax' && d.tTax) {
      (T.taxAmounts[T.taxFy] = T.taxAmounts[T.taxFy] || {})[d.tTax] = el.value;
      persist();
      return refresh();
    }
    const c = calcDef();
    if (d.tField) values(c)[d.tField] = el.value;
    else if (d.tRow) values(c)[d.tRow][Number(d.tI)][d.tCol] = el.value;
    else return;
    persist();
    refresh();
  }

  function onChange(e) {
    const el = e.target;
    if (!T.root.contains(el) || !T.py) return;
    const d = el.dataset;
    if (d.tCalc !== undefined) {
      T.current = el.value;
      T.result = null;
      persist();
      return draw();
    }
    if (d.tFy !== undefined) {
      T.taxFy = el.value;
      persist();
      return draw();
    }
    if (d.tChoice && T.view === 'calc') {
      values(calcDef())[d.tChoice] = el.value;
      persist();
      return draw();
    }
    if (d.tOpenSheet !== undefined && el.value !== '') {
      const c = calcDef();
      const s = (T.sheets[c.key] || [])[Number(el.value)];
      if (s) T.inputs[c.key] = JSON.parse(JSON.stringify(s.inputs));
      persist();
      return draw();
    }
    if (d.tRow || d.tField) onInput(e); // date pickers report on change
  }

  function onKey(e) {
    if (e.key === 'Enter' && e.target.dataset && e.target.dataset.tExpr !== undefined) {
      e.preventDefault();
      T.expr = e.target.value;
      evaluateKeypad();
    }
  }

  function start() {
    T.loadError = null;
    T.slow = false;
    clearTimeout(T.slowTimer);
    if (!T.py)
      T.slowTimer = setTimeout(() => {
        T.slow = true;
        if (!T.py) draw();
      }, 45_000);
    draw();
    python()
      .then(() => draw())
      .catch(() => draw());
  }

  /** Draws the Calculator ('calc') or Tax ('tax') tab into `root`. */
  function mount(view, root) {
    if (T.root !== root) {
      root.addEventListener('click', onClick);
      root.addEventListener('input', onInput);
      root.addEventListener('change', onChange);
      root.addEventListener('keydown', onKey);
    }
    T.view = view;
    T.root = root;
    T.result = null;
    start();
  }

  return { mount, python };
})();
window.CashTools = CashTools;
