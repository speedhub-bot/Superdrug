"""Unit tests for :mod:`akamai.stealth` — string templating only."""

from __future__ import annotations

from akamai.config import BypassConfig, Viewport
from akamai.stealth import (
    EXTRA_HEADERS,
    LAUNCH_ARGS,
    STEALTH_INIT_JS,
    build_extra_headers,
    build_stealth_init_js,
)


def test_default_stealth_js_is_substituted():
    js = STEALTH_INIT_JS
    assert "$$LOCALE$$" not in js
    assert "$$PLATFORM$$" not in js
    assert "$$CH_MAJOR$$" not in js
    assert "$$VIEW_WIDTH$$" not in js
    # Spot-checks for actual substituted values.
    assert "'en-GB'" in js
    assert "'Linux x86_64'" in js
    assert "'Linux'" in js  # platform_short
    # Functional features that must remain present.
    assert "webdriver" in js
    assert "'plugins'" in js
    assert "userAgentData" in js
    assert "WebGLRenderingContext" in js
    assert "WebGL2RenderingContext" in js
    assert "RTCPeerConnection" in js


def test_custom_config_changes_locale_and_platform():
    cfg = BypassConfig()
    cfg = BypassConfig(
        locale="fr-FR",
        platform="Win32",
        platform_short="Windows",
        viewport=Viewport(width=1920, height=1080),
    )
    js = build_stealth_init_js(cfg)
    assert "'fr-FR'" in js
    assert "'fr'" in js  # locale base
    assert "'Win32'" in js
    assert "'Windows'" in js
    assert "1920" in js
    assert "1080" in js


def test_launch_args_are_what_we_expect():
    assert "--disable-blink-features=AutomationControlled" in LAUNCH_ARGS
    assert "--disable-features=IsolateOrigins,site-per-process,AutomationControlled" in LAUNCH_ARGS
    # No bare --headless or --headless=new — leave the headless flag to Playwright.
    for a in LAUNCH_ARGS:
        assert not a.startswith("--headless")


def test_default_extra_headers_chrome_shape():
    h = EXTRA_HEADERS
    assert "Sec-Ch-Ua" in h
    assert "Sec-Ch-Ua-Mobile" in h
    assert "Sec-Ch-Ua-Platform" in h
    assert h["Sec-Ch-Ua-Mobile"] == "?0"
    assert h["Accept-Language"].startswith("en-GB")


def test_build_extra_headers_picks_up_custom_locale():
    cfg = BypassConfig(accept_language="de-DE,de;q=0.9", locale="de-DE")
    h = build_extra_headers(cfg)
    assert h["Accept-Language"] == "de-DE,de;q=0.9"


def test_build_stealth_idempotent_marker_present():
    """The IIFE must guard re-application or iframes will throw."""
    assert "__akamai_stealth_applied" in STEALTH_INIT_JS
