# Superdrug Account Report

A small personal tool that signs into **your own** Superdrug account, then collects your publicly-visible account data — profile, Health & Beautycard, addresses, saved payment methods (masked, last 4 digits only, exactly as Superdrug itself displays them), order history, subscriptions — and writes it all into a single neatly-formatted `.txt` report you can hand to your boss.

When you run it you just get a numbered menu — no command-line flags to memorise:

```
============================================================
  Superdrug Account Report
============================================================
  How would you like to sign in?

    1) Type my email + password   (silent / hidden browser, fast
                                   — may fail if Superdrug bot-blocks)
    2) Open Chrome for me          [most reliable]
                                   I open your real Chrome, you sign in there.
    3) Open a visible browser      Plays in front of you; sign in by hand.
    4) Use cached session          Skip login if I've signed in before.
    5) Quit

  Pick [1-5]:
```

## Which option should I pick?

- **1 — Type my email + password.** Fastest. The browser stays hidden, the tool fills the login form for you and writes the report. Works most of the time, but Superdrug runs Akamai bot detection and sometimes flags the script — when it does, you'll see `[!!] Superdrug looks like it's flagging the script` and a suggestion to use option 2.
- **2 — Open Chrome for me. *(most reliable)*** The tool launches your real Google Chrome with a Superdrug login tab already open, and you sign in there like a human. After signing in you press Enter back in the terminal and the rest is automatic. **No password ever leaves your browser** — the script only reads the already-authenticated session. Akamai sees a real human session because it *is* one. The Chrome window stays open afterwards so subsequent runs skip login entirely.
- **3 — Open a visible browser.** Same as 2 but uses Playwright's bundled Chromium instead of your real Chrome. Slightly less reliable against bot detection.
- **4 — Use cached session.** If you've already signed in once via 1, 2 or 3, this just re-uses the saved cookies. Instant. Falls back with a clear error if there's no cache yet.

## Intended use

**Your own account, one at a time.** There is deliberately:

- no combo-list / batch mode
- no proxy rotation
- no CAPTCHA solver or fingerprint-randomising "stealth" beyond the bare minimum needed to look like a normal browser instead of an obvious robot
- no full card number extraction — Superdrug itself only shows the last 4 digits, and that's all the report contains

Your password lives only in the running process's memory; it is never written to disk, never sent to any third party, and never stored anywhere unless you explicitly put it in an environment variable yourself.

You're responsible for complying with Superdrug's Terms of Service. In most jurisdictions, exporting your own account data is a right (e.g. under UK GDPR / data portability); this tool just automates the "copy & paste my own order history into a document" chore.

## Install

Requires Python 3.10+ and (for option 2) Google Chrome installed normally on your computer.

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

You'll see the numbered menu. Pick a number and follow the on-screen prompts. The report appears under `reports/` once the run completes.

### Skip the menu

If you want to wire this into a script, you can pass `--mode N` to skip the menu, or set the environment variable `SUPERDRUG_REPORT_MODE=N`:

```bash
python superdrug_report.py --mode 1                          # auto-login
python superdrug_report.py --mode 2                          # open Chrome for me
SUPERDRUG_REPORT_MODE=4 python superdrug_report.py           # cached only
```

For non-interactive auto-login (e.g. cron):

```bash
SUPERDRUG_EMAIL='you@example.com' \
SUPERDRUG_PASSWORD='hunter2'      \
python superdrug_report.py --mode 1
```

### Flags

Most users won't need any of these — pick a number from the menu and you're done.

| Flag | What it does |
|------|--------------|
| `--mode {1,2,3,4}` | Skip the interactive menu and go straight to a mode. |
| `--email EMAIL` | Use this email instead of asking. |
| `--password-from-env VAR` | Read the password from this environment variable instead of prompting. Default fallback is `SUPERDRUG_PASSWORD`. |
| `--output DIR` | Where to write the report (default `reports/`). |
| `--debug` | Also save raw HTML / visible text of each page under `<output>/debug/`. |
| `--no-cache` | Ignore cached browser state; start fresh. |
| `--state-dir DIR` | Where to persist Playwright browser profile data (default `.browser_state/`). |
| `--cdp-url URL` | For mode 2: where the launched Chrome's debug endpoint listens (default `http://localhost:9222`). |

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

- **"Couldn't auto-login — Superdrug looks like it's flagging the script."** Akamai's bot detector is having a moment. Pick option 2 from the menu next time — that uses your real Chrome and is essentially undetectable.
- **"Couldn't find a Chrome / Chromium installation."** (Mode 2) Install Google Chrome from <https://www.google.com/chrome/>.
- **No cached session found.** (Mode 4) Run option 1, 2 or 3 once to sign in; the cookies are then cached under `.browser_state/` (or, for mode 2, under `~/.cache/superdrug-report-chrome/`).
- **Order history report is empty.** Make sure you have at least one order on the account; new accounts show no history.
