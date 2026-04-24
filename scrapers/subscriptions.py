"""Subscribe & Save / subscription scraper."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page

from .base import BASE, dump_debug, main_content_text, try_urls

CANDIDATE_URLS = [
    f"{BASE}/my-account/subscriptions",
    f"{BASE}/my-account/subscriptions/",
    f"{BASE}/my-account/subscribe-and-save",
]


def scrape(page: Page, debug_dir: Path | None = None) -> dict:
    final = try_urls(page, CANDIDATE_URLS)
    if final is None:
        return {"status": "skipped", "url": None, "fields": {}, "items": [],
                "raw_text": "", "error": "no subscriptions page"}

    page.wait_for_timeout(500)
    text = main_content_text(page)
    dump_debug(debug_dir, "subscriptions", page)

    items: list[dict] = []
    for sel in ("[data-testid*=subscription]", ".subscription-card", "li.subscription"):
        nodes = page.query_selector_all(sel)
        if nodes:
            for n in nodes:
                raw = (n.inner_text() or "").strip()
                if raw:
                    items.append({"raw": raw})
            break

    return {
        "status": "ok" if items else "empty",
        "url": final,
        "fields": {"count": str(len(items))},
        "items": items,
        "raw_text": text,
    }
