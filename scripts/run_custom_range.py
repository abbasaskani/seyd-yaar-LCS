from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timedelta


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config/defaults.json")
    p.add_argument("--start-local-date", required=True)
    p.add_argument("--end-local-date", required=True)
    p.add_argument("--step-hours", type=int, default=24)
    p.add_argument("--preset", default=None)
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not args.start_local_date or not args.end_local_date:
        raise SystemExit(
            "custom_range requires both --start-local-date and --end-local-date. "
            "Example: --start-local-date 2025-01-01 --end-local-date 2025-01-07"
        )

    try:
        start = datetime.fromisoformat(args.start_local_date)
    except ValueError as exc:
        raise SystemExit(
            f"Invalid start date: {args.start_local_date!r}. Use YYYY-MM-DD."
        ) from exc

    try:
        end = datetime.fromisoformat(args.end_local_date)
    except ValueError as exc:
        raise SystemExit(
            f"Invalid end date: {args.end_local_date!r}. Use YYYY-MM-DD."
        ) from exc

    if args.step_hours <= 0:
        raise SystemExit(f"step-hours must be > 0, got {args.step_hours!r}")

    cur = start.replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = end.replace(hour=0, minute=0, second=0, microsecond=0)

    while cur <= end_dt:
        label = f"range_{cur.strftime('%Y%m%dT%H%M')}"
        cmd = [
            sys.executable,
            "scripts/run_pipeline.py",
            "--config",
            args.config,
            "--target-local-datetime",
            cur.isoformat(timespec="minutes"),
            "--run-label",
            label,
            "--mode",
            "custom_range",
        ]
        if args.preset:
            cmd.extend(["--preset", args.preset])
        subprocess.run(cmd, check=True)
        cur += timedelta(hours=args.step_hours)

    subprocess.run([sys.executable, "scripts/build_pages.py", "--config", args.config], check=True)


if __name__ == "__main__":
    main()
