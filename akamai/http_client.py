"""Optional ``curl_cffi`` wrapper for raw HTTP that mimics Chrome at TLS level.

Akamai checks more than your headers — it inspects the TLS ClientHello
fingerprint (JA3) and the HTTP/2 SETTINGS / HEADERS frame ordering. ``requests``
and ``urllib`` produce a JA3 that is *immediately* recognisable as Python.
``curl_cffi`` (https://github.com/yifeikong/curl_cffi) ships pre-built
impersonation profiles ("chrome131", "chrome120", "safari17", …) that match
real browsers byte-for-byte.

We import ``curl_cffi`` lazily so the rest of the package — and the Superdrug
report tool — keeps working even when ``curl_cffi`` isn't installed (e.g. on
the CI lint-only image).
"""

from __future__ import annotations

import importlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .config import BypassConfig, default_config
from .cookies import cookies_to_header

DEFAULT_IMPERSONATE = "chrome131"


class CurlCffiNotAvailable(RuntimeError):
    """Raised when the caller tries to use the HTTP client without curl_cffi."""


def _try_import_curl_cffi():
    try:
        return importlib.import_module("curl_cffi.requests")
    except Exception as e:  # pragma: no cover - depends on env
        raise CurlCffiNotAvailable(
            "curl_cffi is not installed. `pip install curl_cffi` to use "
            "akamai.http_client.AkamaiHttpClient."
        ) from e


@dataclass
class AkamaiHttpClient:
    """Drop-in HTTP client that impersonates Chrome at TLS + H2 level.

    Typical use, after warming a Playwright session::

        from akamai.http_client import AkamaiHttpClient
        client = AkamaiHttpClient.from_playwright(ctx, cfg=cfg)
        r = client.get("https://www.superdrug.com/api/orders")
    """

    cookie_jar: dict[str, str] = field(default_factory=dict)
    impersonate: str = DEFAULT_IMPERSONATE
    cfg: BypassConfig = field(default_factory=default_config)
    _session: Any = field(default=None, init=False, repr=False)

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_playwright(
        cls,
        ctx: Any,
        *,
        cfg: BypassConfig | None = None,
        impersonate: str = DEFAULT_IMPERSONATE,
    ) -> AkamaiHttpClient:
        cfg = cfg or default_config()
        jar: dict[str, str] = {}
        try:
            for c in ctx.cookies():
                name = c.get("name")
                value = c.get("value", "")
                if name:
                    jar[name] = value
        except Exception:
            pass
        return cls(cookie_jar=jar, impersonate=impersonate, cfg=cfg)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def session(self):
        """Return (creating if needed) the underlying curl_cffi Session."""
        if self._session is None:
            curl_cffi = _try_import_curl_cffi()
            sess = curl_cffi.Session(impersonate=self.impersonate)
            for k, v in self._headers().items():
                sess.headers[k] = v
            for n, v in self.cookie_jar.items():
                with _suppress():
                    sess.cookies.set(n, v)
            self._session = sess
        return self._session

    def close(self) -> None:
        if self._session is not None:
            with _suppress():
                self._session.close()
            self._session = None

    def __enter__(self) -> AkamaiHttpClient:
        self.session()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Cookie / header helpers
    # ------------------------------------------------------------------

    def update_cookies(self, jar: Iterable[Mapping[str, object]]) -> None:
        for c in jar:
            n = c.get("name")
            v = c.get("value", "")
            if n:
                self.cookie_jar[str(n)] = str(v)
        if self._session is not None:
            for n, v in self.cookie_jar.items():
                with _suppress():
                    self._session.cookies.set(n, v)

    def cookie_header(self) -> str:
        return cookies_to_header(
            [{"name": n, "value": v} for n, v in self.cookie_jar.items()]
        )

    def _headers(self) -> dict[str, str]:
        h = self.cfg.base_headers()
        h["User-Agent"] = self.cfg.user_agent
        return h

    # ------------------------------------------------------------------
    # Request methods
    # ------------------------------------------------------------------

    def get(self, url: str, **kw: Any):
        return self.session().get(url, **kw)

    def post(self, url: str, **kw: Any):
        return self.session().post(url, **kw)

    def request(self, method: str, url: str, **kw: Any):
        return self.session().request(method, url, **kw)


class _suppress:
    """Local re-impl of contextlib.suppress(Exception) to keep import small."""

    def __enter__(self) -> _suppress:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return exc_type is not None and issubclass(exc_type, Exception)


__all__ = [
    "DEFAULT_IMPERSONATE",
    "AkamaiHttpClient",
    "CurlCffiNotAvailable",
]
