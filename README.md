# Superdrug Account Report

A small personal tool that signs into **your own** Superdrug account, then collects your publicly-visible account data — profile, Health & Beautycard, addresses, saved payment methods (masked, last 4 digits only, exactly as Superdrug itself displays them), order history, subscriptions — and writes it all into a single neatly-formatted `.txt` report you can hand to your boss.

By default it runs in a hidden (headless) browser and asks you for your email and password at the terminal — no UI, no popping windows, just a clean CLI:

```
============================================================
  Superdrug Account Report
============================================================
  Account : you@example.com
  Started : 2026-04-24 11:07:13
------------------------------------------------------------
  [..] Logging in...
  [OK] Logged in (3.4s).
------------------------------------------------------------
  [..] Collecting Profile...
  [OK] Profile: ok
  [..] Collecting Health & Beautycard...
  [OK] Health & Beautycard: ok
  [..] Collecting Saved Addresses...
  [OK] Saved Addresses: ok
  [..] Collecting Saved Payment Methods...
  [OK] Saved Payment Methods: ok
  [..] Collecting Subscriptions...
  [!!] Subscriptions: empty
  [..] Collecting Order History...
  [OK] Order History: ok
------------------------------------------------------------
  [OK] Report written to reports/superdrug_report_you_at_example_com_2026-04-24_1107.txt
      (24,118 bytes)
```

If Superdrug shows a CAPTCHA or 2FA challenge during login, the tool **automatically reopens the browser visibly** and asks you to solve it in the window — once.

## Intended use

**Your own account, one at a time.** There is deliberately:

- no combo-list / batch mode
- no proxy rotation
- no CAPTCHA solver or anti-bot evasion
- no full card number extraction — Superdrug itself only shows the last 4 digits, and that's all the report contains

Your password lives only in the running process's memory; it is never written to disk, never sent to any third party, and never stored anywhere unless you explicitly put it in an environment variable yourself.

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

It will prompt for:

```
Superdrug email: you@example.com
Password (input hidden):
```

Then it logs in silently in a hidden browser, walks through your account pages, and writes the report under `reports/`.

### Non-interactive use

```bash
SUPERDRUG_EMAIL='you@example.com' \
SUPERDRUG_PASSWORD='hunter2'      \
python superdrug_report.py
```

or with flags + a different env var name for the password:

```bash
python superdrug_report.py --email you@example.com --password-from-env MY_SD_PW
```

### Flags

| Flag | What it does |
|------|--------------|
| `--email EMAIL` | Account email (otherwise prompted). |
| `--password-from-env VAR` | Read the password from this environment variable instead of prompting. Default falls back to `SUPERDRUG_PASSWORD`. |
| `--output DIR` | Where to write the report (default `reports/`). |
| `--debug` | Also save raw HTML / visible text of each page under `<output>/debug/`. |
| `--show-browser` | Run the browser visibly. Useful if Superdrug is repeatedly CAPTCHA-ing you. |
| `--manual-login` | Open a visible browser and let you sign in yourself — no email/password prompts. |
| `--no-cache` | Ignore cached browser state; start fresh. |
| `--state-dir DIR` | Where to persist browser profile data (default `.browser_state/`). |

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

- **"CAPTCHA / 2FA detected — opening a visible browser window"** — solve the challenge in the window, press Enter; the session is cached so subsequent runs go straight through.
- **"Login rejected — email/password didn't work"** — re-check the credentials. Superdrug normally locks the account after a few wrong attempts; if so, reset the password on their site first.
- **Page didn't load / selector missing** — Superdrug may have changed a layout. Rerun with `--debug` to save the raw HTML of each page under `reports/debug/`.
- **Repeatedly being challenged on every run** — try `--show-browser` once, solve the CAPTCHA, then later runs can go back to hidden mode using the cached `.browser_state/`.

## Files

```
superdrug_report.py    # entrypoint: credentials, auto-login, scraper orchestration, report write-out
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
