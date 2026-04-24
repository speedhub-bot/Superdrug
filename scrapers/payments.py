"""Saved payment methods scraper.

Only returns what Superdrug itself renders to the account holder — card brand,
expiry, and the last 4 digits. Full card numbers (PAN) are never stored by the
retailer in a way that's exposed to the account page, and this scraper will
NOT attempt to recover them.
"""

from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import Page

from .base import BASE, dump_debug, main_content_text, try_urls

CANDIDATE_URLS = [
    f"{BASE}/my-account/payment-details",
    f"{BASE}/my-account/payment-details/",
    f"{BASE}/my-account/payment-methods",
    f"{BASE}/my-account/saved-cards",
]

_BRAND_RE = re.compile(r"\b(visa|mastercard|maestro|amex|american express|discover|paypal)\b", re.I)
_LAST4_RE = re.compile(r"(?:ending(?:\s+in)?|\*{2,}|•{2,}|\u2022{2,}|xxxx)\s*(\d{4})", re.I)
_EXPIRY_RE = re.compile(r"\b(0[1-9]|1[0-2])\s*[/\-]\s*(\d{2,4})\b")


def scrape(page: Page, debug_dir: Path | None = None) -> dict:
    final = try_urls(page, CANDIDATE_URLS)
    if final is None:
        return {"status": "skipped", "url": None, "fields": {}, "items": [],
                "raw_text": "", "error": "no payments page"}

    page.wait_for_timeout(500)
    text = main_content_text(page)
    dump_debug(debug_dir, "payments", page)

    items: list[dict] = []

    for sel in (
        "[data-testid*=payment-card]",
        ".payment-card",
        ".saved-card",
        "li.payment-method",
    ):
        nodes = page.query_selector_all(sel)
        if nodes:
            for n in nodes:
                raw = (n.inner_text() or "").strip()
                if not raw:
                    continue
                items.append(_parse_card_text(raw))
            break

    if not items:
        # Split visible text into blocks and pick any that look card-ish.
        for block in text.split("\n\n"):
            b = block.strip()
            if _BRAND_RE.search(b) or _LAST4_RE.search(b):
                items.append(_parse_card_text(b))

    return {
        "status": "ok" if items else "empty",
        "url": final,
        "fields": {"count": str(len(items))},
        "items": items,
        "raw_text": text,
    }


def _parse_card_text(raw: str) -> dict:
    brand = ""
    last4 = ""
    expiry = ""

    if m := _BRAND_RE.search(raw):
        brand = m.group(1).title()
    if m := _LAST4_RE.search(raw):
        last4 = m.group(1)
    if m := _EXPIRY_RE.search(raw):
        expiry = f"{m.group(1)}/{m.group(2)}"

    return {
        "brand": brand,
        "last4": last4,
        "expiry": expiry,
        "raw": " | ".join(
            ln.strip() for ln in raw.splitlines() if ln.strip()
        ),
    }
