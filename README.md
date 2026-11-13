# Kuberlekha Cash Log

[Kuberlekha](https://github.com/purvkanani5-art)'s phone companion for spending. Entries stay on the phone;
**Export** makes CSV files that Kuberlekha imports like bank statements. Nothing is sent anywhere else.

- **Spent:** amount, category, note, date. **Split with others** divides it equally or by amounts;
  each person's share becomes what they owe you in Kuberlekha.
- **Received:** a person paid you back.
- **Paid from / Received into** (1.1): the account the money left or entered, from Kuberlekha's list
  (Cash in Hand unless you tap a bank account or card).
- **Export** sends only entries not exported yet, one file per account, named for it
  (`cash-2026-10-27.csv`, `hdfc-savings-2026-10-27.csv`); upload each in Kuberlekha → Import to that
  account. Every entry has its own id, so exporting twice never posts twice. Exported entries are
  read-only here.
- **Settings:** load the categories, people and accounts list downloaded from Kuberlekha, set a 4-digit PIN.
- **Calc** (1.2): Kuberlekha's financial calculator, the same calculators with the same answers to the last
  digit: TVM (solve any of N, I/Y, PV, PMT, FV), annuities, interest and rate conversions, money-market
  yields, flat against reducing rates, NPV, IRR, MIRR, XIRR, dates, percentages; (1.3) returns, statistics
  as Excel works them out, the normal distribution, volatility, drawdown, Sharpe, Sortino, alpha, beta, VaR,
  with tables pasted from Excel and the risk-free rate from the list; (1.4) loans (EMI, prepayment, true
  cost, comparing offers, balance transfer), planners (SIP with step-up, goal, SWP, retirement, FD, RD, PPF,
  EPF, NPS, Sukanya Samriddhi, ULIP against term + fund, rent or buy, cost of delay) and depreciation; a
  keypad with registers M0 to
  M9 and a tape; inputs saved on the phone by name.
- **Tax** (1.2): Kuberlekha's income tax calculator (new regime), with the rates from the loaded list, or the
  built-in rates until one is loaded.

Calc and Tax run Kuberlekha's own Python code (`py/calc`, copied unchanged by Kuberlekha's
`scripts/export_calc.py`, hashes in `py/MANIFEST.json`) on the phone under [Pyodide](https://pyodide.org)
314.0.7 (`pyodide/`, MPL-2.0, vendored as published). Python loads only when one of the two tabs opens, so
Cash Log itself opens as fast as before. The service worker keeps Pyodide in its own cache (about 13 MB,
downloaded once), so after the first visit everything works without a signal. Tests, with Node:
`node tests/run-vectors.mjs` (the phone's answers against Kuberlekha's, exactly) and `node tests/browser.mjs`
(a phone-sized browser, including offline).

Plain HTML, CSS and JavaScript; no build step. Hosted on GitHub Pages. The icon and the logo are Kuberlekha's
own brand files (`icons/icon.svg`, `icons/logo-light.svg`, `icons/logo-dark.svg`, copied unchanged from
`frontend/public/brand`), and the colours are its ledger red, gold and ivory; the PNG icons are renders of
`icon.svg` on the same red, so the corners stay red when the phone rounds them. Bump `CACHE_VERSION` in
`sw.js` and `APP_VERSION` in `app.js` on every release.

The CSV format is documented in Kuberlekha's `docs/parsers.md` (Cash Log section).
