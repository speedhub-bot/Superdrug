"""Human-like input helpers used by the sensor warmup.

Akamai's sensor data POST contains aggregate statistics about mouse/touch/key
events — *not* the events themselves. So we don't have to be cinema-grade
realistic; we just have to:

* generate enough movement that the JS observers think a human is present, and
* avoid obviously synthetic patterns (perfect straight lines, identical timings).

A small dependency-free Bezier curve + jitter is enough.
"""

from __future__ import annotations

import contextlib
import math
import random
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - only used for type hints
    from playwright.sync_api import Locator, Page

DEFAULT_STEPS = 25


def _ease_in_out(t: float) -> float:
    """Cosine ease-in-out."""
    return 0.5 - 0.5 * math.cos(math.pi * t)


def _bezier_point(t: float, p0: tuple[float, float], p1: tuple[float, float],
                  p2: tuple[float, float], p3: tuple[float, float]) -> tuple[float, float]:
    """Standard cubic-bezier formula."""
    u = 1 - t
    x = (u**3) * p0[0] + 3 * (u**2) * t * p1[0] + 3 * u * (t**2) * p2[0] + (t**3) * p3[0]
    y = (u**3) * p0[1] + 3 * (u**2) * t * p1[1] + 3 * u * (t**2) * p2[1] + (t**3) * p3[1]
    return x, y


def random_in_viewport(page: Page, *, margin: int = 50) -> tuple[int, int]:
    """Pick a random point inside the visible viewport."""
    try:
        size = page.viewport_size or {"width": 1280, "height": 800}
    except Exception:
        size = {"width": 1280, "height": 800}
    w = max(int(size["width"]) - margin * 2, margin * 2)
    h = max(int(size["height"]) - margin * 2, margin * 2)
    return random.randint(margin, margin + w), random.randint(margin, margin + h)


def human_mouse_move(
    page: Page,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    steps: int = DEFAULT_STEPS,
    duration_ms: int = 600,
    jitter: int = 3,
) -> None:
    """Move the mouse from ``start`` to ``end`` along a slightly-curved path.

    Uses a cubic Bezier with two random control points + per-step pixel jitter
    + a cosine timing easing so the wall-clock duration of each step varies,
    which is the bit Akamai's sensor actually checks.
    """
    sx, sy = start
    ex, ey = end
    dx, dy = ex - sx, ey - sy
    # Control points perpendicular to the straight line (so the path curves).
    perp = (-dy, dx)
    norm = math.hypot(*perp) or 1.0
    perp_unit = (perp[0] / norm, perp[1] / norm)
    bow = random.uniform(-0.20, 0.20) * math.hypot(dx, dy)
    p0 = (sx, sy)
    p3 = (ex, ey)
    p1 = (sx + dx * 0.33 + perp_unit[0] * bow, sy + dy * 0.33 + perp_unit[1] * bow)
    p2 = (sx + dx * 0.66 + perp_unit[0] * bow, sy + dy * 0.66 + perp_unit[1] * bow)

    per_step = max(duration_ms / max(steps, 1) / 1000.0, 0.001)
    page.mouse.move(sx, sy, steps=1)
    for i in range(1, steps + 1):
        t = _ease_in_out(i / steps)
        x, y = _bezier_point(t, p0, p1, p2, p3)
        x += random.uniform(-jitter, jitter)
        y += random.uniform(-jitter, jitter)
        with contextlib.suppress(Exception):
            page.mouse.move(x, y, steps=1)
        time.sleep(per_step * random.uniform(0.7, 1.3))


def human_scroll(
    page: Page,
    *,
    distance: int | None = None,
    direction: str = "down",
    steps: int = 5,
    pause_ms: tuple[int, int] = (60, 220),
) -> None:
    """Scroll the page in small, irregular increments."""
    if distance is None:
        distance = random.randint(200, 800)
    if direction not in {"up", "down"}:
        direction = "down"
    sign = 1 if direction == "down" else -1
    chunks = [distance // steps + random.randint(-12, 12) for _ in range(steps)]
    for c in chunks:
        try:
            page.mouse.wheel(0, c * sign)
        except Exception:
            with contextlib.suppress(Exception):
                page.evaluate(f"window.scrollBy(0, {c * sign})")
        time.sleep(random.uniform(pause_ms[0], pause_ms[1]) / 1000.0)


def human_dwell(min_ms: int, max_ms: int) -> None:
    """Sleep for a random duration inside the given bounds."""
    if max_ms < min_ms:
        max_ms = min_ms
    time.sleep(random.uniform(min_ms, max_ms) / 1000.0)


def human_type(
    locator: Locator,
    text: str,
    *,
    per_key_ms: tuple[int, int] = (40, 140),
) -> None:
    """Type ``text`` into a Playwright Locator one character at a time.

    Tiny per-key delays beat ``Locator.fill`` for sensor data warmth.
    """
    locator.click()
    for ch in text:
        locator.type(ch, delay=random.uniform(per_key_ms[0], per_key_ms[1]))


__all__ = [
    "DEFAULT_STEPS",
    "human_dwell",
    "human_mouse_move",
    "human_scroll",
    "human_type",
    "random_in_viewport",
]
