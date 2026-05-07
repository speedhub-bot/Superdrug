"""High-level :class:`AkamaiSession` — Playwright + stealth + warmup in one knob.

This is the entry point most callers want. A typical script looks like::

    from akamai import AkamaiSession, BypassConfig

    with AkamaiSession() as sess:
        report = sess.goto("https://www.superdrug.com/login")
        if report.blocked:
            sess.warm_up("https://www.superdrug.com/")
        page = sess.page
        # ... drive page like a normal Playwright page ...

The class deliberately exposes the underlying Playwright objects (``ctx``,
``page``) so it stays a thin convenience layer rather than a leaky wrapper —
all the existing scrapers in this repo keep working as-is.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import BypassConfig, ChallengeStatus, default_config
from .cookies import AkamaiCookies, extract_cookies
from .detection import ChallengeReport, is_challenge
from .sensor import WarmupResult, warm_up_with_retries
from .stealth import (
    IGNORE_DEFAULT_ARGS,
    LAUNCH_ARGS,
    apply_stealth,
    build_extra_headers,
)

if TYPE_CHECKING:  # pragma: no cover
    from playwright.sync_api import (
        BrowserContext,
        Page,
        Playwright,
        Response,
    )


@dataclass
class AkamaiSession:
    """Manage a stealthy Playwright context plus warmup helpers.

    Construct directly (``AkamaiSession()``) and call :meth:`start` before
    use, or use as a context manager (preferred).
    """

    cfg: BypassConfig = field(default_factory=default_config)
    state_dir: Path | None = None
    headless: bool = True
    chrome_channel: str | None = "chrome"
    on_step: Callable[[str], None] | None = None

    pw: Playwright | None = field(default=None, init=False, repr=False)
    ctx: BrowserContext | None = field(default=None, init=False, repr=False)
    page: Page | None = field(default=None, init=False, repr=False)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> AkamaiSession:
        """Boot Playwright, launch the context with stealth, open a tab."""
        if self.ctx is not None:
            return self

        # Lazy import — keeps unit tests for cookie/detection logic Playwright-free.
        from playwright.sync_api import sync_playwright

        self.pw = sync_playwright().start()
        launch_kwargs: dict[str, Any] = {
            "headless": self.headless,
            "viewport": {
                "width": self.cfg.viewport.width,
                "height": self.cfg.viewport.height,
            },
            "user_agent": self.cfg.user_agent,
            "locale": self.cfg.locale,
            "timezone_id": self.cfg.timezone_id,
            "extra_http_headers": build_extra_headers(self.cfg),
            "ignore_default_args": list(IGNORE_DEFAULT_ARGS),
            "args": list(LAUNCH_ARGS),
            "device_scale_factor": self.cfg.viewport.device_scale_factor,
            "is_mobile": self.cfg.viewport.is_mobile,
            "has_touch": self.cfg.viewport.has_touch,
        }

        if self.state_dir is not None:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            launch_kwargs["user_data_dir"] = str(self.state_dir)
            self.ctx = self._launch_persistent(launch_kwargs)
        else:
            browser = self._launch_browser()
            ctx_kwargs = {
                k: v for k, v in launch_kwargs.items()
                if k not in {"headless", "ignore_default_args", "args"}
            }
            self.ctx = browser.new_context(**ctx_kwargs)

        apply_stealth(self.ctx, self.cfg)
        self.page = self.ctx.new_page()
        return self

    def _launch_persistent(self, launch_kwargs: dict[str, Any]) -> BrowserContext:
        assert self.pw is not None
        try:
            return self.pw.chromium.launch_persistent_context(
                channel=self.chrome_channel,
                **launch_kwargs,
            )
        except Exception:
            launch_kwargs.pop("channel", None)
            return self.pw.chromium.launch_persistent_context(**launch_kwargs)

    def _launch_browser(self):
        assert self.pw is not None
        try:
            return self.pw.chromium.launch(
                channel=self.chrome_channel,
                headless=self.headless,
                args=list(LAUNCH_ARGS),
                ignore_default_args=list(IGNORE_DEFAULT_ARGS),
            )
        except Exception:
            return self.pw.chromium.launch(
                headless=self.headless,
                args=list(LAUNCH_ARGS),
                ignore_default_args=list(IGNORE_DEFAULT_ARGS),
            )

    def close(self) -> None:
        """Tear down Playwright. Idempotent."""
        with contextlib.suppress(Exception):
            if self.ctx is not None:
                self.ctx.close()
        with contextlib.suppress(Exception):
            if self.pw is not None:
                self.pw.stop()
        self.pw = None
        self.ctx = None
        self.page = None

    def __enter__(self) -> AkamaiSession:
        return self.start()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def _require_page(self) -> Page:
        if self.page is None:
            raise RuntimeError("AkamaiSession has not been started.")
        return self.page

    def goto(
        self,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
        timeout_ms: int | None = None,
    ) -> ChallengeReport:
        """Navigate and return the resulting :class:`ChallengeReport`."""
        page = self._require_page()
        timeout = timeout_ms if timeout_ms is not None else self.cfg.nav_timeout_ms
        response: Response | None = None
        try:
            response = page.goto(url, wait_until=wait_until, timeout=timeout)
        except Exception:
            response = None
        return is_challenge(page, cfg=self.cfg, response=response)

    def warm_up(self, target_url: str) -> WarmupResult:
        """Drive the human-like warmup loop. See :mod:`akamai.sensor`."""
        page = self._require_page()
        ctx = page.context
        return warm_up_with_retries(
            ctx,
            page,
            target_url,
            cfg=self.cfg,
            on_step=self.on_step,
        )

    def cookies(self) -> AkamaiCookies:
        """Snapshot Akamai cookies from the current context."""
        if self.ctx is None:
            return AkamaiCookies(None, None, None, None, None)
        try:
            return extract_cookies(self.ctx.cookies())
        except Exception:
            return AkamaiCookies(None, None, None, None, None)

    def is_clear(self) -> bool:
        """True if both the page looks unblocked and ``_abck`` is valid."""
        if self.page is None:
            return False
        report = is_challenge(self.page, cfg=self.cfg)
        return report.clear and self.cookies().is_valid

    def report(self) -> ChallengeReport:
        """Return the latest :class:`ChallengeReport` for the current page."""
        page = self._require_page()
        return is_challenge(page, cfg=self.cfg)

    # ------------------------------------------------------------------
    # Optional: handover to curl_cffi
    # ------------------------------------------------------------------

    def http_client(self):
        """Return an :class:`akamai.http_client.AkamaiHttpClient` keyed off
        the current Playwright cookie jar.

        Imports ``curl_cffi`` lazily — raises :class:`CurlCffiNotAvailable`
        if the package isn't installed.
        """
        from .http_client import AkamaiHttpClient

        if self.ctx is None:
            raise RuntimeError("AkamaiSession has not been started.")
        return AkamaiHttpClient.from_playwright(self.ctx, cfg=self.cfg)


__all__ = [
    "AkamaiSession",
    "ChallengeReport",
    "ChallengeStatus",
]
