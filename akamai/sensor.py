"""Sensor-data warmup orchestrator.

Akamai's bot-manager script does two things on every page load:

1. it watches mouse / scroll / key events for ~5–10 seconds, building a sensor
   payload that gets POSTed to a path like ``/akam/13/<id>`` or
   ``akamai.com/_bm/_data``, and
2. it inspects ``_abck`` after the response — if the cookie's index-3 piece
   flips from ``-1`` to ``0`` the session is "good" and subsequent requests
   are passed through without further checks.

This module drives a Playwright page through a believable interaction loop
until either ``_abck`` flips to good *or* a deadline elapses. It does **not**
forge sensor data; it just makes sure real-looking input exists for the JS
to observe.
"""

from __future__ import annotations

import contextlib
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .config import BypassConfig, ChallengeStatus, default_config
from .cookies import AkamaiCookies, extract_cookies
from .detection import is_challenge
from .human import human_dwell, human_mouse_move, human_scroll, random_in_viewport

if TYPE_CHECKING:  # pragma: no cover
    from playwright.sync_api import BrowserContext, Page


@dataclass
class WarmupResult:
    """What :func:`warm_up` saw before it returned."""

    succeeded: bool
    elapsed_seconds: float
    attempts: int
    last_status: ChallengeStatus
    cookies: AkamaiCookies
    detail: str = ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def warm_up(
    page: Page,
    *,
    cfg: BypassConfig | None = None,
    on_step: Callable[[str], None] | None = None,
) -> WarmupResult:
    """Drive ``page`` until the Akamai cookie says we're "clear".

    The loop alternates between mouse moves, small scrolls and idle dwells —
    exactly what a real user does while reading a page. ``on_step`` is an
    optional progress hook (great for the CLI).
    """
    cfg = cfg or default_config()
    log = on_step or (lambda _msg: None)

    ctx = page.context
    started = time.time()
    deadline = started + cfg.warmup_max_seconds
    attempts = 0
    last_status = ChallengeStatus.UNKNOWN
    last_cookies = extract_cookies(ctx.cookies())

    log(f"warmup: start  ({cfg.warmup_max_seconds:.1f}s deadline)")
    if last_cookies.is_valid:
        log("warmup: _abck already valid — skipping")
        return WarmupResult(
            succeeded=True,
            elapsed_seconds=time.time() - started,
            attempts=0,
            last_status=ChallengeStatus.CLEAR,
            cookies=last_cookies,
            detail="already valid",
        )

    last = random_in_viewport(page)
    while time.time() < deadline:
        attempts += 1
        # Mouse move along a Bezier arc.
        nxt = random_in_viewport(page)
        with contextlib.suppress(Exception):
            human_mouse_move(
                page, last, nxt,
                duration_ms=random.randint(450, 1200),
                steps=random.randint(15, 35),
            )
        last = nxt

        # Occasional small scroll.
        if attempts % 2 == 0:
            with contextlib.suppress(Exception):
                human_scroll(
                    page,
                    distance=random.randint(120, 480),
                    direction="down" if random.random() > 0.2 else "up",
                    steps=random.randint(3, 6),
                )

        # Idle dwell — Akamai cares about *time between* events too.
        human_dwell(*cfg.warmup_dwell_ms)

        # Inspect cookies + challenge status.
        try:
            last_cookies = extract_cookies(ctx.cookies())
        except Exception:
            last_cookies = AkamaiCookies(None, None, None, None, None)
        try:
            last_status = is_challenge(page, cfg=cfg).status
        except Exception:
            last_status = ChallengeStatus.UNKNOWN

        log(
            f"warmup: t={time.time() - started:5.2f}s "
            f"abck.flag={getattr(last_cookies.abck, 'flag', '-') or '-'} "
            f"status={last_status.value}"
        )

        if last_cookies.is_valid and last_status is ChallengeStatus.CLEAR:
            return WarmupResult(
                succeeded=True,
                elapsed_seconds=time.time() - started,
                attempts=attempts,
                last_status=last_status,
                cookies=last_cookies,
                detail="abck went valid",
            )

        # If a hard block appeared, no amount of scrolling will help.
        if last_status in (ChallengeStatus.AKAMAI, ChallengeStatus.BLOCKED, ChallengeStatus.CAPTCHA):
            human_dwell(*cfg.warmup_idle_ms)
            continue

        human_dwell(*cfg.warmup_idle_ms)

    return WarmupResult(
        succeeded=last_cookies.is_valid and last_status is ChallengeStatus.CLEAR,
        elapsed_seconds=time.time() - started,
        attempts=attempts,
        last_status=last_status,
        cookies=last_cookies,
        detail="deadline reached",
    )


def warm_up_with_retries(
    ctx: BrowserContext,
    page: Page,
    target_url: str,
    *,
    cfg: BypassConfig | None = None,
    on_step: Callable[[str], None] | None = None,
) -> WarmupResult:
    """Higher-level helper: navigate + warm up + retry up to ``max_warmup_attempts``.

    Each retry re-navigates to ``target_url`` so Akamai's script gets another
    chance to mint a fresh ``bm_sz``.
    """
    cfg = cfg or default_config()
    log = on_step or (lambda _msg: None)

    last_result: WarmupResult | None = None
    for attempt in range(1, cfg.max_warmup_attempts + 1):
        log(f"warmup: attempt {attempt}/{cfg.max_warmup_attempts} → {target_url}")
        try:
            page.goto(target_url, wait_until="domcontentloaded", timeout=cfg.nav_timeout_ms)
        except Exception as e:
            log(f"warmup: navigation failed: {type(e).__name__}: {e}")
            continue
        # Tiny natural pause before we start mousing.
        human_dwell(400, 900)
        last_result = warm_up(page, cfg=cfg, on_step=log)
        if last_result.succeeded:
            return last_result
        # Drop only Akamai cookies and try again — server will re-challenge.
        with contextlib.suppress(Exception):
            ctx.clear_cookies(name="bm_sz")
        with contextlib.suppress(Exception):
            ctx.clear_cookies(name="_abck")
        time.sleep(random.uniform(0.8, 1.6))

    if last_result is None:
        last_result = WarmupResult(
            succeeded=False,
            elapsed_seconds=0.0,
            attempts=0,
            last_status=ChallengeStatus.UNKNOWN,
            cookies=AkamaiCookies(None, None, None, None, None),
            detail="no successful navigation",
        )
    return last_result


__all__ = [
    "WarmupResult",
    "warm_up",
    "warm_up_with_retries",
]
