"""Akamai Bot Manager bypass toolkit.

Built for *single-account, owner-operated* automation. The whole package is a
collection of building blocks rather than a CAPTCHA-solver:

* :mod:`akamai.stealth`     — comprehensive ``addInitScript`` payload that
  spoofs the dead-giveaway browser fingerprints Akamai keys off (webdriver,
  plugins, user-agent client hints, WebGL, canvas, audio, WebRTC, …).
* :mod:`akamai.cookies`     — parse/inspect ``_abck``, ``bm_sz``, ``ak_bmsc``
  and decide whether the current Akamai session is "valid" / unblocked.
* :mod:`akamai.detection`   — detect Akamai / Cloudflare / generic CAPTCHA
  challenge pages from URL + visible text + DOM markers.
* :mod:`akamai.human`       — natural mouse, scroll and typing helpers used
  to drive the sensor-data warmup.
* :mod:`akamai.sensor`      — orchestrates the warmup loop; returns once
  Akamai stops flagging the session or a deadline elapses.
* :mod:`akamai.http_client` — optional ``curl_cffi`` wrapper that re-uses
  the Playwright cookies + a Chrome JA3 fingerprint for raw HTTP calls.
* :mod:`akamai.session`     — :class:`AkamaiSession`, the high-level
  Playwright-based session that ties the rest together.
* :mod:`akamai.cli`         — ``python -m akamai check <URL>`` smoke test.

All public names are re-exported here so callers can ``from akamai import …``.
"""

from __future__ import annotations

from .config import BypassConfig, ChallengeStatus, default_config
from .cookies import (
    AkamaiCookies,
    extract_cookies,
    is_abck_valid,
    parse_abck,
)
from .detection import ChallengeReport, is_challenge, is_clear
from .session import AkamaiSession
from .stealth import (
    EXTRA_HEADERS,
    LAUNCH_ARGS,
    STEALTH_INIT_JS,
    apply_stealth,
    build_extra_headers,
)

__all__ = [
    "EXTRA_HEADERS",
    "LAUNCH_ARGS",
    "STEALTH_INIT_JS",
    "AkamaiCookies",
    "AkamaiSession",
    "BypassConfig",
    "ChallengeReport",
    "ChallengeStatus",
    "apply_stealth",
    "build_extra_headers",
    "default_config",
    "extract_cookies",
    "is_abck_valid",
    "is_challenge",
    "is_clear",
    "parse_abck",
]

__version__ = "0.1.0"
