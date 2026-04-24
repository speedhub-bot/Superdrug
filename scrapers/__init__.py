"""Account-page scrapers.

Each module exposes a ``scrape(page, debug_dir=None) -> dict`` function that
navigates the already-logged-in ``playwright.sync_api.Page`` to the relevant
Superdrug account subpage and returns a structured dict of the form::

    {
        "status": "ok" | "skipped" | "error",
        "url": "<final url>",
        "fields": {...},      # parsed structured fields (may be empty)
        "items": [...],       # list-style data if the page is list-shaped
        "raw_text": "...",    # visible text of the main content area
        "error": "<message>", # only present when status == "error"
    }

The report renderer (see ``report.py``) decides how to display each section
based on whichever of ``fields`` / ``items`` / ``raw_text`` is populated.
"""

from . import addresses, beautycard, orders, payments, profile, subscriptions

ALL_SCRAPERS = [
    ("Profile", profile),
    ("Health & Beautycard", beautycard),
    ("Saved Addresses", addresses),
    ("Saved Payment Methods", payments),
    ("Subscriptions", subscriptions),
    ("Order History", orders),
]
