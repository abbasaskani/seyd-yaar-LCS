from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lcs_pipeline.config import load_config
from lcs_pipeline.copernicus_io import describe_dataset


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    cfg = load_config(args.config)
    meta = describe_dataset(cfg.dataset_id)
    print(json.dumps(meta, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
