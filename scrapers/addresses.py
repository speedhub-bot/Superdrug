"""Saved addresses scraper."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page

from .base import BASE, dump_debug, main_content_text, try_urls

CANDIDATE_URLS = [
    f"{BASE}/my-account/addresses",
    f"{BASE}/my-account/addresses/",
    f"{BASE}/my-account/address-book",
]


def scrape(page: Page, debug_dir: Path | None = None) -> dict:
    final = try_urls(page, CANDIDATE_URLS)
    if final is None:
        return {"status": "skipped", "url": None, "fields": {}, "items": [],
                "raw_text": "", "error": "no addresses page"}

    page.wait_for_timeout(500)
    text = main_content_text(page)
    dump_debug(debug_dir, "addresses", page)

    items: list[dict] = []

    # Try structured selectors that Superdrug has historically used.
    for sel in (
        "[data-testid*=address-card]",
        ".address-card",
        ".address-book-item",
        "li.address",
        ".addresses__item",
    ):
        nodes = page.query_selector_all(sel)
        if nodes:
            for n in nodes:
                raw = (n.inner_text() or "").strip()
                if not raw:
                    continue
                lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
                label = ""
                if lines and lines[0].lower() in {"default", "default delivery", "default billing",
                                                  "delivery", "billing"}:
                    label = lines.pop(0)
                items.append({
                    "label": label,
                    "lines": lines,
                })
            break

    # Fallback: split the visible text into paragraphs, keep any that look
    # address-y (contain a postcode).
    if not items:
        blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
        uk_postcode = __import__("re").compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b")
        for b in blocks:
            if uk_postcode.search(b):
                items.append({"label": "", "lines": [ln.strip() for ln in b.splitlines() if ln.strip()]})

    return {
        "status": "ok" if items else "empty",
        "url": final,
        "fields": {"count": str(len(items))},
        "items": items,
        "raw_text": text,
    }
