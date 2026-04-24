"""Superdrug Account Report — personal single-account tool.

Usage:
    python superdrug_report.py [--output DIR] [--debug] [--headless] [--no-cache]

Opens a Chromium window at the Superdrug login page. *You* log in (including
any 2FA / CAPTCHA) in that window. Once you're on your account dashboard,
return to the terminal and press Enter. The tool then collects your profile,
Health & Beautycard, addresses, saved payment methods (masked), subscriptions,
and order history, and writes a single neatly-formatted .txt report.

Explicitly designed for *your own* single account. No combo-list input, no
proxy rotation, no CAPTCHA solver, no anti-bot evasion.
"""

from __future__ import annotations

import argparse
import contextlib
import re
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, sync_playwright

import report
from scrapers import ALL_SCRAPERS

LOGIN_URL = "https://www.superdrug.com/login"
ACCOUNT_URL = "https://www.superdrug.com/my-account"
HERE = Path(__file__).resolve().parent
DEFAULT_STATE_DIR = HERE / ".browser_state"
DEFAULT_OUTPUT_DIR = HERE / "reports"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR,
                   help="Directory to write the .txt report into (default: ./reports)")
    p.add_argument("--debug", action="store_true",
                   help="Also save raw HTML/text of each page under <output>/debug/")
    p.add_argument("--headless", action="store_true",
                   help="Run the browser headless (only useful after the first login is cached).")
    p.add_argument("--no-cache", action="store_true",
                   help="Don't reuse cached browser state; start from a fresh profile.")
    p.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR,
                   help=f"Where to persist browser profile data (default: {DEFAULT_STATE_DIR}).")
    return p.parse_args()


def is_logged_in(page: Page) -> bool:
    url = page.url.lower()
    if "/login" in url and "my-account" not in url:
        return False
    # Heuristic: account dashboard usually has a 'Sign out' / 'Logout' link.
    for sel in ("a:has-text('Sign out')", "a:has-text('Logout')", "button:has-text('Sign out')"):
        if page.query_selector(sel):
            return True
    # Fallback: presence of an account-only URL in nav.
    return "/my-account" in url


def detect_email(page: Page) -> str:
    for sel in ("[data-testid*=email]", "[data-test*=email]", ".account-email"):
        node = page.query_selector(sel)
        if node:
            txt = (node.inner_text() or node.get_attribute("value") or "").strip()
            if "@" in txt:
                return txt
    body = page.query_selector("body")
    text = (body.inner_text() if body else "") or ""
    m = re.search(r"[\w.+\-]+@[\w\-]+\.[A-Za-z]{2,}", text)
    return m.group(0) if m else ""


def wait_for_manual_login(page: Page) -> None:
    print()
    print("A browser window is now open on Superdrug's login page.")
    print("  1. Log in with your own email and password.")
    print("  2. Complete any CAPTCHA or 2FA in that window.")
    print("  3. When you're on your account dashboard, come back here and press Enter.")
    print()
    try:
        input("Press Enter once you're logged in... ")
    except KeyboardInterrupt:
        print("Aborted.")
        sys.exit(130)

    # Nudge to the account page and verify.
    with contextlib.suppress(Exception):
        page.goto(ACCOUNT_URL, wait_until="domcontentloaded", timeout=15_000)

    if not is_logged_in(page):
        print("⚠ Doesn't look like you're logged in — the tool will try to continue anyway,")
        print("  but most sections will likely be marked skipped.")


def open_context(pw, args: argparse.Namespace) -> BrowserContext:
    state_dir = args.state_dir
    if args.no_cache and state_dir.exists():
        # Don't recursively delete — just point at a fresh throwaway dir.
        state_dir = state_dir.with_name(state_dir.name + "-fresh")
    state_dir.mkdir(parents=True, exist_ok=True)

    return pw.chromium.launch_persistent_context(
        user_data_dir=str(state_dir),
        headless=args.headless,
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )


def run() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    debug_dir = (args.output / "debug") if args.debug else None

    with sync_playwright() as pw:
        ctx = open_context(pw, args)
        try:
            page = ctx.new_page()
            try:
                page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=20_000)
            except Exception as e:
                print(f"Could not open Superdrug login page: {e}")
                return 2

            wait_for_manual_login(page)

            account_email = detect_email(page)

            sections: dict[str, dict] = {}
            for title, module in ALL_SCRAPERS:
                print(f"• Collecting {title}...")
                try:
                    sections[title] = module.scrape(page, debug_dir=debug_dir)
                except Exception as e:
                    sections[title] = {
                        "status": "error",
                        "url": page.url,
                        "fields": {},
                        "items": [],
                        "raw_text": "",
                        "error": f"{type(e).__name__}: {e}",
                    }
                print(f"    status: {sections[title].get('status', '?')}")

            collected = {
                "account_email": account_email,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "sections": sections,
            }
        finally:
            with contextlib.suppress(Exception):
                ctx.close()

    text = report.render(collected)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    email_slug = re.sub(r"[^A-Za-z0-9]+", "_", account_email).strip("_") or "account"
    out_path = args.output / f"superdrug_report_{email_slug}_{stamp}.txt"
    out_path.write_text(text, encoding="utf-8")
    print()
    print(f"✔ Report written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
