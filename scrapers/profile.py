"""Profile / personal details scraper."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page

from .base import BASE, dump_debug, extract_fields, main_content_text, try_urls

CANDIDATE_URLS = [
    f"{BASE}/my-account/personal-details",
    f"{BASE}/my-account/personal-details/",
    f"{BASE}/my-account/profile",
    f"{BASE}/my-account",
]


def scrape(page: Page, debug_dir: Path | None = None) -> dict:
    final = try_urls(page, CANDIDATE_URLS)
    if final is None:
        return {"status": "error", "url": None, "fields": {}, "items": [],
                "raw_text": "", "error": "could not load profile page"}

    page.wait_for_timeout(500)
    text = main_content_text(page)
    dump_debug(debug_dir, "profile", page)

    fields = extract_fields(text)

    # Superdrug often renders name as a big heading above the field list.
    if "Name" not in fields:
        h = page.query_selector("h1")
        if h:
            val = (h.inner_text() or "").strip()
            # Skip generic headings like "My Account"
            if val and val.lower() not in {"my account", "personal details", "welcome"}:
                fields["Name"] = val

    # Try to find email from the page if not labelled
    if "Email" not in fields:
        email_node = page.query_selector("[data-testid*=email], input[type=email]")
        if email_node:
            val = (email_node.get_attribute("value") or email_node.inner_text() or "").strip()
            if "@" in val:
                fields["Email"] = val

    return {
        "status": "ok" if fields or text else "error",
        "url": final,
        "fields": fields,
        "items": [],
        "raw_text": text,
    }
