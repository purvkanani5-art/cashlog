/* Cash Log: cash spending kept on this phone, exported as a CSV that Kuberlekha imports like a bank statement
   (Kuberlekha docs/decisions.md #117). Nothing is sent anywhere: the only way out is the Export button.

   Money is integer paise everywhere; rupee text is converted exactly, never through floating point. */
'use strict';

const APP_VERSION = '1.0.0';
const KEYS = { entries: 'cl.entries', lists: 'cl.lists', settings: 'cl.settings', lastExport: 'cl.lastExport' };
const LOCK_AFTER_MS = 2 * 60 * 1000; // ask for the PIN again after two minutes away
const COLUMNS = ['cashlog_id', 'date', 'type', 'amount', 'category', 'category_id', 'person', 'person_id', 'my_share', 'shares', 'note'];
// Kuberlekha's own expense names, until its list is loaded.
const DEFAULT_CATEGORIES = ['Food and Dining', 'Groceries', 'Transport and Fuel', 'Shopping', 'Health', 'Entertainment', 'Family and Gifts', 'Other Expenses'];

// ---- storage ------------------------------------------------------------------------------------------------

function load(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function save(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    toast('Could not save on this phone. Free some space and try again.');
    return false;
  }
}

const state = {
  entries: load(KEYS.entries, []),
  lists: load(KEYS.lists, null) || { entity: null, made: null, categories: DEFAULT_CATEGORIES.map((name) => ({ id: null, name, group: null })), people: [] },
  settings: load(KEYS.settings, {}),
  lastExport: load(KEYS.lastExport, null),
  view: 'add',
  form: null,
  editing: null, // id of the entry being changed
  error: null,
  showAll: false,
  locked: false,
  pin: '',
  hiddenAt: 0,
};

function saveEntries() {
  return save(KEYS.entries, state.entries);
}

// ---- money and dates ----------------------------------------------------------------------------------------

/** '1,250.5' -> 125050; anything that is not an exact rupee amount -> null. */
function toPaise(text) {
  const s = String(text ?? '').replace(/[₹,\s]/g, '');
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return null;
  const [r, p = ''] = s.split('.');
  return Number(r) * 100 + Number((p + '00').slice(0, 2));
}

/** 125050 -> '1250.50' (the CSV's form). */
function rupees(paise) {
  return `${Math.floor(paise / 100)}.${String(paise % 100).padStart(2, '0')}`;
}

/** 12345650 -> '₹1,23,456.50' (Indian grouping); whole rupees drop the paise. */
function inr(paise) {
  const whole = String(Math.floor(Math.abs(paise) / 100));
  const grouped = whole.length > 3 ? whole.slice(0, -3).replace(/\B(?=(\d{2})+$)/g, ',') + ',' + whole.slice(-3) : whole;
  const p = Math.abs(paise) % 100;
  return `${paise < 0 ? '−' : ''}₹${grouped}${p ? '.' + String(p).padStart(2, '0') : ''}`;
}

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function niceDate(iso) {
  const [y, m, d] = iso.split('-');
  return `${d}-${MONTHS[Number(m) - 1]}-${y}`;
}

function dayLabel(iso) {
  const today = todayISO();
  const y = new Date();
  y.setDate(y.getDate() - 1);
  const yesterday = `${y.getFullYear()}-${String(y.getMonth() + 1).padStart(2, '0')}-${String(y.getDate()).padStart(2, '0')}`;
  if (iso === today) return 'Today';
  if (iso === yesterday) return 'Yesterday';
  return niceDate(iso);
}

function newId() {
  const rand = Math.random().toString(36).slice(2, 6).padEnd(4, '0');
  return `CL-${(Date.now().toString(36) + rand).toUpperCase()}`;
}

function esc(text) {
  return String(text ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

function key(name) {
  return String(name || '').trim().toLowerCase().replace(/\s+/g, ' ');
}

// ---- the form -----------------------------------------------------------------------------------------------

function blankForm(type = 'spent') {
  return { type, amount: '', category: null, note: '', date: todayISO(), split: false, people: [], mode: 'equal', includeMe: true, person: null };
}

function form() {
  if (!state.form) state.form = blankForm();
  return state.form;
}

/** The owner's part and each person's part of the spend, or a problem in words. */
function splitOf(f) {
  const total = toPaise(f.amount);
  if (total === null || total === 0) return { problem: 'Enter the amount.' };
  if (!f.split || !f.people.length) return { mine: total, shares: [] };
  if (f.mode === 'equal') {
    const n = f.people.length + (f.includeMe ? 1 : 0);
    const base = Math.floor(total / n);
    let left = total - base * n; // the odd paise: the owner's, or the first people's when the owner has no part
    const shares = f.people.map((p) => ({ id: p.id, name: p.name, amountPaise: base }));
    let mine = f.includeMe ? base : 0;
    if (f.includeMe) mine += left;
    else for (let i = 0; left > 0; i++, left--) shares[i % shares.length].amountPaise += 1;
    return { mine, shares };
  }
  const shares = [];
  for (const p of f.people) {
    const a = toPaise(p.amount || '0');
    if (a === null) return { problem: `${p.name}'s share is not an amount.` };
    shares.push({ id: p.id, name: p.name, amountPaise: a });
  }
  const mine = total - shares.reduce((s, x) => s + x.amountPaise, 0);
  if (mine < 0) return { problem: `The shares are ${inr(-mine)} more than the amount.` };
  return { mine, shares: shares.filter((x) => x.amountPaise > 0) };
}

function entryFromForm(f) {
  const total = toPaise(f.amount);
  if (total === null || total === 0) return { problem: 'Enter the amount.' };
  if (!/^\d{4}-\d{2}-\d{2}$/.test(f.date)) return { problem: 'Choose the date.' };
  if (f.date > todayISO()) return { problem: 'The date is in the future.' };
  const base = { date: f.date, amountPaise: total, note: f.note.trim() };
  if (f.type === 'received') {
    if (!f.person) return { problem: 'Choose who paid you.' };
    return { entry: { ...base, type: 'received', person: f.person, category: null, mySharePaise: 0, shares: [] } };
  }
  const s = splitOf(f);
  if (s.problem) return { problem: s.problem };
  if (f.split && !s.shares.length) return { problem: 'Choose who shared it, or turn off Split.' };
  if (s.mine > 0 && !f.category) return { problem: 'Choose a category.' };
  return { entry: { ...base, type: 'spent', category: s.mine > 0 ? f.category : null, person: null, mySharePaise: s.mine, shares: s.shares } };
}

function formFromEntry(e) {
  const f = blankForm(e.type);
  f.amount = rupees(e.amountPaise).replace(/\.00$/, '');
  f.date = e.date;
  f.note = e.note || '';
  f.category = e.category;
  f.person = e.person;
  if (e.shares.length) {
    f.split = true;
    f.mode = 'amounts';
    f.people = e.shares.map((s) => ({ id: s.id, name: s.name, amount: rupees(s.amountPaise).replace(/\.00$/, '') }));
  }
  return f;
}

// ---- lists --------------------------------------------------------------------------------------------------

function categories() {
  return state.lists.categories;
}

function people() {
  return state.lists.people;
}

/** Most used in the last 90 days first, then the rest in list order. */
function byUse(items, pick) {
  const since = new Date();
  since.setDate(since.getDate() - 90);
  const from = since.toISOString().slice(0, 10);
  const counts = new Map();
  for (const e of state.entries) if (e.date >= from) for (const x of pick(e)) counts.set(key(x.name), (counts.get(key(x.name)) || 0) + 1);
  return [...items].sort((a, b) => (counts.get(key(b.name)) || 0) - (counts.get(key(a.name)) || 0));
}

function topCategories() {
  return byUse(categories(), (e) => (e.category ? [e.category] : [])).slice(0, 6);
}

function topPeople() {
  return byUse(people(), (e) => [...e.shares, ...(e.person ? [e.person] : [])]).slice(0, 8);
}

function findCategory(name) {
  return categories().find((c) => key(c.name) === key(name));
}

function findPerson(name) {
  return people().find((p) => key(p.name) === key(name));
}

function addName(kind, name) {
  name = String(name || '').trim().replace(/\s+/g, ' ').slice(0, 120);
  if (!name) return null;
  const found = kind === 'category' ? findCategory(name) : findPerson(name);
  if (found) return found;
  const item = kind === 'category' ? { id: null, name, group: null } : { id: null, name };
  state.lists[kind === 'category' ? 'categories' : 'people'].push(item);
  save(KEYS.lists, state.lists);
  return item;
}

function loadList(data) {
  if (!data || data.app !== 'cashlog' || data.version !== 1 || !Array.isArray(data.categories) || !Array.isArray(data.people)) {
    throw new Error('This is not a list file from Kuberlekha.');
  }
  const cats = data.categories.filter((c) => c && c.name).map((c) => ({ id: Number.isInteger(c.id) ? c.id : null, name: String(c.name), group: c.group ? String(c.group) : null }));
  const ppl = data.people.filter((p) => p && p.name).map((p) => ({ id: Number.isInteger(p.id) ? p.id : null, name: String(p.name) }));
  // Names added on the phone stay until Kuberlekha knows them.
  const extraCats = categories().filter((c) => c.id === null && !cats.some((x) => key(x.name) === key(c.name)) && !DEFAULT_CATEGORIES.includes(c.name));
  const extraPeople = people().filter((p) => p.id === null && !ppl.some((x) => key(x.name) === key(p.name)));
  state.lists = { entity: data.entity || null, made: data.made || null, categories: [...cats, ...extraCats], people: [...ppl, ...extraPeople] };
  save(KEYS.lists, state.lists);
  return { categories: cats.length, people: ppl.length };
}

// ---- export -------------------------------------------------------------------------------------------------

function csvCell(value) {
  const s = String(value ?? '');
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function csvOf(entries) {
  const rows = [COLUMNS.join(',')];
  for (const e of entries) {
    const shares = e.shares.length ? JSON.stringify(e.shares.map((s) => (s.id ? { name: s.name, id: s.id, amount: rupees(s.amountPaise) } : { name: s.name, amount: rupees(s.amountPaise) }))) : '';
    rows.push(
      [
        e.id,
        e.date,
        e.type,
        rupees(e.amountPaise),
        e.category ? e.category.name : '',
        e.category && e.category.id ? e.category.id : '',
        e.person ? e.person.name : '',
        e.person && e.person.id ? e.person.id : '',
        e.type === 'spent' ? rupees(e.mySharePaise) : '',
        shares,
        e.note,
      ]
        .map(csvCell)
        .join(','),
    );
  }
  return rows.join('\r\n') + '\r\n';
}

function pending() {
  return state.entries.filter((e) => !e.exportedAt);
}

async function exportEntries(all) {
  const list = (all ? state.entries : pending()).slice().sort((a, b) => (a.date + a.createdAt).localeCompare(b.date + b.createdAt));
  if (!list.length) return toast('Nothing new to export.');
  const name = `cash-${todayISO()}.csv`;
  const file = new File([csvOf(list)], name, { type: 'text/csv' });
  let shared = false;
  if (navigator.canShare && navigator.canShare({ files: [file] })) {
    try {
      await navigator.share({ files: [file], title: name });
      shared = true;
    } catch (err) {
      if (err && err.name === 'AbortError') return; // the owner closed the share sheet: nothing exported
    }
  }
  if (!shared) {
    const url = URL.createObjectURL(file);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }
  const now = new Date().toISOString();
  const marked = list.filter((e) => !e.exportedAt).map((e) => e.id);
  for (const e of list) if (!e.exportedAt) e.exportedAt = now;
  saveEntries();
  state.lastExport = { at: now, ids: marked, count: list.length };
  save(KEYS.lastExport, state.lastExport);
  render();
  toast(`Exported ${list.length} ${list.length === 1 ? 'entry' : 'entries'}. Upload ${name} in Kuberlekha → Import → Cash in Hand.`);
}

function undoExport() {
  const last = state.lastExport;
  if (!last) return;
  const ids = new Set(last.ids);
  for (const e of state.entries) if (ids.has(e.id)) e.exportedAt = null;
  saveEntries();
  state.lastExport = null;
  save(KEYS.lastExport, null);
  render();
  toast('Those entries will go in the next export again.');
}

// ---- PIN ----------------------------------------------------------------------------------------------------

async function pinHash(pin) {
  const data = new TextEncoder().encode(`cashlog:${pin}`);
  const hash = await crypto.subtle.digest('SHA-256', data);
  return [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

function hasPin() {
  return Boolean(state.settings.pinHash);
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) state.hiddenAt = Date.now();
  else if (hasPin() && state.hiddenAt && Date.now() - state.hiddenAt > LOCK_AFTER_MS) {
    state.locked = true;
    state.pin = '';
    render();
  }
});

// ---- rendering ----------------------------------------------------------------------------------------------

const $app = document.getElementById('app');

function render() {
  if (state.locked) {
    $app.innerHTML = lockHtml();
    return;
  }
  $app.innerHTML = headerHtml() + (state.view === 'entries' ? entriesHtml() : state.view === 'settings' ? settingsHtml() : addHtml());
}

function headerHtml() {
  const n = pending().length;
  const tab = (id, label, badge) =>
    `<button class="tab${state.view === id ? ' on' : ''}" data-action="view" data-view="${id}" aria-pressed="${state.view === id}">${label}${badge ? ` <span class="badge">${badge}</span>` : ''}</button>`;
  return `<header class="top">
    <div class="brand"><img src="./icons/icon.svg" alt="" width="28" height="28" /><h1>Cash Log</h1></div>
    <div class="month">${monthLine()}</div>
  </header>
  <nav class="tabs" aria-label="Sections">${tab('add', state.editing ? 'Change' : 'Add')}${tab('entries', 'Entries', n || '')}${tab('settings', 'Settings')}</nav>`;
}

function monthLine() {
  const ym = todayISO().slice(0, 7);
  let spent = 0;
  for (const e of state.entries) if (e.type === 'spent' && e.date.startsWith(ym)) spent += e.mySharePaise;
  return `${MONTHS[Number(ym.slice(5)) - 1]}: ${inr(spent)} your share`;
}

function seg(name, value, options) {
  return `<div class="seg" role="radiogroup">${options
    .map(([v, label]) => `<button type="button" role="radio" aria-checked="${v === value}" class="${v === value ? 'on' : ''}" data-action="${name}" data-value="${v}">${label}</button>`)
    .join('')}</div>`;
}

function chip(label, on, action, attrs = '') {
  return `<button type="button" class="chip${on ? ' on' : ''}" aria-pressed="${on}" data-action="${action}" ${attrs}>${esc(label)}</button>`;
}

function categorySelect(f) {
  const groups = new Map();
  for (const c of categories()) {
    const g = c.group || '';
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(c);
  }
  const opt = (c) => `<option value="${esc(c.name)}"${f.category && key(f.category.name) === key(c.name) ? ' selected' : ''}>${esc(c.name)}</option>`;
  let html = '<option value="">All categories…</option>';
  for (const [g, items] of groups) html += g ? `<optgroup label="${esc(g)}">${items.map(opt).join('')}</optgroup>` : items.map(opt).join('');
  return `<select class="select" data-change="category" aria-label="All categories">${html}<option value="__new">+ New category…</option></select>`;
}

function personSelect(change, label) {
  const opts = people().map((p) => `<option value="${esc(p.name)}">${esc(p.name)}</option>`).join('');
  return `<select class="select" data-change="${change}" aria-label="${label}"><option value="">${label}…</option>${opts}<option value="__new">+ New person…</option></select>`;
}

function addHtml() {
  const f = form();
  const editing = state.editing ? state.entries.find((e) => e.id === state.editing) : null;
  let body = `<section class="card">
    ${seg('type', f.type, [['spent', 'Spent'], ['received', 'Received']])}
    <label class="amount"><span>₹</span><input id="amount" inputmode="decimal" autocomplete="off" placeholder="0" value="${esc(f.amount)}" data-input="amount" aria-label="Amount in rupees" /></label>`;
  if (f.type === 'spent') {
    const top = topCategories();
    const chosenTop = f.category && top.some((c) => key(c.name) === key(f.category.name));
    body += `<div class="field"><div class="label">Category</div>
      <div class="chips">${top.map((c) => chip(c.name, f.category && key(f.category.name) === key(c.name), 'category', `data-value="${esc(c.name)}"`)).join('')}</div>
      ${f.category && !chosenTop ? `<div class="picked">${esc(f.category.name)}</div>` : ''}
      ${categorySelect(f)}</div>`;
  } else {
    const top = topPeople();
    body += `<div class="field"><div class="label">Who paid you</div>
      <div class="chips">${top.map((p) => chip(p.name, f.person && key(f.person.name) === key(p.name), 'person', `data-value="${esc(p.name)}"`)).join('')}</div>
      ${f.person && !top.some((p) => key(p.name) === key(f.person.name)) ? `<div class="picked">${esc(f.person.name)}</div>` : ''}
      ${personSelect('person', 'All people')}</div>`;
  }
  body += `<div class="row2">
      <label class="field"><span class="label">Note</span><input class="input" id="note" maxlength="200" placeholder="${f.type === 'spent' ? 'Lunch, auto, vegetables…' : 'Optional'}" value="${esc(f.note)}" data-input="note" /></label>
      <label class="field date"><span class="label">Date</span><input class="input" id="date" type="date" max="${todayISO()}" value="${esc(f.date)}" data-change="date" /></label>
    </div>`;
  if (f.type === 'spent') body += splitHtml(f);
  body += `<p class="error" id="form-error" role="alert">${esc(state.error || '')}</p>
    <button class="primary" data-action="save">${editing ? 'Save changes' : f.type === 'spent' ? 'Save spend' : 'Save money received'}</button>
    ${editing ? '<button class="ghost" data-action="cancelEdit">Cancel</button>' : ''}
  </section>`;
  return body + recentHtml();
}

function splitHtml(f) {
  let html = `<label class="toggle"><input type="checkbox" ${f.split ? 'checked' : ''} data-change="split" /> <span>Split with others</span></label>`;
  if (!f.split) return html;
  const top = topPeople();
  const chosen = (p) => f.people.some((x) => key(x.name) === key(p.name));
  const others = f.people.filter((p) => !top.some((t) => key(t.name) === key(p.name)));
  html += `<div class="split">
    <div class="label">Who shared it</div>
    <div class="chips">${[...top, ...others].map((p) => chip(p.name, chosen(p), 'sharePerson', `data-value="${esc(p.name)}"`)).join('')}</div>
    ${personSelect('sharePerson', 'Add a person')}
    ${f.people.length ? seg('mode', f.mode, [['equal', 'Equal'], ['amounts', 'Amounts']]) : ''}
    ${f.people.length && f.mode === 'equal' ? `<label class="toggle"><input type="checkbox" ${f.includeMe ? 'checked' : ''} data-change="includeMe" /> <span>Include me</span></label>` : ''}
    ${f.people.length && f.mode === 'amounts' ? f.people.map((p, i) => `<label class="share"><span>${esc(p.name)}</span><input class="input" inputmode="decimal" placeholder="0" value="${esc(p.amount || '')}" data-input="shareAmount" data-index="${i}" aria-label="${esc(p.name)}'s share" /></label>`).join('') : ''}
    <div class="summary" id="split-summary">${splitSummary(f)}</div>
  </div>`;
  return html;
}

function splitSummary(f) {
  if (!f.people.length) return '';
  const s = splitOf(f);
  if (s.problem) return `<span class="muted">${esc(s.problem)}</span>`;
  const parts = [`You ${inr(s.mine)}`, ...s.shares.map((x) => `${esc(x.name)} ${inr(x.amountPaise)}`)];
  return parts.join(' · ') + (s.shares.length ? `<div class="muted small">They owe you ${inr(s.shares.reduce((t, x) => t + x.amountPaise, 0))}</div>` : '');
}

function entryTitle(e) {
  if (e.type === 'received') return `From ${e.person.name}`;
  return e.note || (e.category ? e.category.name : 'Paid for others');
}

function entrySub(e) {
  const bits = [];
  if (e.type === 'received') bits.push('Received' + (e.note ? ` · ${e.note}` : ''));
  else {
    if (e.note && e.category) bits.push(e.category.name);
    if (e.shares.length) bits.push(`split: you ${inr(e.mySharePaise)}, ${e.shares.map((s) => `${s.name} ${inr(s.amountPaise)}`).join(', ')}`);
  }
  return bits.map(esc).join(' · ');
}

function entryRow(e) {
  const sign = e.type === 'received' ? '+' : '−';
  return `<button class="entry" data-action="open" data-id="${e.id}">
    <span class="what"><span class="title">${esc(entryTitle(e))}</span><span class="sub">${entrySub(e)}</span></span>
    <span class="how"><span class="amt ${e.type}">${sign}${inr(e.amountPaise).replace('−', '')}</span><span class="state ${e.exportedAt ? 'done' : 'new'}">${e.exportedAt ? 'Exported' : 'New'}</span></span>
  </button>`;
}

function sorted() {
  return state.entries.slice().sort((a, b) => (b.date + b.createdAt).localeCompare(a.date + a.createdAt));
}

function recentHtml() {
  const list = sorted().slice(0, 5);
  if (!list.length) return '<p class="muted center">Your cash entries appear here.</p>';
  return `<section class="group"><h2>Recent <a href="#" data-action="view" data-view="entries">All ›</a></h2>${list.map(entryRow).join('')}</section>`;
}

function entriesHtml() {
  const n = pending();
  const total = n.reduce((s, e) => s + (e.type === 'spent' ? -e.amountPaise : e.amountPaise), 0);
  let html = `<section class="card export">
    ${n.length ? `<div><b>${n.length} new ${n.length === 1 ? 'entry' : 'entries'}</b> <span class="muted">· ${inr(total)} cash</span></div>
    <button class="primary" data-action="export">Export ${n.length} new</button>` : '<div class="muted">Everything is exported.</div>'}
    ${state.lastExport && state.lastExport.ids.length ? `<p class="small muted">Last export ${niceDate(state.lastExport.at.slice(0, 10))}: ${state.lastExport.count} entries · <a href="#" data-action="undoExport">Undo, export them again</a></p>` : ''}
    <p class="small muted">Save the file to the PC, then in Kuberlekha: Import → Cash in Hand → upload.</p>
  </section>`;
  const list = sorted();
  if (!list.length) return html + '<p class="muted center">No entries yet.</p>';
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - 60);
  const from = cutoff.toISOString().slice(0, 10);
  const shown = state.showAll ? list : list.filter((e) => e.date >= from || !e.exportedAt);
  let day = null;
  html += '<section class="group">';
  for (const e of shown) {
    if (e.date !== day) {
      day = e.date;
      const spent = list.filter((x) => x.date === day && x.type === 'spent').reduce((s, x) => s + x.amountPaise, 0);
      html += `<h3>${dayLabel(day)}<span class="muted">${spent ? inr(spent) + ' spent' : ''}</span></h3>`;
    }
    html += entryRow(e);
  }
  html += '</section>';
  if (shown.length < list.length) html += `<button class="ghost" data-action="showAll">Show ${list.length - shown.length} older entries</button>`;
  return html;
}

function settingsHtml() {
  const L = state.lists;
  const phoneCats = categories().filter((c) => c.id === null);
  const phonePeople = people().filter((p) => p.id === null);
  return `<section class="card">
    <h2>Categories and people</h2>
    <p>${L.made ? `From Kuberlekha${L.entity ? ` (${esc(L.entity)})` : ''}, ${niceDate(L.made)}: ` : 'Not loaded from Kuberlekha yet: '}${categories().length} categories, ${people().length} people.</p>
    <button class="primary" data-action="loadList">Load list from Kuberlekha</button>
    <p class="small muted">In Kuberlekha: Import → “download the list for Cash Log”. Send the file to the phone, then load it here. Load it again after adding categories or people there.</p>
    ${phoneCats.length || phonePeople.length ? `<div class="label">Added on the phone (Kuberlekha adds unknown people; an unknown category waits for you in review)</div>
      <div class="chips">${[...phoneCats.map((c) => ['category', c.name]), ...phonePeople.map((p) => ['person', p.name])].map(([k, n]) => `<button class="chip removable" data-action="removeName" data-kind="${k}" data-value="${esc(n)}" aria-label="Remove ${esc(n)}">${esc(n)} ✕</button>`).join('')}</div>` : ''}
  </section>
  <section class="card">
    <h2>PIN</h2>
    <p>${hasPin() ? 'Cash Log asks for your PIN when it opens.' : 'No PIN: anyone holding the unlocked phone can open Cash Log.'}</p>
    <button class="ghost" data-action="setPin">${hasPin() ? 'Change PIN' : 'Set a 4-digit PIN'}</button>
    ${hasPin() ? '<button class="ghost" data-action="removePin">Remove PIN</button>' : ''}
  </section>
  <section class="card">
    <h2>Entries</h2>
    <p>${state.entries.length} on this phone, ${pending().length} not exported yet.</p>
    <button class="ghost" data-action="exportAll">Export everything again (a backup)</button>
    <button class="ghost danger" data-action="clearOld">Delete exported entries older than 90 days</button>
    <p class="small muted">Entries live only on this phone. Deleting Safari's website data, or the app from the home screen, deletes them too: export often. Exporting an entry twice never puts it in the books twice.</p>
  </section>
  <p class="muted center small">Cash Log ${APP_VERSION}</p>`;
}

function lockHtml() {
  const dots = [0, 1, 2, 3].map((i) => `<span class="dot${i < state.pin.length ? ' on' : ''}"></span>`).join('');
  const keys = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '', '0', '⌫'];
  return `<section class="lock">
    <img src="./icons/icon.svg" alt="" width="56" height="56" />
    <h1>Cash Log</h1>
    <p>Enter your PIN</p>
    <div class="dots" aria-label="${state.pin.length} of 4 digits">${dots}</div>
    <p class="error" role="alert">${esc(state.error || '')}</p>
    <div class="keypad">${keys.map((k) => (k ? `<button data-action="pinKey" data-value="${k}" aria-label="${k === '⌫' ? 'Delete' : k}">${k}</button>` : '<span></span>')).join('')}</div>
  </section>`;
}

// ---- modal and toast ----------------------------------------------------------------------------------------

const $modal = document.getElementById('modal');

function openModal(html) {
  $modal.innerHTML = `<div class="sheet" role="dialog" aria-modal="true">${html}</div>`;
  $modal.hidden = false;
}

function closeModal() {
  $modal.hidden = true;
  $modal.innerHTML = '';
}

$modal.addEventListener('click', (e) => {
  if (e.target === $modal) closeModal();
});

let toastTimer = null;

function toast(text) {
  const t = document.getElementById('toast');
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 4000);
}

function entryDetail(e) {
  const lines = [
    ['Date', niceDate(e.date)],
    ['Amount', inr(e.amountPaise)],
    e.type === 'received' ? ['From', e.person.name] : ['Category', e.category ? e.category.name : '—'],
  ];
  if (e.type === 'spent' && e.shares.length) {
    lines.push(['Your share', inr(e.mySharePaise)]);
    for (const s of e.shares) lines.push([`${s.name} owes`, inr(s.amountPaise)]);
  }
  if (e.note) lines.push(['Note', e.note]);
  lines.push(['Status', e.exportedAt ? `Exported ${niceDate(e.exportedAt.slice(0, 10))}` : 'Not exported yet']);
  return `<h2>${esc(entryTitle(e))}</h2>
    <dl class="detail">${lines.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>
    ${e.exportedAt ? '<p class="small muted">Already sent to Kuberlekha, so it cannot be changed here: change it in Kuberlekha. Deleting it here leaves the books as they are.</p>' : ''}
    <div class="actions">
      ${e.exportedAt ? '' : `<button class="primary" data-action="edit" data-id="${e.id}">Change</button>`}
      <button class="ghost danger" data-action="delete" data-id="${e.id}">Delete from this phone</button>
      <button class="ghost" data-action="closeModal">Close</button>
    </div>`;
}

// ---- actions ------------------------------------------------------------------------------------------------

function pickCategory(name) {
  if (name === '__new') {
    const typed = prompt('New category name (use the same name as in Kuberlekha):');
    const item = addName('category', typed);
    if (item) form().category = { id: item.id, name: item.name };
    return;
  }
  const c = findCategory(name);
  if (c) form().category = { id: c.id, name: c.name };
}

function pickPerson(name) {
  if (name === '__new') name = prompt('Their name:');
  const p = addName('person', name);
  return p ? { id: p.id, name: p.name } : null;
}

function toggleSharePerson(name) {
  const f = form();
  const i = f.people.findIndex((p) => key(p.name) === key(name));
  if (i >= 0) f.people.splice(i, 1);
  else {
    const p = pickPerson(name);
    if (p) f.people.push({ ...p, amount: '' });
  }
}

const actions = {
  view(el) {
    state.view = el.dataset.view;
    state.error = null;
    render();
    window.scrollTo(0, 0);
  },
  type(el) {
    const f = form();
    state.form = { ...blankForm(el.dataset.value), amount: f.amount, date: f.date, note: f.note };
    state.error = null;
    render();
  },
  category(el) {
    pickCategory(el.dataset.value);
    render();
  },
  person(el) {
    const f = form();
    f.person = f.person && key(f.person.name) === key(el.dataset.value) ? null : pickPerson(el.dataset.value);
    render();
  },
  sharePerson(el) {
    toggleSharePerson(el.dataset.value);
    render();
  },
  mode(el) {
    const f = form();
    if (el.dataset.value === 'amounts' && f.mode === 'equal') {
      const s = splitOf(f); // start from the equal split, so only the odd one out needs typing
      if (!s.problem) f.people.forEach((p) => (p.amount = rupees(s.shares.find((x) => key(x.name) === key(p.name))?.amountPaise || 0).replace(/\.00$/, '')));
    }
    f.mode = el.dataset.value;
    render();
  },
  save() {
    const r = entryFromForm(form());
    if (r.problem) {
      state.error = r.problem;
      document.getElementById('form-error').textContent = r.problem;
      return;
    }
    const was = state.editing && state.entries.find((e) => e.id === state.editing);
    if (was) Object.assign(was, r.entry, { changedAt: new Date().toISOString() });
    else state.entries.push({ id: newId(), createdAt: new Date().toISOString(), exportedAt: null, ...r.entry });
    if (!saveEntries()) return;
    const kept = form();
    state.form = { ...blankForm(kept.type), date: kept.date }; // keep the date: several entries of one day in a row
    state.editing = null;
    state.error = null;
    render();
    toast(was ? 'Changed.' : r.entry.type === 'spent' ? `Saved ${inr(r.entry.amountPaise)}.` : `Saved ${inr(r.entry.amountPaise)} from ${r.entry.person.name}.`);
    document.getElementById('amount')?.focus();
  },
  cancelEdit() {
    state.editing = null;
    state.form = null;
    state.error = null;
    render();
  },
  open(el) {
    const e = state.entries.find((x) => x.id === el.dataset.id);
    if (e) openModal(entryDetail(e));
  },
  edit(el) {
    const e = state.entries.find((x) => x.id === el.dataset.id);
    if (!e || e.exportedAt) return;
    closeModal();
    state.editing = e.id;
    state.form = formFromEntry(e);
    state.view = 'add';
    render();
    window.scrollTo(0, 0);
  },
  delete(el) {
    const e = state.entries.find((x) => x.id === el.dataset.id);
    if (!e) return;
    if (!e.exportedAt && !confirm('Delete this entry? It has not been exported, so it will be lost.')) return;
    state.entries = state.entries.filter((x) => x.id !== e.id);
    if (state.editing === e.id) actions.cancelEdit();
    saveEntries();
    closeModal();
    render();
    toast('Deleted from this phone.');
  },
  closeModal,
  export: () => exportEntries(false),
  exportAll: () => exportEntries(true),
  undoExport,
  showAll() {
    state.showAll = true;
    render();
  },
  loadList() {
    document.getElementById('list-file').click();
  },
  removeName(el) {
    const k = el.dataset.kind === 'category' ? 'categories' : 'people';
    state.lists[k] = state.lists[k].filter((x) => !(x.id === null && key(x.name) === key(el.dataset.value)));
    save(KEYS.lists, state.lists);
    render();
  },
  clearOld() {
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - 90);
    const from = cutoff.toISOString().slice(0, 10);
    const old = state.entries.filter((e) => e.exportedAt && e.date < from);
    if (!old.length) return toast('No exported entries older than 90 days.');
    if (!confirm(`Delete ${old.length} exported entries older than 90 days from this phone? Kuberlekha keeps them.`)) return;
    state.entries = state.entries.filter((e) => !old.includes(e));
    saveEntries();
    render();
  },
  async setPin() {
    const pin = prompt('New 4-digit PIN:');
    if (pin === null) return;
    if (!/^\d{4}$/.test(pin)) return toast('The PIN must be 4 digits.');
    if (prompt('Type it again:') !== pin) return toast('The two PINs differ; nothing changed.');
    state.settings.pinHash = await pinHash(pin);
    save(KEYS.settings, state.settings);
    render();
    toast('PIN set.');
  },
  removePin() {
    if (!confirm('Remove the PIN?')) return;
    delete state.settings.pinHash;
    save(KEYS.settings, state.settings);
    render();
  },
  async pinKey(el) {
    const k = el.dataset.value;
    state.error = null;
    if (k === '⌫') state.pin = state.pin.slice(0, -1);
    else if (state.pin.length < 4) state.pin += k;
    if (state.pin.length === 4) {
      if ((await pinHash(state.pin)) === state.settings.pinHash) {
        state.locked = false;
        state.pin = '';
      } else {
        state.pin = '';
        state.error = 'Wrong PIN.';
      }
    }
    render();
  },
};

const changes = {
  category(el) {
    if (el.value) pickCategory(el.value);
    render();
  },
  person(el) {
    if (el.value) form().person = pickPerson(el.value);
    render();
  },
  sharePerson(el) {
    const f = form();
    if (el.value && !(el.value !== '__new' && f.people.some((p) => key(p.name) === key(el.value)))) toggleSharePerson(el.value);
    render();
  },
  date(el) {
    form().date = el.value;
  },
  split(el) {
    form().split = el.checked;
    render();
  },
  includeMe(el) {
    form().includeMe = el.checked;
    render();
  },
  async listFile(el) {
    const file = el.files && el.files[0];
    el.value = '';
    if (!file) return;
    try {
      const n = loadList(JSON.parse(await file.text()));
      render();
      toast(`Loaded ${n.categories} categories and ${n.people} people.`);
    } catch (err) {
      toast(err instanceof SyntaxError ? 'That file is not a list from Kuberlekha.' : err.message);
    }
  },
};

const inputs = {
  amount(el) {
    form().amount = el.value;
    refreshSummary();
  },
  note(el) {
    form().note = el.value;
  },
  shareAmount(el) {
    const p = form().people[Number(el.dataset.index)];
    if (p) p.amount = el.value;
    refreshSummary();
  },
};

function refreshSummary() {
  const box = document.getElementById('split-summary');
  if (box) box.innerHTML = splitSummary(form());
}

document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-action]');
  if (!el || !actions[el.dataset.action]) return;
  if (el.tagName === 'A') e.preventDefault();
  actions[el.dataset.action](el);
});
document.addEventListener('change', (e) => {
  const el = e.target.closest('[data-change]');
  if (el && changes[el.dataset.change]) changes[el.dataset.change](el);
});
document.addEventListener('input', (e) => {
  const el = e.target.closest('[data-input]');
  if (el && inputs[el.dataset.input]) inputs[el.dataset.input](el);
});

// ---- start --------------------------------------------------------------------------------------------------

state.locked = hasPin();
render();
if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
if ('serviceWorker' in navigator && location.protocol === 'https:') navigator.serviceWorker.register('./sw.js').catch(() => {});
