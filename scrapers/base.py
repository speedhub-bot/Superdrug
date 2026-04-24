"""Shared scraper helpers."""

from __future__ import annotations

import contextlib
import re
from collections.abc import Iterable
from pathlib import Path

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PWTimeout

BASE = "https://www.superdrug.com"
DEFAULT_TIMEOUT_MS = 20_000


def safe_goto(page: Page, url: str, *, wait: str = "networkidle") -> bool:
    """Navigate to ``url`` and return True on success. Never raises."""
    try:
        page.goto(url, wait_until=wait, timeout=DEFAULT_TIMEOUT_MS)
        return True
    except PWTimeout:
        # networkidle can hang on marketing pixels — fall back to DOMContentLoaded
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
            return True
        except Exception:
            return False
    except Exception:
        return False


def main_content_text(page: Page) -> str:
    """Return the visible text of the most likely 'main content' region.

    Falls back to ``body.inner_text()`` if no main region is identifiable.
    """
    for sel in ("main", "[role=main]", "#main-content", ".main-content", ".account-content"):
        node = page.query_selector(sel)
        if node:
            txt = (node.inner_text() or "").strip()
            if txt:
                return _clean_text(txt)
    body = page.query_selector("body")
    return _clean_text((body.inner_text() if body else "") or "")


def _clean_text(s: str) -> str:
    # Collapse runs of blank lines and strip trailing whitespace on each line
    lines = [ln.rstrip() for ln in s.splitlines()]
    out: list[str] = []
    blank = 0
    for ln in lines:
        if ln.strip():
            out.append(ln)
            blank = 0
        else:
            blank += 1
            if blank <= 1:
                out.append("")
    return "\n".join(out).strip()


_LABEL_RE = re.compile(
    r"^\s*([A-Z][A-Za-z0-9 &/\-]{1,40}?)\s*[:\u2013\-]\s*(.+?)\s*$"
)


def extract_fields(text: str) -> dict[str, str]:
    """Heuristically pull 'Label: value' pairs out of visible page text."""
    fields: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or len(line) > 200:
            continue
        m = _LABEL_RE.match(line)
        if m:
            key = m.group(1).strip()
            val = m.group(2).strip()
            if key and val and val.lower() not in {"edit", "change", "remove", "view"}:
                # Keep first occurrence; later duplicates (e.g. footer) are ignored.
                fields.setdefault(key, val)
    return fields


def dump_debug(debug_dir: Path | None, name: str, page: Page) -> None:
    if not debug_dir:
        return
    debug_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
    with contextlib.suppress(Exception):
        (debug_dir / f"{safe_name}.html").write_text(page.content(), encoding="utf-8")
    with contextlib.suppress(Exception):
        (debug_dir / f"{safe_name}.txt").write_text(main_content_text(page), encoding="utf-8")


def try_urls(page: Page, urls: Iterable[str]) -> str | None:
    """Try each URL in order; return the first that loads into a non-redirect page."""
    for url in urls:
        if safe_goto(page, url):
            # If Superdrug bounced us to /login we're not logged in for this page
            if "/login" in page.url.lower() or "/account/login" in page.url.lower():
                continue
            return page.url
    return None
