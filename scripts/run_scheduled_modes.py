from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from lcs_pipeline.config import load_config


def cleanup_generated_outputs(repo_root: Path) -> None:
    """Remove stale generated artifacts but keep source files intact."""
    repo_root = Path(repo_root)
    for candidate in (
        repo_root / "outputs" / "latest",
        repo_root / "outputs" / "archive",
        repo_root / "outputs" / "_staging",
        repo_root / "docs" / "latest",
    ):
        if not candidate.exists():
            continue
        if candidate.is_dir():
            shutil.rmtree(candidate)
        else:
            candidate.unlink()

    for target in (repo_root / "outputs", repo_root / "docs" / "latest"):
        target.mkdir(parents=True, exist_ok=True)
    (repo_root / "docs" / "latest" / ".gitkeep").touch(exist_ok=True)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cleanup_generated_outputs(repo_root)

    project = load_config("config/defaults.json")
    cfg = project.raw
    for offset in cfg.get("run_horizons_days", [-1, 0, 1, 2, 3, 4, 5]):
        label = {-1: "yesterday", 0: "today", 1: "tomorrow"}.get(offset, f"plus_{offset}" if offset > 1 else f"minus_{abs(offset)}")
        cmd = [
            sys.executable,
            "scripts/run_pipeline.py",
            "--config",
            "config/defaults.json",
            "--offset-days",
            str(offset),
            "--run-label",
            label,
            "--mode",
            "routine",
        ]
        subprocess.run(cmd, check=True)
    subprocess.run([sys.executable, "scripts/build_pages.py", "--config", "config/defaults.json"], check=True)


if __name__ == "__main__":
    main()
