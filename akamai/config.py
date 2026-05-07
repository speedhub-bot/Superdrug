"""Configuration objects for the Akamai bypass toolkit.

Everything that varies between sites or between "Chrome 131 on Windows" vs
"Chrome 131 on Linux" lives here so the rest of the package stays declarative.

The defaults are tuned for *Linux x86_64 + Chrome 131 + en-GB* (which is what
``superdrug_report.py`` runs under) and intentionally biased toward boring,
common values — Akamai blocks weirdness, not majorities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ChallengeStatus(str, Enum):
    """Coarse outcome of an Akamai check on a page."""

    CLEAR = "clear"               # no challenge detected, content rendered
    AKAMAI = "akamai"             # Akamai bot manager challenge / interstitial
    CLOUDFLARE = "cloudflare"     # Cloudflare 5xx / "checking your browser" page
    CAPTCHA = "captcha"           # generic CAPTCHA widget on screen
    BLOCKED = "blocked"           # 403 / Access Denied page from origin
    UNKNOWN = "unknown"           # couldn't decide, treat as suspicious


# Chrome 131 on Linux x86_64 — keep the UA, sec-ch-ua and platform consistent.
CHROME_VERSION = "131"
CHROME_FULL_VERSION = "131.0.0.0"
CHROME_USER_AGENT = (
    f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    f"(KHTML, like Gecko) Chrome/{CHROME_FULL_VERSION} Safari/537.36"
)


@dataclass(frozen=True)
class Viewport:
    width: int = 1280
    height: int = 900
    device_scale_factor: float = 1.0
    is_mobile: bool = False
    has_touch: bool = False


@dataclass
class BypassConfig:
    """Tunables for the Akamai bypass session.

    Frozen-ish in spirit — anything you care about should be set at
    construction time. Mutating later is supported but won't retroactively
    apply to an already-launched browser context.
    """

    # ------------------------------------------------------------------
    # Browser identity
    # ------------------------------------------------------------------
    user_agent: str = CHROME_USER_AGENT
    chrome_major: str = CHROME_VERSION
    chrome_full_version: str = CHROME_FULL_VERSION
    platform: str = "Linux x86_64"
    platform_short: str = "Linux"
    locale: str = "en-GB"
    accept_language: str = "en-GB,en;q=0.9"
    timezone_id: str = "Europe/London"
    viewport: Viewport = field(default_factory=Viewport)

    # ------------------------------------------------------------------
    # Network
    # ------------------------------------------------------------------
    extra_headers: dict[str, str] = field(default_factory=dict)
    sec_ch_ua_full: str = field(init=False)
    sec_ch_ua_mobile: str = "?0"
    sec_ch_ua_platform: str = field(init=False)

    # ------------------------------------------------------------------
    # Sensor / warmup behaviour
    # ------------------------------------------------------------------
    warmup_max_seconds: float = 12.0
    warmup_min_mouse_moves: int = 6
    warmup_min_scrolls: int = 2
    warmup_dwell_ms: tuple[int, int] = (250, 750)   # min/max per micro-step
    warmup_idle_ms: tuple[int, int] = (350, 900)    # idle gap between steps

    # ------------------------------------------------------------------
    # Challenge detection
    # ------------------------------------------------------------------
    blocked_status_codes: tuple[int, ...] = (403, 429)
    challenge_url_substrings: tuple[str, ...] = (
        "captcha",
        "challenges.cloudflare",
        "/cdn-cgi/challenge",
        "/_Incapsula_Resource",
        "/akam/",
        "akamai.com/_bm",
    )
    challenge_text_needles: tuple[str, ...] = (
        "verify you are human",
        "i'm not a robot",
        "checking your browser",
        "complete the security check",
        "press and hold",
        "needs to review the security",
        "captcha",
        "access denied",
        "you don't have permission",
        "request unsuccessful",
        "akamai",
    )

    # ------------------------------------------------------------------
    # Retries
    # ------------------------------------------------------------------
    max_warmup_attempts: int = 3
    nav_timeout_ms: int = 20_000

    def __post_init__(self) -> None:
        # sec-ch-ua header value: keep brand list reasonable & in a stable order.
        self.sec_ch_ua_full = (
            f'"Google Chrome";v="{self.chrome_major}", '
            f'"Chromium";v="{self.chrome_major}", '
            f'"Not_A Brand";v="24"'
        )
        self.sec_ch_ua_platform = f'"{self.platform_short}"'

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------
    def base_headers(self) -> dict[str, str]:
        """The minimum request headers Chrome always sends to top-level docs."""
        h: dict[str, str] = {
            "Accept-Language": self.accept_language,
            "Sec-Ch-Ua": self.sec_ch_ua_full,
            "Sec-Ch-Ua-Mobile": self.sec_ch_ua_mobile,
            "Sec-Ch-Ua-Platform": self.sec_ch_ua_platform,
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8,"
                "application/signed-exchange;v=b3;q=0.7"
            ),
        }
        h.update(self.extra_headers)
        return h


def default_config() -> BypassConfig:
    """Return a fresh :class:`BypassConfig` with sensible defaults."""
    return BypassConfig()
