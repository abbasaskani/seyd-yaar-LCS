from __future__ import annotations

import py_compile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def first_non_empty(path: Path) -> str:
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            return line.strip()
    return ""


def fail(msg: str) -> None:
    raise SystemExit(f"SOURCE_LAYOUT_ERROR: {msg}")


def main() -> None:
    py_files = [
        ROOT / "lcs_pipeline" / "copernicus_io.py",
        ROOT / "lcs_pipeline" / "ftle.py",
        ROOT / "lcs_pipeline" / "outputs.py",
        ROOT / "scripts" / "run_pipeline.py",
        ROOT / "scripts" / "run_scheduled_modes.py",
    ]
    workflow = ROOT / ".github" / "workflows" / "run_lcs.yml"

    for p in py_files:
        if not p.exists():
            fail(f"Missing required Python file: {p.relative_to(ROOT)}")
        head = first_non_empty(p)
        if head.startswith("name:") or head.startswith("on:") or "Run LCS pipeline" in head:
            fail(f"{p.relative_to(ROOT)} appears to contain GitHub Actions YAML, not Python. First line: {head!r}")
        try:
            py_compile.compile(str(p), doraise=True)
        except Exception as exc:
            fail(f"Python compile failed for {p.relative_to(ROOT)}: {exc}")

    if not workflow.exists():
        fail(f"Missing workflow file: {workflow.relative_to(ROOT)}")
    head = first_non_empty(workflow)
    if not head.startswith("name:"):
        fail(f"{workflow.relative_to(ROOT)} does not look like a GitHub Actions workflow. First line: {head!r}")

    print("Source layout sanity check passed.")


if __name__ == "__main__":
    main()
