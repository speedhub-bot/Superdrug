"""Render a collected account-data dict as a neatly-formatted .txt report."""

from __future__ import annotations

from datetime import datetime
from textwrap import wrap

LINE = "=" * 72
SUB = "-" * 72


def _header(title: str) -> str:
    return f"{LINE}\n  {title.upper()}\n{LINE}"


def _subheader(title: str) -> str:
    return f"\n{SUB}\n  {title}\n{SUB}"


def _kv(key: str, value: str, *, width: int = 22) -> str:
    if value is None:
        value = ""
    value = str(value)
    key_part = f"  {key:<{width}} : "
    lines = value.splitlines() or [""]
    first = f"{key_part}{lines[0]}"
    rest = [" " * len(key_part) + ln for ln in lines[1:]]
    return "\n".join([first, *rest])


def _render_fields(fields: dict[str, str]) -> str:
    if not fields:
        return "  (no fields parsed)"
    width = max((len(k) for k in fields), default=22)
    width = min(max(width, 10), 30)
    return "\n".join(_kv(k, v, width=width) for k, v in fields.items())


def _render_raw(raw: str, *, indent: str = "    ") -> str:
    if not raw:
        return ""
    out: list[str] = []
    for ln in raw.splitlines():
        if len(ln) <= 72:
            out.append(f"{indent}{ln}")
        else:
            for chunk in wrap(ln, width=72, break_long_words=False, replace_whitespace=False):
                out.append(f"{indent}{chunk}")
    return "\n".join(out)


def _render_address(item: dict, n: int) -> str:
    label = item.get("label") or f"Address #{n}"
    lines = item.get("lines") or []
    body = "\n".join(f"    {ln}" for ln in lines) if lines else "    (empty)"
    return f"  [{n}] {label}\n{body}"


def _render_payment(item: dict, n: int) -> str:
    brand = item.get("brand") or "Unknown"
    last4 = item.get("last4") or "????"
    expiry = item.get("expiry") or "--/--"
    line = f"  [{n}] {brand}  ****{last4}   exp {expiry}"
    raw = item.get("raw") or ""
    if raw and raw.lower() not in line.lower():
        line += f"\n        raw: {raw}"
    return line


def _render_order(item: dict, n: int) -> str:
    head = (
        f"  [{n}] Order {item.get('order_no') or '(no number)'}"
        f"   date: {item.get('date') or '—'}"
        f"   status: {item.get('status') or '—'}"
        f"   total: {item.get('total') or '—'}"
    )
    parts = [head]
    url = item.get("url")
    if url:
        parts.append(f"        url: {url}")
    lines = item.get("lines") or []
    for li in lines:
        raw = li.get("raw", "") if isinstance(li, dict) else str(li)
        if raw:
            parts.append(f"        • {raw}")
    return "\n".join(parts)


def _render_section(title: str, data: dict) -> str:
    out: list[str] = [_subheader(title)]
    status = data.get("status", "unknown")
    url = data.get("url") or ""
    out.append(f"  Source URL : {url}")
    out.append(f"  Status     : {status}")

    if err := data.get("error"):
        out.append(f"  Error      : {err}")
        out.append("")
        return "\n".join(out)

    fields = data.get("fields") or {}
    items = data.get("items") or []

    t = title.lower()
    if "address" in t:
        out.append("")
        out.append(_kv("Address count", fields.get("count", str(len(items)))))
        out.append("")
        for i, it in enumerate(items, 1):
            out.append(_render_address(it, i))
            out.append("")
    elif "payment" in t:
        out.append("")
        out.append(_kv("Saved cards", fields.get("count", str(len(items)))))
        out.append("")
        for i, it in enumerate(items, 1):
            out.append(_render_payment(it, i))
        out.append("")
    elif "order" in t:
        out.append("")
        out.append(_kv("Order count", fields.get("count", str(len(items)))))
        if fields.get("lifetime_spend"):
            out.append(_kv("Lifetime spend", fields["lifetime_spend"]))
        out.append("")
        for i, it in enumerate(items, 1):
            out.append(_render_order(it, i))
            out.append("")
    else:
        out.append("")
        if fields:
            out.append(_render_fields(fields))
            out.append("")
        for i, it in enumerate(items, 1):
            if isinstance(it, dict):
                raw = it.get("raw") or it.get("voucher") or next(
                    (str(v) for v in it.values() if v), ""
                )
            else:
                raw = str(it)
            if raw:
                out.append(f"  [{i}] {raw}")
        if items:
            out.append("")

    # Always include a truncated raw dump as a fallback so no info is lost.
    raw = data.get("raw_text") or ""
    if raw:
        out.append("  -- raw visible text --")
        out.append(_render_raw(raw[:4000]))
        if len(raw) > 4000:
            out.append(f"    ...[truncated, {len(raw) - 4000} more chars]")
        out.append("")

    return "\n".join(out)


def render(collected: dict) -> str:
    """``collected`` is the top-level dict produced by superdrug_report.py."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    email = collected.get("account_email") or "(unknown)"
    sections: dict[str, dict] = collected.get("sections", {})

    # ---- Summary ----
    profile = sections.get("Profile", {}) or {}
    beauty = sections.get("Health & Beautycard", {}) or {}
    orders = sections.get("Order History", {}) or {}

    profile_fields = profile.get("fields", {}) or {}
    beauty_fields = beauty.get("fields", {}) or {}
    orders_fields = orders.get("fields", {}) or {}

    parts: list[str] = []
    parts.append(_header("Superdrug Account Report"))
    parts.append(_kv("Account email", email))
    parts.append(_kv("Report generated", now))
    parts.append(_kv("Name on file", profile_fields.get("Name", "—")))
    parts.append(_kv("Points balance", beauty_fields.get("Points Balance", "—")))
    parts.append(_kv("Lifetime orders", orders_fields.get("count", "—")))
    parts.append(_kv("Lifetime spend", orders_fields.get("lifetime_spend", "—")))
    parts.append("")

    # ---- All sections ----
    for section_title, data in sections.items():
        parts.append(_render_section(section_title, data))

    parts.append(LINE)
    parts.append("  End of report")
    parts.append(LINE)
    return "\n".join(parts) + "\n"
