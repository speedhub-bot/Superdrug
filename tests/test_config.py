"""Unit tests for :mod:`akamai.config`."""

from __future__ import annotations

from akamai.config import (
    CHROME_FULL_VERSION,
    CHROME_USER_AGENT,
    CHROME_VERSION,
    BypassConfig,
    ChallengeStatus,
    default_config,
)


def test_default_config_has_chrome_131_user_agent():
    cfg = default_config()
    assert cfg.user_agent == CHROME_USER_AGENT
    assert cfg.chrome_major == CHROME_VERSION
    assert cfg.chrome_full_version == CHROME_FULL_VERSION
    assert "Linux x86_64" in cfg.user_agent
    assert cfg.locale == "en-GB"
    assert cfg.timezone_id == "Europe/London"


def test_sec_ch_ua_strings_match_chrome_format():
    cfg = default_config()
    assert cfg.sec_ch_ua_full.startswith('"Google Chrome";v="131"')
    assert cfg.sec_ch_ua_platform == '"Linux"'


def test_base_headers_includes_chrome_fetch_metadata():
    cfg = default_config()
    h = cfg.base_headers()
    assert h["Sec-Fetch-Dest"] == "document"
    assert h["Sec-Fetch-Mode"] == "navigate"
    assert h["Sec-Fetch-Site"] == "none"
    assert h["Upgrade-Insecure-Requests"] == "1"


def test_extra_headers_override_merges_in():
    cfg = BypassConfig(extra_headers={"X-Test": "yes"})
    h = cfg.base_headers()
    assert h["X-Test"] == "yes"
    # Defaults must still be present.
    assert h["Sec-Ch-Ua-Mobile"] == "?0"


def test_challenge_status_enum_values():
    assert ChallengeStatus.CLEAR.value == "clear"
    assert ChallengeStatus.AKAMAI.value == "akamai"
    assert ChallengeStatus.CAPTCHA.value == "captcha"
    assert ChallengeStatus.BLOCKED.value == "blocked"
    assert ChallengeStatus.UNKNOWN.value == "unknown"
