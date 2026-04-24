"""Order history scraper."""

from __future__ import annotations

import contextlib
import re
from pathlib import Path

from playwright.sync_api import Page

from .base import BASE, dump_debug, main_content_text, safe_goto, try_urls

LIST_URLS = [
    f"{BASE}/my-account/my-orders",
    f"{BASE}/my-account/my-orders/",
    f"{BASE}/my-account/orders",
]

_ORDER_NO_RE = re.compile(r"\border(?:\s*(?:no\.?|number|#))?[\s:#]*([A-Z0-9\-]{5,})", re.I)
_MONEY_RE = re.compile(r"£\s*\d+(?:\.\d{2})?")
_DATE_RE = re.compile(
    r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{4}|"
    r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\b"
)


def scrape(page: Page, debug_dir: Path | None = None) -> dict:
    final = try_urls(page, LIST_URLS)
    if final is None:
        return {"status": "error", "url": None, "fields": {}, "items": [],
                "raw_text": "", "error": "could not load order history"}

    page.wait_for_timeout(500)
    list_text = main_content_text(page)
    dump_debug(debug_dir, "orders_list", page)

    # Collect links to individual order pages.
    order_links: list[tuple[str, str]] = []  # (label, href)
    for a in page.query_selector_all("a"):
        href = a.get_attribute("href") or ""
        if not href:
            continue
        if "/my-orders/" in href or "/my-account/order/" in href or "/order-details" in href:
            label = (a.inner_text() or "").strip() or href
            if href.startswith("/"):
                href = f"{BASE}{href}"
            order_links.append((label, href))

    # Deduplicate by href, preserve order
    seen: set[str] = set()
    order_links = [(lbl, h) for (lbl, h) in order_links if not (h in seen or seen.add(h))]

    # Page through "next" / "load more" buttons up to a sane cap.
    _collect_more_orders(page, order_links, seen)

    items: list[dict] = []
    if order_links:
        for idx, (_label, href) in enumerate(order_links, 1):
            item = _scrape_order_detail(page, href, debug_dir=debug_dir, idx=idx)
            if item:
                items.append(item)
    else:
        # Fallback: parse order rows from the list page's text.
        for block in list_text.split("\n\n"):
            b = block.strip()
            if _ORDER_NO_RE.search(b) or _MONEY_RE.search(b):
                items.append(_parse_order_block(b))

    # Aggregate summary
    total_spend = 0.0
    for it in items:
        t = it.get("total", "")
        if m := re.search(r"(\d+(?:\.\d+)?)", t.replace(",", "")):
            with contextlib.suppress(ValueError):
                total_spend += float(m.group(1))

    return {
        "status": "ok" if items else "empty",
        "url": final,
        "fields": {
            "count": str(len(items)),
            "lifetime_spend": f"£{total_spend:,.2f}" if total_spend else "",
        },
        "items": items,
        "raw_text": list_text,
    }


def _collect_more_orders(page: Page, acc: list[tuple[str, str]], seen: set[str]) -> None:
    for _ in range(20):  # safety cap
        clicked = False
        for sel in ("button:has-text('Load more')", "button:has-text('Show more')",
                    "a:has-text('Next')", "button:has-text('Next')"):
            btn = page.query_selector(sel)
            if btn and btn.is_enabled():
                try:
                    btn.click()
                    page.wait_for_timeout(800)
                    clicked = True
                    break
                except Exception:
                    continue
        if not clicked:
            break
        for a in page.query_selector_all("a"):
            href = a.get_attribute("href") or ""
            if not href:
                continue
            if "/my-orders/" in href or "/my-account/order/" in href or "/order-details" in href:
                label = (a.inner_text() or "").strip() or href
                if href.startswith("/"):
                    href = f"{BASE}{href}"
                if href not in seen:
                    seen.add(href)
                    acc.append((label, href))


def _scrape_order_detail(page: Page, href: str, *, debug_dir: Path | None, idx: int) -> dict | None:
    if not safe_goto(page, href):
        return None
    page.wait_for_timeout(400)
    dump_debug(debug_dir, f"order_{idx:04d}", page)
    text = main_content_text(page)

    item = _parse_order_block(text)
    item["url"] = href

    # Line items: look for structured product rows on the detail page.
    lines: list[dict] = []
    for sel in ("[data-testid*=order-line]", ".order-line-item", "tr.order-item", ".line-item"):
        nodes = page.query_selector_all(sel)
        if nodes:
            for n in nodes:
                raw = (n.inner_text() or "").strip()
                if raw:
                    lines.append({"raw": " | ".join(ln.strip() for ln in raw.splitlines() if ln.strip())})
            break
    if lines:
        item["lines"] = lines

    return item


def _parse_order_block(block: str) -> dict:
    d: dict[str, str | list] = {
        "order_no": "",
        "date": "",
        "status": "",
        "total": "",
        "raw": block,
    }
    if m := _ORDER_NO_RE.search(block):
        d["order_no"] = m.group(1)
    if m := _DATE_RE.search(block):
        d["date"] = m.group(1)
    totals = _MONEY_RE.findall(block)
    if totals:
        d["total"] = totals[-1]  # last money figure is usually the grand total

    for line in block.splitlines():
        s = line.strip().lower()
        for status in ("delivered", "dispatched", "processing", "cancelled", "refunded",
                       "returned", "pending", "on its way", "out for delivery"):
            if status in s and len(line) < 80:
                d["status"] = line.strip()
                break
        if d["status"]:
            break

    return d
