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
    start = datetime.fromisoformat(args.start_local_date + "T00:00:00")
    end = datetime.fromisoformat(args.end_local_date + "T00:00:00")
    step = timedelta(hours=args.step_hours)
    cur = start
    while cur <= end:
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
        cur += step
    subprocess.run([sys.executable, "scripts/build_pages.py", "--config", args.config], check=True)


if __name__ == "__main__":
    main()
