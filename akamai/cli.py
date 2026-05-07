"""``python -m akamai check <URL>`` — a smoke test for the bypass.

Useful for asking "is the toolkit currently good enough to crack site X?" in
one line. Prints a structured report of the navigation outcome, the warmup
loop, the final ``_abck`` cookie state, and a suggestion for what to do
next.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

from .config import ChallengeStatus, default_config
from .session import AkamaiSession


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m akamai",
        description="Probe a URL through the Akamai bypass toolkit.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    check = sub.add_parser("check", help="Navigate to a URL and report.")
    check.add_argument("url", help="The URL to probe.")
    check.add_argument("--headed", action="store_true",
                       help="Show the browser window (default: headless).")
    check.add_argument("--state-dir", type=Path, default=None,
                       help="Persistent profile dir (omit for ephemeral).")
    check.add_argument("--no-warmup", action="store_true",
                       help="Skip the sensor warmup loop.")
    check.add_argument("--json", action="store_true",
                       help="Emit machine-readable JSON instead of human text.")

    info = sub.add_parser("info", help="Print the active default config.")
    info.add_argument("--json", action="store_true")

    return p


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_check(args: argparse.Namespace) -> int:
    log_lines: list[str] = []

    def step(msg: str) -> None:
        log_lines.append(msg)
        if not args.json:
            print(f"  [..] {msg}")

    sess = AkamaiSession(
        headless=not args.headed,
        state_dir=args.state_dir,
        on_step=step,
    )
    try:
        sess.start()
    except Exception as e:
        print(f"failed to start Playwright: {e}", file=sys.stderr)
        return 2

    try:
        report = sess.goto(args.url)
        if not args.json:
            print(f"  initial   : {report.status.value}  url={report.url}")
        warm_result = None
        if not args.no_warmup and report.status is not ChallengeStatus.CLEAR:
            warm_result = sess.warm_up(args.url)
            if not args.json:
                ok = "OK" if warm_result.succeeded else "NOT CLEARED"
                print(
                    f"  warmup    : {ok}  in {warm_result.elapsed_seconds:.1f}s "
                    f"after {warm_result.attempts} attempts ({warm_result.detail})"
                )

        final_report = sess.report()
        cookies = sess.cookies()

        payload = {
            "url": args.url,
            "final_url": final_report.url,
            "initial_status": report.status.value,
            "final_status": final_report.status.value,
            "blocked": final_report.blocked,
            "abck_valid": cookies.is_valid,
            "abck_flag": cookies.abck.flag if cookies.abck else None,
            "abck_present": cookies.abck is not None,
            "bm_sz_present": cookies.bm_sz is not None,
            "warmup": (
                {
                    "succeeded": warm_result.succeeded,
                    "elapsed_seconds": round(warm_result.elapsed_seconds, 2),
                    "attempts": warm_result.attempts,
                    "last_status": warm_result.last_status.value,
                    "detail": warm_result.detail,
                }
                if warm_result is not None else None
            ),
            "matched": list(final_report.matched),
            "log": log_lines,
        }

        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print()
            print("  " + "-" * 56)
            print(f"  final     : {final_report.status.value}")
            print(f"  abck      : valid={cookies.is_valid}  flag={payload['abck_flag']!r}")
            print(f"  bm_sz set : {cookies.bm_sz is not None}")
            if final_report.matched:
                print(f"  matched   : {', '.join(final_report.matched)}")
            print()
            verdict = "PASS" if not final_report.blocked and cookies.is_valid else "BLOCKED"
            print(f"  verdict   : {verdict}")

        return 0 if not final_report.blocked and cookies.is_valid else 1
    finally:
        with contextlib.suppress(Exception):
            sess.close()


def cmd_info(args: argparse.Namespace) -> int:
    cfg = default_config()
    out = {
        "user_agent": cfg.user_agent,
        "chrome_major": cfg.chrome_major,
        "chrome_full_version": cfg.chrome_full_version,
        "platform": cfg.platform,
        "locale": cfg.locale,
        "timezone_id": cfg.timezone_id,
        "viewport": {
            "width": cfg.viewport.width,
            "height": cfg.viewport.height,
        },
        "warmup_max_seconds": cfg.warmup_max_seconds,
        "max_warmup_attempts": cfg.max_warmup_attempts,
    }
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        for k, v in out.items():
            print(f"  {k:<22}: {v}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "info":
        return cmd_info(args)
    parser.error("unknown command")
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
