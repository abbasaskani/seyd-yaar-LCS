from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json


@dataclass
class ProjectConfig:
    raw: dict[str, Any]
    base_dir: Path

    @property
    def outputs_dir(self) -> Path:
        return self.base_dir / self.raw.get("outputs_dir", "outputs")

    @property
    def pages_dir(self) -> Path:
        return self.base_dir / self.raw.get("pages_dir", "docs/latest")


def load_config(path: str | Path) -> ProjectConfig:
    path = Path(path).resolve()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return ProjectConfig(raw=raw, base_dir=path.parent.parent if path.parent.name == 'config' else path.parent)
