# Cash Log

A phone web app for cash spending. Entries stay on the phone; **Export** makes a CSV that
[Kuberlekha](https://github.com/purvkanani5-art) imports into Cash in Hand like a bank statement.
Nothing is sent anywhere else.

- **Spent:** amount, category, note, date. **Split with others** divides it equally or by amounts;
  each person's share becomes what they owe you in Kuberlekha.
- **Received:** a person paid you back in cash.
- **Export** sends only entries not exported yet. Every entry has its own id, so exporting twice never
  posts twice. Exported entries are read-only here.
- **Settings:** load the category and people list downloaded from Kuberlekha, set a 4-digit PIN.

Plain HTML, CSS and JavaScript; no build step. Hosted on GitHub Pages. Bump `CACHE_VERSION` in `sw.js`
and `APP_VERSION` in `app.js` on every release.

The CSV format is documented in Kuberlekha's `docs/parsers.md` (Cash Log section).
