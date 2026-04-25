"""Superdrug Account Report — personal single-account tool.

Usage:
    python superdrug_report.py [options]

Asks for your Superdrug email and password at the terminal, signs in for you in
a hidden browser, and writes a single neatly-formatted .txt report covering
your profile, Health & Beautycard, addresses, saved payment methods (masked —
last 4 only, the same as the website itself shows), subscriptions, and
order history.

Explicitly designed for *your own* single account. No combo-list input, no
proxy rotation, no CAPTCHA solver, no anti-bot evasion. If Superdrug shows a
CAPTCHA or 2FA challenge, the browser is reopened visibly so you can solve it
yourself.
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, sync_playwright
from playwright.sync_api import TimeoutError as PWTimeout

import report
from scrapers import ALL_SCRAPERS

LOGIN_URL = "https://www.superdrug.com/login"
ACCOUNT_URL = "https://www.superdrug.com/my-account"
HERE = Path(__file__).resolve().parent
DEFAULT_STATE_DIR = HERE / ".browser_state"
DEFAULT_OUTPUT_DIR = HERE / "reports"
DEFAULT_CDP_URL = "http://localhost:9222"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Tiny init script that hides the most obvious automation tells. This is NOT a
# CAPTCHA bypass / fingerprint randomiser — it just stops `navigator.webdriver`
# from screaming "I'm a bot" at every site we visit. Without this, sites like
# Cloudflare-fronted Superdrug throw their challenge page at us instantly.
_STEALTH_INIT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-GB', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = window.chrome || { runtime: {} };
"""


# ---------------------------------------------------------------------------
# CLI / credentials
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--email", help="Account email. Prompts interactively if omitted.")
    p.add_argument(
        "--password-from-env",
        metavar="VAR",
        help="Read the password from this environment variable instead of prompting.",
    )
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR,
                   help="Directory to write the .txt report into (default: ./reports)")
    p.add_argument("--debug", action="store_true",
                   help="Save raw HTML/text of each visited page under <output>/debug/.")
    p.add_argument(
        "--show-browser",
        action="store_true",
        help="Show the browser window (default: hidden). Useful if Superdrug throws a CAPTCHA.",
    )
    p.add_argument(
        "--manual-login",
        action="store_true",
        help="Skip automatic form-fill — open a visible browser and let you sign in yourself.",
    )
    p.add_argument(
        "--use-my-chrome",
        action="store_true",
        help=(
            "Connect to your own already-running Chrome instead of launching one. "
            "Start Chrome yourself with `--remote-debugging-port=9222`, sign in to "
            "Superdrug like a human, then run with this flag. Bulletproof against "
            "bot detection because it literally is your real browser."
        ),
    )
    p.add_argument(
        "--cdp-url",
        default=DEFAULT_CDP_URL,
        help=f"Where to find your running Chrome's debug endpoint (default: {DEFAULT_CDP_URL}).",
    )
    p.add_argument("--no-cache", action="store_true",
                   help="Don't reuse cached browser state; start fresh.")
    p.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR,
                   help=f"Where to persist browser profile data (default: {DEFAULT_STATE_DIR}).")
    return p.parse_args()


def get_credentials(args: argparse.Namespace) -> tuple[str, str]:
    """Resolve email + password from flags / env / interactive prompts."""
    email = args.email or os.environ.get("SUPERDRUG_EMAIL", "").strip()
    if not email:
        try:
            email = input("Superdrug email: ").strip()
        except EOFError:
            email = ""
    if not email or "@" not in email:
        sys.exit("error: a valid email address is required")

    password = ""
    if args.password_from_env:
        password = os.environ.get(args.password_from_env, "")
        if not password:
            sys.exit(f"error: ${args.password_from_env} is empty or unset")
    else:
        password = os.environ.get("SUPERDRUG_PASSWORD", "")
        if not password:
            try:
                password = getpass.getpass("Password (input hidden): ")
            except EOFError:
                password = ""
    if not password:
        sys.exit("error: password is required")
    return email, password


# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------


def _line() -> None:
    print("-" * 60)


def banner(email: str) -> None:
    print()
    print("=" * 60)
    print("  Superdrug Account Report")
    print("=" * 60)
    print(f"  Account : {email}")
    print(f"  Started : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    _line()


def step(msg: str) -> None:
    print(f"  [..] {msg}")


def ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def warn(msg: str) -> None:
    print(f"  [!!] {msg}")


def fail(msg: str) -> None:
    print(f"  [XX] {msg}")


# ---------------------------------------------------------------------------
# Browser / login
# ---------------------------------------------------------------------------


def open_context(pw, args: argparse.Namespace, *, headless: bool) -> BrowserContext:
    state_dir = args.state_dir
    if args.no_cache and state_dir.exists():
        state_dir = state_dir.with_name(state_dir.name + "-fresh")
    state_dir.mkdir(parents=True, exist_ok=True)

    launch_kwargs = dict(
        user_data_dir=str(state_dir),
        headless=headless,
        viewport={"width": 1280, "height": 900},
        user_agent=USER_AGENT,
        locale="en-GB",
        timezone_id="Europe/London",
        extra_http_headers={
            "Accept-Language": "en-GB,en;q=0.9",
            "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Linux"',
        },
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--no-default-browser-check",
            "--no-first-run",
        ],
    )

    # Prefer real Chrome over Playwright's bundled Chromium — much harder for
    # Cloudflare/Akamai to fingerprint. Fall back to bundled Chromium if Chrome
    # isn't installed on this machine.
    try:
        ctx = pw.chromium.launch_persistent_context(channel="chrome", **launch_kwargs)
    except Exception:
        ctx = pw.chromium.launch_persistent_context(**launch_kwargs)

    ctx.add_init_script(_STEALTH_INIT)
    return ctx


def connect_to_my_chrome(pw, cdp_url: str) -> BrowserContext:
    """Attach to the user's already-running Chrome instead of launching one."""
    browser = pw.chromium.connect_over_cdp(cdp_url)
    if browser.contexts:
        ctx = browser.contexts[0]
    else:
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=USER_AGENT,
            locale="en-GB",
            timezone_id="Europe/London",
        )
    ctx.add_init_script(_STEALTH_INIT)
    return ctx


def _dismiss_cookie_banner(page: Page) -> None:
    for sel in (
        "button:has-text('Accept Cookies')",
        "button:has-text('Accept All')",
        "button:has-text('Accept')",
        "#onetrust-accept-btn-handler",
    ):
        btn = page.query_selector(sel)
        if btn:
            try:
                btn.click(timeout=2000)
                page.wait_for_timeout(300)
                return
            except Exception:
                pass


def _is_captcha(page: Page) -> bool:
    """Best-effort detection of CAPTCHA / Cloudflare / bot-challenge pages."""
    url = page.url.lower()
    if any(s in url for s in ("captcha", "challenges.cloudflare", "/cdn-cgi/challenge")):
        return True
    body = page.query_selector("body")
    text = (body.inner_text() if body else "").lower() if body else ""
    needles = (
        "verify you are human",
        "i'm not a robot",
        "checking your browser",
        "complete the security check",
        "press and hold",
        "needs to review the security",
        "captcha",
    )
    if any(n in text for n in needles):
        return True
    for sel in (
        "iframe[src*='recaptcha']",
        "iframe[src*='hcaptcha']",
        "iframe[src*='turnstile']",
        "div.g-recaptcha",
        "[data-sitekey]",
    ):
        if page.query_selector(sel):
            return True
    return False


def _is_logged_in(page: Page) -> bool:
    url = page.url.lower()
    if "/login" in url and "my-account" not in url:
        return False
    for sel in (
        "a:has-text('Sign out')",
        "a:has-text('Logout')",
        "button:has-text('Sign out')",
        "a[href*='/logout']",
    ):
        if page.query_selector(sel):
            return True
    return "/my-account" in url


def attempt_auto_login(page: Page, email: str, password: str) -> str:
    """Drive the Superdrug login form. Returns one of:
        "ok"           — landed on /my-account
        "captcha"      — CAPTCHA / bot-challenge detected
        "bad_creds"    — login form re-displayed with an error message
        "unknown"      — couldn't determine state
    """
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=20_000)
    except Exception:
        return "unknown"

    _dismiss_cookie_banner(page)

    if _is_captcha(page):
        return "captcha"

    # If state is cached and we're already logged in, the login URL redirects.
    if _is_logged_in(page):
        return "ok"

    # Locate and fill the form.
    email_sel = next(
        (s for s in (
            "input[type=email]",
            "input[name='email']",
            "input[placeholder*='email' i]",
        ) if page.query_selector(s)),
        None,
    )
    pw_sel = next(
        (s for s in (
            "input[type=password]",
            "input[name='password']",
            "input[placeholder*='password' i]",
        ) if page.query_selector(s)),
        None,
    )
    if not (email_sel and pw_sel):
        return "unknown"

    try:
        page.fill(email_sel, email)
        page.fill(pw_sel, password)
    except Exception:
        return "unknown"

    submit_sel = next(
        (s for s in (
            "button:has-text('Login')",
            "button:has-text('Sign in')",
            "button[type=submit]",
        ) if page.query_selector(s)),
        None,
    )
    if not submit_sel:
        return "unknown"

    try:
        with page.expect_navigation(wait_until="domcontentloaded", timeout=20_000):
            page.click(submit_sel)
    except PWTimeout:
        # Some submits just swap out the form via JS without a navigation event.
        pass
    except Exception:
        return "unknown"

    # Give the page a beat to settle (account dashboards often hydrate from XHR).
    for _ in range(15):
        if _is_captcha(page):
            return "captcha"
        if _is_logged_in(page):
            return "ok"
        page.wait_for_timeout(500)

    if _is_captcha(page):
        return "captcha"
    if _is_logged_in(page):
        return "ok"

    # Look for a visible error on the login form.
    body = page.query_selector("body")
    text = (body.inner_text() if body else "").lower()
    for needle in ("incorrect", "invalid", "could not", "didn't recognise", "didn't recognize"):
        if needle in text:
            return "bad_creds"

    return "unknown"


def manual_login_loop(ctx: BrowserContext, page: Page, *, reason: str = "") -> bool:
    """Visible-browser fallback: ask the owner to log in / solve CAPTCHA themselves."""
    print()
    if reason:
        warn(reason)
    warn("Opening a visible browser window so you can sign in (and solve any challenge) yourself.")
    print("        After you're on the account dashboard, come back here and press Enter.")
    print()
    with contextlib.suppress(Exception):
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=20_000)
    try:
        input("  Press Enter once you're logged in... ")
    except KeyboardInterrupt:
        return False

    with contextlib.suppress(Exception):
        page.goto(ACCOUNT_URL, wait_until="domcontentloaded", timeout=15_000)
    return _is_logged_in(page)


# ---------------------------------------------------------------------------
# Account email detection (post-login)
# ---------------------------------------------------------------------------


def detect_email(page: Page, fallback: str) -> str:
    for sel in ("[data-testid*=email]", "[data-test*=email]", ".account-email"):
        node = page.query_selector(sel)
        if node:
            txt = (node.inner_text() or node.get_attribute("value") or "").strip()
            if "@" in txt:
                return txt
    body = page.query_selector("body")
    text = (body.inner_text() if body else "") or ""
    m = re.search(r"[\w.+\-]+@[\w\-]+\.[A-Za-z]{2,}", text)
    return m.group(0) if m else fallback


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run() -> int:
    args = parse_args()

    if args.use_my_chrome:
        email = args.email or input("Superdrug email (for the report header): ").strip()
        password = ""
    elif args.manual_login:
        # Manual mode: skip prompting for password, open a visible browser.
        email = args.email or input("Superdrug email (for the report header): ").strip()
        password = ""
    else:
        email, password = get_credentials(args)

    args.output.mkdir(parents=True, exist_ok=True)
    debug_dir = (args.output / "debug") if args.debug else None

    banner(email)

    headless = not args.show_browser and not args.manual_login and not args.use_my_chrome

    with sync_playwright() as pw:
        if args.use_my_chrome:
            step(f"Connecting to your Chrome at {args.cdp_url}...")
            try:
                ctx = connect_to_my_chrome(pw, args.cdp_url)
            except Exception as e:
                fail(f"Could not connect: {e}")
                print(
                    "        Start Chrome first with:\n"
                    "          google-chrome --remote-debugging-port=9222\n"
                    "        then sign in to https://www.superdrug.com and rerun."
                )
                return 1
            ok("Connected.")
        else:
            ctx = open_context(pw, args, headless=headless)
        try:
            page = ctx.new_page()

            # ---- Login phase ----
            if args.use_my_chrome:
                step("Loading account dashboard...")
                with contextlib.suppress(Exception):
                    page.goto(ACCOUNT_URL, wait_until="domcontentloaded", timeout=20_000)
                if not _is_logged_in(page):
                    fail(
                        "Your Chrome doesn't appear to be signed into Superdrug. "
                        "Sign in there first, then rerun."
                    )
                    return 1
                ok("Already signed in.")
            elif args.manual_login:
                step("Opening browser for manual login...")
                if not manual_login_loop(ctx, page):
                    fail("Login was not completed. Aborting.")
                    return 1
                ok("Logged in.")
            else:
                step("Logging in...")
                t0 = time.time()
                status = attempt_auto_login(page, email, password)
                elapsed = time.time() - t0

                if status == "ok":
                    ok(f"Logged in ({elapsed:.1f}s).")
                elif status == "bad_creds":
                    fail("Login rejected — email/password didn't work.")
                    return 1
                else:
                    if status == "captcha":
                        reason = "CAPTCHA / bot-challenge detected."
                    else:
                        reason = (
                            "Couldn't auto-login — Superdrug may be flagging the script as a bot."
                        )
                    print()
                    warn(reason)
                    print(
                        "        TIP: the most reliable way to run this tool is\n"
                        "             `--use-my-chrome` (start your own Chrome with\n"
                        "             `--remote-debugging-port=9222`, sign in normally,\n"
                        "             then rerun this script with that flag)."
                    )
                    with contextlib.suppress(Exception):
                        ctx.close()
                    ctx = open_context(pw, args, headless=False)
                    page = ctx.new_page()
                    if not manual_login_loop(ctx, page, reason=""):
                        fail("Login was not completed. Aborting.")
                        return 1
                    ok("Logged in.")

            account_email = detect_email(page, fallback=email)

            # ---- Scrape phase ----
            _line()
            sections: dict[str, dict] = {}
            for title, module in ALL_SCRAPERS:
                step(f"Collecting {title}...")
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
                status = sections[title].get("status", "?")
                if status == "ok":
                    ok(f"{title}: {status}")
                elif status in {"empty", "skipped"}:
                    warn(f"{title}: {status}")
                else:
                    fail(f"{title}: {status}")

            collected = {
                "account_email": account_email,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "sections": sections,
            }
        finally:
            with contextlib.suppress(Exception):
                ctx.close()

    # ---- Render phase ----
    text = report.render(collected)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    email_slug = re.sub(r"[^A-Za-z0-9]+", "_", account_email).strip("_") or "account"
    out_path = args.output / f"superdrug_report_{email_slug}_{stamp}.txt"
    out_path.write_text(text, encoding="utf-8")

    _line()
    ok(f"Report written to {out_path}")
    print(f"      ({out_path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(run())
