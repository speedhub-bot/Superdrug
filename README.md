# Superdrug Account Report

A small personal tool that logs into **your own** Superdrug account in a real browser window (you type the password, you handle 2FA/CAPTCHA), then collects your publicly-visible account data — profile, Health & Beautycard, addresses, saved payment methods (masked — last 4 digits only, as Superdrug itself shows them), order history, subscriptions — and writes it all into a single neatly-formatted `.txt` report you can hand to your boss.

## Intended use

**Your own account, one at a time.** There is deliberately:

- no combo-list / batch mode
- no proxy rotation
- no CAPTCHA solver or anti-bot evasion
- no full card number extraction — Superdrug itself only shows the last 4 digits, and that's all the report contains

If Superdrug asks you to solve a CAPTCHA or confirm a 2FA code, solve it in the browser window like you normally would. If the site blocks the session, the tool stops.

You're responsible for complying with Superdrug's Terms of Service. In most jurisdictions, exporting your own account data is a right (e.g. under UK GDPR / data portability); this tool just automates the "copy & paste my own order history into a document" chore.

## Install

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Run

```bash
python superdrug_report.py
```

What happens:

1. A Chromium window opens on `https://www.superdrug.com/login`.
2. Log in yourself. Solve any CAPTCHA / 2FA / age check in the window.
3. Once you're on your account dashboard, return to the terminal and press Enter.
4. The tool navigates through your account pages, collecting data. This takes ~30–60 seconds.
5. A report is written to `reports/superdrug_report_<email>_<YYYY-MM-DD_HHMM>.txt`.

Your browser session (cookies / localStorage) is cached in `.browser_state/` so you don't have to log in again on the next run. Delete that folder to force a fresh login.

## Report sections

The `.txt` report contains these sections, each clearly delimited with headers:

1. **Summary** — account email, date of export, lifetime order count & spend, current points balance.
2. **Profile** — name, email, phone, DOB, gender, marketing preferences.
3. **Health & Beautycard** — card number, points balance, tier, active vouchers.
4. **Saved Addresses** — every delivery / billing address on file.
5. **Saved Payment Methods** — card brand + last 4 + expiry (no full PAN; Superdrug doesn't expose it).
6. **Subscriptions** — active subscribe-&-save items, if any.
7. **Order History** — every order: date, order #, status, items (name / qty / unit price), total, delivery address, tracking link.

If any section can't be parsed into structured fields, the tool falls back to dumping the visible page text under that section so nothing is lost.

## Troubleshooting

- **"Page didn't load / selector missing"** — Superdrug may have changed a page layout. Rerun with `--debug` to save the raw HTML of each page under `reports/debug/`.
- **Still getting logged out** — delete `.browser_state/` and log in fresh.
- **CAPTCHA every time** — that's Superdrug's bot detection reacting to automation; solve it in the window, the session should stick afterward.

## Flags

```
python superdrug_report.py [--output reports/] [--debug] [--headless] [--no-cache]
```

- `--output DIR` — where to write the report (default `reports/`).
- `--debug` — also save raw HTML of each page under `reports/debug/`.
- `--headless` — run the browser headless (only works after the first login is cached).
- `--no-cache` — don't reuse cached browser state; start fresh.

## Files

```
superdrug_report.py    # entrypoint: launches browser, orchestrates scrapers, writes report
report.py              # turns the collected data dict into a neat .txt
scrapers/
  __init__.py
  base.py              # shared helpers (safe_goto, extract_fields, dump_visible_text)
  profile.py
  beautycard.py
  addresses.py
  payments.py
  orders.py
  subscriptions.py
```
