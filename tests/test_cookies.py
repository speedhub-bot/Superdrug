"""Unit tests for :mod:`akamai.cookies` — pure string parsing, no Playwright."""

from __future__ import annotations

from akamai.cookies import (
    AbckCookie,
    AkamaiCookies,
    cookies_to_header,
    extract_cookies,
    is_abck_valid,
    parse_abck,
)

# ---------------------------------------------------------------------------
# parse_abck / is_abck_valid
# ---------------------------------------------------------------------------


def test_parse_abck_empty_returns_invalid():
    out = parse_abck("")
    assert isinstance(out, AbckCookie)
    assert out.valid is False
    assert out.flag == ""
    assert out.parts == ()


def test_parse_abck_flag_minus_one_is_invalid():
    """The textbook "bad bot" flag value (index-3 piece == '-1')."""
    # parts = ['EE21', 'deadbeef', 'sensorhash', '-1', '9999', '', '']
    raw = "EE21~deadbeef~sensorhash~-1~9999~~"
    out = parse_abck(raw)
    assert out.parts[3] == "-1"
    assert out.flag == "-1"
    assert out.valid is False
    assert is_abck_valid(raw) is False


def test_parse_abck_flag_zero_is_valid():
    # parts = ['EE21', 'deadbeef', 'sensorhash', '0', '9999', '', '']
    raw = "EE21~deadbeef~sensorhash~0~9999~~"
    out = parse_abck(raw)
    assert out.parts[3] == "0"
    assert out.flag == "0"
    assert out.valid is True
    assert is_abck_valid(raw) is True


def test_parse_abck_unknown_positive_flag_is_treated_as_valid():
    """Akamai sometimes uses non-zero positive flags for short windows."""
    raw = "EE21~deadbeef~sensorhash~7~9999~~"
    assert parse_abck(raw).valid is True


def test_parse_abck_too_short_falls_back_to_invalid():
    assert parse_abck("a~b~c").valid is False


# ---------------------------------------------------------------------------
# extract_cookies
# ---------------------------------------------------------------------------


def _jar(*pairs: tuple[str, str]) -> list[dict]:
    return [{"name": n, "value": v, "domain": "example.com"} for (n, v) in pairs]


def test_extract_cookies_pulls_relevant_cookies():
    jar = _jar(
        ("_abck", "EE21~deadbeef~sensorhash~0~9999~~"),
        ("bm_sz", "abc123"),
        ("ak_bmsc", "long-id"),
        ("noise", "ignored"),
    )
    out = extract_cookies(jar)
    assert isinstance(out, AkamaiCookies)
    assert out.abck is not None
    assert out.abck.valid is True
    assert out.bm_sz == "abc123"
    assert out.ak_bmsc == "long-id"
    assert out.has_session is True
    assert out.is_valid is True


def test_extract_cookies_partial_session_is_not_valid():
    jar = _jar(("_abck", "v~h~s~-1~~"))
    out = extract_cookies(jar)
    assert out.has_session is False  # bm_sz missing
    assert out.is_valid is False


def test_extract_cookies_handles_missing_cookies():
    out = extract_cookies(_jar(("foo", "bar")))
    assert out.abck is None
    assert out.bm_sz is None
    assert out.has_session is False
    assert out.is_valid is False


# ---------------------------------------------------------------------------
# cookies_to_header
# ---------------------------------------------------------------------------


def test_cookies_to_header_renders_pairs_in_order():
    jar = _jar(("a", "1"), ("b", "two"), ("c", "three"))
    assert cookies_to_header(jar) == "a=1; b=two; c=three"


def test_cookies_to_header_skips_empty_names():
    jar = [
        {"name": "ok", "value": "1"},
        {"name": "", "value": "skip"},
        {"name": "also", "value": "fine"},
    ]
    assert cookies_to_header(jar) == "ok=1; also=fine"
