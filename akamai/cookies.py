"""Akamai cookie parsing.

Akamai Bot Manager (ABM) tracks a session via three cookies:

* ``_abck``    — the verdict cookie. Tilde-separated. The 4th piece (index 3)
  is ``-1`` while the script is unsure / has flagged you, and ``0`` once your
  sensor data has been accepted. This is the single most useful signal.
* ``bm_sz``    — short-lived rotating session token (set on first response).
* ``ak_bmsc``  — long-lived session id; not always present on every site.

Nothing in here decrypts or replays the cookies — we only *read* them so the
rest of the toolkit can decide "is the session unblocked?" / "do we need to
warm up again?".
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class AbckCookie:
    """Parsed view of the ``_abck`` cookie."""

    raw: str
    parts: tuple[str, ...]
    valid: bool
    flag: str  # the index-3 piece, "" if missing

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return self.valid


@dataclass(frozen=True)
class AkamaiCookies:
    """Snapshot of Akamai-relevant cookies pulled from a browser context."""

    abck: AbckCookie | None
    bm_sz: str | None
    ak_bmsc: str | None
    bm_sv: str | None
    bm_mi: str | None

    @property
    def has_session(self) -> bool:
        """True if at least the bare-minimum Akamai cookie pair is present."""
        return self.abck is not None and self.bm_sz is not None

    @property
    def is_valid(self) -> bool:
        """True if Akamai considers the current session "good"."""
        return bool(self.abck and self.abck.valid)


def parse_abck(value: str) -> AbckCookie:
    """Parse an ``_abck`` cookie value into a structured view.

    The cookie format is informally:

        ``<version>~<sensor_hash>~<flag>~<more...>~~``

    where ``flag`` is the index-3 tilde piece. Akamai sets it to ``"-1"`` while
    the session is "still being judged" (or has been ruled bad) and ``"0"``
    once the script accepts your sensor-data POST. Anything that isn't ``"-1"``
    we treat as "valid" — Akamai occasionally uses non-zero positive flags for
    short windows during a session.
    """
    raw = (value or "").strip()
    if not raw:
        return AbckCookie(raw="", parts=(), valid=False, flag="")

    parts = tuple(raw.split("~"))
    flag = parts[3] if len(parts) >= 4 else ""
    valid = bool(parts) and flag != "" and flag != "-1"
    return AbckCookie(raw=raw, parts=parts, valid=valid, flag=flag)


def is_abck_valid(value: str) -> bool:
    """Convenience wrapper around :func:`parse_abck`."""
    return parse_abck(value).valid


# ---------------------------------------------------------------------------
# Playwright integration
# ---------------------------------------------------------------------------


def _select(name: str, jar: Iterable[Mapping[str, object]]) -> str | None:
    """Return the first cookie value with ``name`` from a Playwright cookie jar."""
    needle = name.lower()
    for c in jar:
        if str(c.get("name", "")).lower() == needle:
            return str(c.get("value", ""))
    return None


def extract_cookies(jar: Iterable[Mapping[str, object]]) -> AkamaiCookies:
    """Build :class:`AkamaiCookies` from a Playwright ``context.cookies()`` list.

    The input is the loose ``list[dict]`` shape Playwright returns; we don't
    take a hard dependency on Playwright types so this can also be unit-tested
    with plain dicts.
    """
    jar_list = list(jar)
    abck_raw = _select("_abck", jar_list)
    abck = parse_abck(abck_raw) if abck_raw else None
    return AkamaiCookies(
        abck=abck,
        bm_sz=_select("bm_sz", jar_list),
        ak_bmsc=_select("ak_bmsc", jar_list),
        bm_sv=_select("bm_sv", jar_list),
        bm_mi=_select("bm_mi", jar_list),
    )


def cookies_to_header(jar: Iterable[Mapping[str, object]]) -> str:
    """Render a Playwright cookie jar as a single ``Cookie:`` header string.

    Useful for forwarding the warmed-up session to ``curl_cffi`` /
    ``requests`` for raw API calls.
    """
    pieces: list[str] = []
    for c in jar:
        n = str(c.get("name", "")).strip()
        v = str(c.get("value", ""))
        if n:
            pieces.append(f"{n}={v}")
    return "; ".join(pieces)
