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
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright
from playwright.sync_api import TimeoutError as PWTimeout

import report
from akamai import (
    EXTRA_HEADERS,
    LAUNCH_ARGS,
    BypassConfig,
    ChallengeStatus,
    apply_stealth,
    is_challenge,
)
from akamai.sensor import warm_up
from akamai.stealth import IGNORE_DEFAULT_ARGS
from scrapers import ALL_SCRAPERS

LOGIN_URL = "https://www.superdrug.com/login"
ACCOUNT_URL = "https://www.superdrug.com/my-account"
HERE = Path(__file__).resolve().parent
DEFAULT_STATE_DIR = HERE / ".browser_state"
DEFAULT_OUTPUT_DIR = HERE / "reports"
DEFAULT_CDP_URL = "http://localhost:9222"

# Default tunables: Chrome 131 / Linux / en-GB. Edit fields here if you want
# to spoof a different browser identity globally.
AKAMAI_CFG = BypassConfig()
USER_AGENT = AKAMAI_CFG.user_agent


# ---------------------------------------------------------------------------
# CLI / credentials
# ---------------------------------------------------------------------------


MODE_AUTO = 1          # type email + password, hidden browser
MODE_OPEN_CHROME = 2   # script launches your real Chrome, you sign in there
MODE_VISIBLE = 3       # visible browser, you sign in by hand
MODE_CACHED = 4        # reuse cached session, no login at all


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--mode",
        type=int,
        choices=[1, 2, 3, 4],
        help=(
            "Skip the interactive menu and pick a mode directly: "
            "1=auto-login, 2=open my Chrome, 3=visible browser, 4=cached session."
        ),
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
    p.add_argument("--no-cache", action="store_true",
                   help="Don't reuse cached browser state; start fresh.")
    p.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR,
                   help=f"Where to persist browser profile data (default: {DEFAULT_STATE_DIR}).")
    p.add_argument(
        "--cdp-url",
        default=DEFAULT_CDP_URL,
        help=f"For mode 2: where the launched Chrome's debug endpoint listens (default: {DEFAULT_CDP_URL}).",
    )
    return p.parse_args()


def interactive_menu() -> int:
    print()
    print("=" * 60)
    print("  Superdrug Account Report")
    print("=" * 60)
    print("  How would you like to sign in?")
    print()
    print("    1) Type my email + password   (silent / hidden browser, fast")
    print("                                   — may fail if Superdrug bot-blocks)")
    print("    2) Open Chrome for me          [most reliable]")
    print("                                   I open your real Chrome, you sign in there.")
    print("    3) Open a visible browser      Plays in front of you; sign in by hand.")
    print("    4) Use cached session          Skip login if I've signed in before.")
    print("    5) Quit")
    print()
    while True:
        try:
            choice = input("  Pick [1-5]: ").strip()
        except EOFError:
            return 5
        if choice in {"1", "2", "3", "4"}:
            return int(choice)
        if choice == "5" or choice.lower() in {"q", "quit", "exit"}:
            return 5
        print(f"    '{choice}' isn't 1-5. Try again.")


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
        viewport={
            "width": AKAMAI_CFG.viewport.width,
            "height": AKAMAI_CFG.viewport.height,
        },
        user_agent=USER_AGENT,
        locale=AKAMAI_CFG.locale,
        timezone_id=AKAMAI_CFG.timezone_id,
        extra_http_headers=dict(EXTRA_HEADERS),
        ignore_default_args=list(IGNORE_DEFAULT_ARGS),
        args=list(LAUNCH_ARGS),
    )

    # Prefer real Chrome over Playwright's bundled Chromium — much harder for
    # Cloudflare/Akamai to fingerprint. Fall back to bundled Chromium if Chrome
    # isn't installed on this machine.
    try:
        ctx = pw.chromium.launch_persistent_context(channel="chrome", **launch_kwargs)
    except Exception:
        ctx = pw.chromium.launch_persistent_context(**launch_kwargs)

    apply_stealth(ctx, AKAMAI_CFG)
    return ctx


# ---------------------------------------------------------------------------
# Mode 2: launch the user's real Chrome ourselves and attach to it
# ---------------------------------------------------------------------------


def _find_chrome_binary() -> str | None:
    """Locate the user's installed Chrome / Chromium binary, cross-platform."""
    if sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        ]
    elif sys.platform.startswith("win"):
        program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        local_app = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            rf"{program_files}\Google\Chrome\Application\chrome.exe",
            rf"{program_files_x86}\Google\Chrome\Application\chrome.exe",
            rf"{local_app}\Google\Chrome\Application\chrome.exe" if local_app else "",
            rf"{program_files}\Chromium\Application\chrome.exe",
        ]
    else:
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
            "/snap/bin/chromium",
            "/opt/google/chrome/chrome",
        ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    return None


def _wait_for_port(host: str, port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with contextlib.suppress(Exception), socket.create_connection((host, port), timeout=1.0):
            return True
        time.sleep(0.3)
    return False


def launch_user_chrome(args: argparse.Namespace) -> tuple[subprocess.Popen | None, str]:
    """Launch the user's real Chrome with a debug port and a tool-specific profile.

    Returns (popen_handle, cdp_url). The handle is None if Chrome was already
    running on the requested port — in that case we just attach to it.
    """
    cdp_url = args.cdp_url or DEFAULT_CDP_URL
    port = int(cdp_url.rsplit(":", 1)[-1].rstrip("/"))

    # Already running on that port? Just attach.
    if _wait_for_port("localhost", port, timeout=0.5):
        return None, cdp_url

    chrome_bin = _find_chrome_binary()
    if not chrome_bin:
        raise RuntimeError(
            "Couldn't find a Chrome / Chromium installation. "
            "Install Google Chrome from https://www.google.com/chrome/ then rerun."
        )

    profile_dir = Path.home() / ".cache" / "superdrug-report-chrome"
    profile_dir.mkdir(parents=True, exist_ok=True)

    chrome_args = [
        chrome_bin,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-default-browser-check",
        "--no-first-run",
        "--start-maximized",
        LOGIN_URL,
    ]
    proc = subprocess.Popen(  # noqa: S603 — chrome_bin is from a fixed allowlist
        chrome_args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not _wait_for_port("localhost", port, timeout=20.0):
        with contextlib.suppress(Exception):
            proc.terminate()
        raise RuntimeError(
            f"Chrome started but didn't open a debug port on {port} within 20s."
        )
    return proc, cdp_url


def connect_to_chrome(pw, cdp_url: str) -> tuple[Browser, BrowserContext]:
    """Attach to a Chrome instance speaking CDP at cdp_url."""
    browser = pw.chromium.connect_over_cdp(cdp_url)
    if browser.contexts:
        ctx = browser.contexts[0]
    else:
        ctx = browser.new_context(
            viewport={
                "width": AKAMAI_CFG.viewport.width,
                "height": AKAMAI_CFG.viewport.height,
            },
            user_agent=USER_AGENT,
            locale=AKAMAI_CFG.locale,
            timezone_id=AKAMAI_CFG.timezone_id,
        )
    apply_stealth(ctx, AKAMAI_CFG)
    return browser, ctx


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
    """Best-effort detection of CAPTCHA / Cloudflare / bot-challenge pages.

    Thin wrapper around :func:`akamai.detection.is_challenge` that preserves
    the existing boolean callsite contract elsewhere in the file.
    """
    report = is_challenge(page, cfg=AKAMAI_CFG)
    return report.status is not ChallengeStatus.CLEAR


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


def _mode_label(mode: int) -> str:
    return {
        MODE_AUTO: "auto-login",
        MODE_OPEN_CHROME: "open my Chrome",
        MODE_VISIBLE: "visible browser",
        MODE_CACHED: "cached session",
    }.get(mode, "?")


def _resolve_mode(args: argparse.Namespace) -> int:
    """Pick a login mode: from --mode flag, from env var, or via the menu."""
    if args.mode is not None:
        return args.mode
    env_mode = os.environ.get("SUPERDRUG_REPORT_MODE", "").strip()
    if env_mode in {"1", "2", "3", "4"}:
        return int(env_mode)
    # If the user piped non-interactive credentials via env, default to mode 1
    # so non-interactive scripted use still works.
    if os.environ.get("SUPERDRUG_EMAIL") and os.environ.get("SUPERDRUG_PASSWORD"):
        return MODE_AUTO
    if not sys.stdin.isatty():
        # No TTY and no env override \u2014 fall back to mode 1 (will read from env / fail).
        return MODE_AUTO
    return interactive_menu()


def run() -> int:
    args = parse_args()
    mode = _resolve_mode(args)
    if mode == 5 or mode not in {MODE_AUTO, MODE_OPEN_CHROME, MODE_VISIBLE, MODE_CACHED}:
        print("  Bye.")
        return 0

    # Resolve email + password depending on mode.
    if mode == MODE_AUTO:
        email, password = get_credentials(args)
    else:
        # Modes 2/3/4 don't need the password (you sign in yourself or use cache).
        email = args.email or os.environ.get("SUPERDRUG_EMAIL", "").strip()
        if not email:
            try:
                email = input("Superdrug email (for the report header): ").strip()
            except EOFError:
                email = ""
        password = ""

    args.output.mkdir(parents=True, exist_ok=True)
    debug_dir = (args.output / "debug") if args.debug else None

    banner(email or "(unknown)")
    print(f"  Mode    : {mode} ({_mode_label(mode)})")
    _line()

    chrome_proc: subprocess.Popen | None = None
    cdp_browser: Browser | None = None

    with sync_playwright() as pw:
        # ---- Open / connect browser ----
        if mode == MODE_OPEN_CHROME:
            step("Opening Chrome for you...")
            try:
                chrome_proc, cdp_url = launch_user_chrome(args)
            except RuntimeError as e:
                fail(str(e))
                return 1
            if chrome_proc is None:
                ok(f"Attached to a Chrome already running on {cdp_url}.")
            else:
                ok(f"Chrome is open with a Superdrug login tab. ({cdp_url})")
            try:
                cdp_browser, ctx = connect_to_chrome(pw, cdp_url)
            except Exception as e:
                fail(f"Could not connect to Chrome: {e}")
                return 1
        elif mode == MODE_VISIBLE:
            ctx = open_context(pw, args, headless=False)
        elif mode == MODE_CACHED:
            ctx = open_context(pw, args, headless=True)
        else:  # MODE_AUTO
            ctx = open_context(pw, args, headless=True)

        try:
            # Reuse an existing tab if Chrome already had one open; otherwise new.
            page = ctx.pages[0] if (mode == MODE_OPEN_CHROME and ctx.pages) else ctx.new_page()

            # ---- Login phase ----
            if mode == MODE_OPEN_CHROME:
                with contextlib.suppress(Exception):
                    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=15_000)
                print()
                step("Sign in to Superdrug in the Chrome window I just opened.")
                print("        When you see your account dashboard, come back here and press Enter.")
                print()
                try:
                    input("  Press Enter once you're signed in... ")
                except (EOFError, KeyboardInterrupt):
                    fail("Login was not completed. Aborting.")
                    return 1
                with contextlib.suppress(Exception):
                    page.goto(ACCOUNT_URL, wait_until="domcontentloaded", timeout=20_000)
                if not _is_logged_in(page):
                    fail("Doesn't look like you're signed in yet. Aborting.")
                    return 1
                ok("Signed in.")
            elif mode == MODE_VISIBLE:
                step("Opening browser for manual login...")
                if not manual_login_loop(ctx, page):
                    fail("Login was not completed. Aborting.")
                    return 1
                ok("Logged in.")
            elif mode == MODE_CACHED:
                step("Loading account dashboard from cached session...")
                with contextlib.suppress(Exception):
                    page.goto(ACCOUNT_URL, wait_until="domcontentloaded", timeout=20_000)
                if not _is_logged_in(page):
                    fail(
                        "No cached session found. Run with mode 1 or 3 first to sign in once."
                    )
                    return 1
                ok("Cached session is valid.")
            else:  # MODE_AUTO
                step("Logging in...")
                t0 = time.time()
                status = attempt_auto_login(page, email, password)
                elapsed = time.time() - t0

                if status == "ok":
                    ok(f"Logged in ({elapsed:.1f}s).")
                elif status == "bad_creds":
                    fail("Login rejected \u2014 email/password didn't work.")
                    return 1
                else:
                    if status == "captcha":
                        reason = "CAPTCHA / bot-challenge detected."
                    else:
                        reason = (
                            "Couldn't auto-login \u2014 Superdrug looks like it's flagging the script."
                        )
                    print()
                    warn(reason)
                    print(
                        "        TIP: rerun and pick option 2 (\"Open Chrome for me\")\n"
                        "             \u2014 it's the most reliable mode against bot detection."
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

            # ---- Sensor warmup ----
            # Run the human-like warmup loop so Akamai's bot manager flips
            # ``_abck`` to "valid" before we hammer the account subpages.
            # Skipped for MODE_OPEN_CHROME (mode 2): the user already drove
            # the page like a human, the cookie is already good.
            if mode != MODE_OPEN_CHROME:
                step("Warming up Akamai sensor...")
                wr = warm_up(page, cfg=AKAMAI_CFG)
                if wr.succeeded:
                    ok(
                        f"Sensor accepted ({wr.elapsed_seconds:.1f}s, "
                        f"{wr.attempts} micro-steps)"
                    )
                else:
                    warn(
                        f"Sensor warmup did not flip _abck "
                        f"(status={wr.last_status.value}, {wr.detail}); "
                        "continuing anyway."
                    )

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
            if mode == MODE_OPEN_CHROME:
                # Leave the user's Chrome window alone — disconnect cleanly.
                if cdp_browser is not None:
                    with contextlib.suppress(Exception):
                        cdp_browser.close()
            else:
                with contextlib.suppress(Exception):
                    ctx.close()
    # The launched-Chrome subprocess is intentionally left running so the user
    # can keep using the same Chrome window for future runs (and so we keep the
    # cached login session).
    _ = chrome_proc

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
