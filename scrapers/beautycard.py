"""Health & Beautycard scraper (loyalty card info)."""

from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import Page

from .base import BASE, dump_debug, extract_fields, main_content_text, try_urls

CANDIDATE_URLS = [
    f"{BASE}/my-account/beautycard",
    f"{BASE}/my-account/beautycard/",
    f"{BASE}/my-account/health-and-beautycard",
    f"{BASE}/my-account/loyalty",
]

_POINTS_RE = re.compile(r"(?:points?\s+balance|your\s+points|balance)[^\d]{0,20}(\d[\d,]*)", re.I)
_CARD_NO_RE = re.compile(r"(?:card\s*(?:number|no\.?))[^\d]{0,10}([\d\s]{10,24})", re.I)
_TIER_RE = re.compile(r"(?:tier|level|status)[^\w]{0,6}([A-Za-z][\w &]{2,30})", re.I)


def scrape(page: Page, debug_dir: Path | None = None) -> dict:
    final = try_urls(page, CANDIDATE_URLS)
    if final is None:
        return {"status": "skipped", "url": None, "fields": {}, "items": [],
                "raw_text": "", "error": "no beautycard page"}

    page.wait_for_timeout(500)
    text = main_content_text(page)
    dump_debug(debug_dir, "beautycard", page)

    fields = extract_fields(text)

    if m := _POINTS_RE.search(text):
        fields.setdefault("Points Balance", m.group(1).replace(",", ""))
    if m := _CARD_NO_RE.search(text):
        fields.setdefault("Card Number", m.group(1).strip())
    if m := _TIER_RE.search(text):
        fields.setdefault("Tier", m.group(1).strip())

    # Vouchers: any ``£X off`` / ``X% off`` lines
    vouchers = []
    for line in text.splitlines():
        s = line.strip()
        if re.search(r"£\s*\d+|\b\d+%\s*off\b", s, re.I) and 3 <= len(s) <= 120:
            vouchers.append(s)
    # dedupe preserving order
    seen = set()
    vouchers = [v for v in vouchers if not (v in seen or seen.add(v))]

    return {
        "status": "ok",
        "url": final,
        "fields": fields,
        "items": [{"voucher": v} for v in vouchers],
        "raw_text": text,
    }
