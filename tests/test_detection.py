"""Unit tests for :mod:`akamai.detection` text/url classifiers."""

from __future__ import annotations

from akamai.config import ChallengeStatus, default_config
from akamai.detection import _classify_text, _classify_url, classify_text


def test_classify_text_clear_for_normal_page():
    txt = "Welcome back to Superdrug. Order again, save 10%."
    assert classify_text(txt) is ChallengeStatus.CLEAR


def test_classify_text_press_and_hold_is_captcha():
    assert classify_text("Please press and hold the button") is ChallengeStatus.CAPTCHA


def test_classify_text_cloudflare_phrase_is_cloudflare():
    assert (
        classify_text("Checking your browser before accessing example.com.")
        is ChallengeStatus.CLOUDFLARE
    )


def test_classify_text_akamai_block_is_akamai():
    txt = "Access Denied. You don't have permission to access on this server. Reference #18.2.akamai"
    assert classify_text(txt) is ChallengeStatus.AKAMAI


def test_classify_text_access_denied_alone_is_blocked():
    assert classify_text("Access Denied — go away") is ChallengeStatus.BLOCKED


def test_classify_url_cloudflare_substring():
    cfg = default_config()
    status, matched = _classify_url("https://challenges.cloudflare.com/turnstile", cfg)
    assert status is ChallengeStatus.CLOUDFLARE
    assert any("cloudflare" in m for m in matched)


def test_classify_url_akamai_substring():
    cfg = default_config()
    status, matched = _classify_url("https://example.com/_Incapsula_Resource?xyz", cfg)
    assert status is ChallengeStatus.AKAMAI
    assert any("incapsula" in m.lower() for m in matched)


def test_classify_url_clean_returns_none():
    cfg = default_config()
    status, matched = _classify_url("https://www.superdrug.com/login", cfg)
    assert status is None
    assert matched == []


def test_classify_text_returns_breadcrumbs():
    cfg = default_config()
    status, matched = _classify_text(
        "Please complete the security check to continue.", cfg
    )
    assert status is ChallengeStatus.CAPTCHA
    assert any("security check" in m for m in matched)
