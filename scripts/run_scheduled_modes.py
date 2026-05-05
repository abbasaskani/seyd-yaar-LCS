from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from lcs_pipeline.config import load_config


def main() -> None:
    project = load_config("config/defaults.json")
    cfg = project.raw
    for offset in cfg.get("run_horizons_days", [-2, -1, 0, 1, 2, 3, 4, 5]):
        label = { -2: "m2", -1: "yesterday", 0: "today", 1: "tomorrow" }.get(offset, f"plus_{offset}" if offset > 1 else f"minus_{abs(offset)}")
        cmd = [sys.executable, "scripts/run_pipeline.py", "--config", "config/defaults.json", "--offset-days", str(offset), "--run-label", label, "--mode", "scheduled"]
        subprocess.run(cmd, check=True)
    subprocess.run([sys.executable, "scripts/build_pages.py", "--config", "config/defaults.json"], check=True)


if __name__ == "__main__":
    main()
