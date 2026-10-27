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

Plain HTML, CSS and JavaScript; no build step. Hosted on GitHub Pages. The icon and the logo are Kuberlekha's
own brand files (`icons/icon.svg`, `icons/logo-light.svg`, `icons/logo-dark.svg`, copied unchanged from
`frontend/public/brand`), and the colours are its ledger red, gold and ivory; the PNG icons are renders of
`icon.svg` on the same red, so the corners stay red when the phone rounds them. Bump `CACHE_VERSION` in
`sw.js` and `APP_VERSION` in `app.js` on every release.

The CSV format is documented in Kuberlekha's `docs/parsers.md` (Cash Log section).
