from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config/defaults.json")
    p.add_argument("--target-local-datetime", required=True)
    p.add_argument("--preset", default=None)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    dt = datetime.fromisoformat(args.target_local_datetime)
    label = f"single_{dt.strftime('%Y%m%dT%H%M')}"
    cmd = [
        sys.executable,
        "scripts/run_pipeline.py",
        "--config",
        args.config,
        "--target-local-datetime",
        dt.isoformat(timespec="minutes"),
        "--run-label",
        label,
        "--mode",
        "custom_single",
    ]
    if args.preset:
        cmd.extend(["--preset", args.preset])
    subprocess.run(cmd, check=True)
    subprocess.run([sys.executable, "scripts/build_pages.py", "--config", args.config], check=True)


if __name__ == "__main__":
    main()
