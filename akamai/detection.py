"""Challenge / block detection for Akamai-protected pages.

This is a thin wrapper around heuristics — URL substrings, visible text
needles, common challenge DOM markers and HTTP status codes — but the
``ChallengeReport`` it returns is structured so callers can act on the
*kind* of challenge ("Akamai interstitial" vs "generic CAPTCHA") instead
of just "blocked yes/no".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .config import BypassConfig, ChallengeStatus, default_config

if TYPE_CHECKING:  # pragma: no cover - only used for type hints
    from playwright.sync_api import Page, Response


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChallengeReport:
    """Outcome of a challenge probe."""

    status: ChallengeStatus
    url: str
    matched: tuple[str, ...]    # debug breadcrumbs ("text:press and hold", ...)
    http_status: int | None = None

    @property
    def blocked(self) -> bool:
        return self.status not in (ChallengeStatus.CLEAR, ChallengeStatus.UNKNOWN)

    @property
    def clear(self) -> bool:
        return self.status is ChallengeStatus.CLEAR


# Common DOM markers that show a CAPTCHA / interactive challenge.
_CHALLENGE_DOM_SELECTORS: tuple[str, ...] = (
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    "iframe[src*='turnstile']",
    "iframe[src*='/_Incapsula_Resource']",
    "iframe[src*='challenges.cloudflare']",
    "iframe[src*='akam']",
    "div.g-recaptcha",
    "div.h-captcha",
    "div#cf-please-wait",
    "div#challenge-stage",
    "[data-sitekey]",
    "[data-callback='onSubmit']",
    "[id^='px-captcha']",   # PerimeterX (sometimes co-deployed)
)


# ---------------------------------------------------------------------------
# Helpers (string-only — easy to unit-test without Playwright)
# ---------------------------------------------------------------------------


def _classify_text(text: str, cfg: BypassConfig) -> tuple[ChallengeStatus, list[str]]:
    """Classify a blob of visible text. Returns the status + matched needles."""
    matched: list[str] = []
    if not text:
        return ChallengeStatus.UNKNOWN, matched

    lower = text.lower()
    has_akamai = "akamai" in lower or "reference&#" in lower or "ref:" in lower
    has_cloudflare = "cloudflare" in lower or "checking your browser" in lower
    captcha_terms = (
        "verify you are human",
        "i'm not a robot",
        "complete the security check",
        "press and hold",
        "captcha",
        "needs to review the security",
    )
    block_terms = (
        "access denied",
        "you don't have permission",
        "request unsuccessful",
    )

    for needle in cfg.challenge_text_needles:
        if needle in lower:
            matched.append(f"text:{needle}")

    if has_akamai and ("denied" in lower or "ref:" in lower or "blocked" in lower):
        return ChallengeStatus.AKAMAI, matched
    if has_cloudflare:
        return ChallengeStatus.CLOUDFLARE, matched
    if any(t in lower for t in captcha_terms):
        return ChallengeStatus.CAPTCHA, matched
    if any(t in lower for t in block_terms):
        return ChallengeStatus.BLOCKED, matched
    if has_akamai:
        return ChallengeStatus.AKAMAI, matched
    if matched:
        return ChallengeStatus.CAPTCHA, matched
    return ChallengeStatus.CLEAR, matched


def _classify_url(url: str, cfg: BypassConfig) -> tuple[ChallengeStatus | None, list[str]]:
    """Classify by URL alone (case-insensitive on both sides)."""
    matched: list[str] = []
    lower = (url or "").lower()
    for sub in cfg.challenge_url_substrings:
        if sub.lower() in lower:
            matched.append(f"url:{sub}")
    if not matched:
        return None, matched
    if "cloudflare" in lower or "/cdn-cgi/" in lower:
        return ChallengeStatus.CLOUDFLARE, matched
    if "incapsula" in lower or "/akam/" in lower or "akamai.com" in lower:
        return ChallengeStatus.AKAMAI, matched
    return ChallengeStatus.CAPTCHA, matched


# ---------------------------------------------------------------------------
# Playwright-backed entry points
# ---------------------------------------------------------------------------


def is_challenge(
    page: Page,
    *,
    cfg: BypassConfig | None = None,
    response: Response | None = None,
) -> ChallengeReport:
    """Inspect a Playwright page and return a :class:`ChallengeReport`.

    ``response`` is optional — if you have the navigation Response handy, pass
    it so we can also key off the HTTP status code.
    """
    cfg = cfg or default_config()
    url = page.url or ""
    matched: list[str] = []

    # 1) URL pattern.
    url_status, url_match = _classify_url(url, cfg)
    matched.extend(url_match)

    # 2) HTTP status (if available).
    http_status = None
    if response is not None:
        try:
            http_status = response.status
        except Exception:
            http_status = None
    if http_status in cfg.blocked_status_codes:
        matched.append(f"http:{http_status}")

    # 3) DOM markers.
    dom_match: str | None = None
    for sel in _CHALLENGE_DOM_SELECTORS:
        try:
            if page.query_selector(sel):
                dom_match = sel
                matched.append(f"dom:{sel}")
                break
        except Exception:
            continue

    # 4) Visible text.
    text = ""
    try:
        body = page.query_selector("body")
        if body is not None:
            text = (body.inner_text() or "")
    except Exception:
        text = ""

    text_status, text_match = _classify_text(text, cfg)
    matched.extend(text_match)

    # Combine: URL trumps text trumps DOM trumps HTTP.
    if url_status is not None:
        return ChallengeReport(url_status, url, tuple(matched), http_status)
    if text_status not in (ChallengeStatus.CLEAR, ChallengeStatus.UNKNOWN):
        return ChallengeReport(text_status, url, tuple(matched), http_status)
    if dom_match is not None:
        return ChallengeReport(ChallengeStatus.CAPTCHA, url, tuple(matched), http_status)
    if http_status in cfg.blocked_status_codes:
        return ChallengeReport(ChallengeStatus.BLOCKED, url, tuple(matched), http_status)
    return ChallengeReport(ChallengeStatus.CLEAR, url, tuple(matched), http_status)


def is_clear(page: Page, *, cfg: BypassConfig | None = None) -> bool:
    """True if the page does not look like a challenge / block."""
    return is_challenge(page, cfg=cfg).clear


def classify_text(text: str, *, cfg: BypassConfig | None = None) -> ChallengeStatus:
    """Classify a piece of HTML / visible text. No Playwright required."""
    cfg = cfg or default_config()
    status, _ = _classify_text(text, cfg)
    return status


__all__ = [
    "ChallengeReport",
    "classify_text",
    "is_challenge",
    "is_clear",
]
