from __future__ import annotations

import argparse
import json
from pathlib import Path

from lcs_pipeline.copernicus_io import (
    describe_dataset_safe,
    download_subset,
    estimate_subset,
    make_json_safe,
    resolve_requested_variables,
    resolve_target_time,
    subset_meta_payload,
)
from lcs_pipeline.coords import build_bbox_from_values
from lcs_pipeline.detect import detect_hotspots_and_clusters
from lcs_pipeline.ftle import compute_backward_ftle
from lcs_pipeline.preprocess import open_velocity_subset
from lcs_pipeline.render import render_ftle_png, render_mp4
from lcs_pipeline.utils import ensure_dir, load_config, merge_runtime_overrides


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("--mode", choices=["today", "tomorrow", "custom"], default="today")
    p.add_argument("--custom-date", default="")
    p.add_argument("--backward-days", type=int, default=None)
    p.add_argument("--lon-min", type=float, default=None)
    p.add_argument("--lon-max", type=float, default=None)
    p.add_argument("--lat-min", type=float, default=None)
    p.add_argument("--lat-max", type=float, default=None)
    p.add_argument("--skip-confirm", action="store_true")
    p.add_argument("--label", default="")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)

    runtime = {
        "date_mode": args.mode,
        "custom_date": args.custom_date,
        "backward_days": args.backward_days,
        "bbox": {
            "lon_min": args.lon_min,
            "lon_max": args.lon_max,
            "lat_min": args.lat_min,
            "lat_max": args.lat_max,
        },
    }
    cfg = merge_runtime_overrides(cfg, runtime)

    bbox = build_bbox_from_values(
        cfg.default_bbox.lon_min,
        cfg.default_bbox.lon_max,
        cfg.default_bbox.lat_min,
        cfg.default_bbox.lat_max,
    )

    label = args.label or args.mode
    out_root = Path(cfg.base_dir) / "outputs" / "latest" / label
    raw_dir = ensure_dir(out_root / "raw")
    processed_dir = ensure_dir(out_root / "processed")
    media_dir = ensure_dir(out_root / "media")

    ds_meta = describe_dataset_safe(cfg.dataset.dataset_id)
    start_dt, target_dt = resolve_target_time(cfg, ds_meta)
    variables = resolve_requested_variables(ds_meta, cfg.dataset)

    estimate = estimate_subset(
        dataset_id=cfg.dataset.dataset_id,
        dataset_version=cfg.dataset.dataset_version,
        bbox=bbox,
        start_dt=start_dt,
        end_dt=target_dt,
        variables=variables,
        username=cfg.credentials.username,
        password=cfg.credentials.password,
    )

    pre = {
        "dataset_id": cfg.dataset.dataset_id,
        "dataset_name": ds_meta.get("dataset_name"),
        "dataset_time_coverage": {
            "time_min": str(ds_meta.get("time_min")),
            "time_max": str(ds_meta.get("time_max")),
        },
        "run_label": label,
        "bbox": make_json_safe(bbox),
        "target_time_utc": target_dt.isoformat(),
        "window_start_utc": start_dt.isoformat(),
        "window_end_utc": target_dt.isoformat(),
        "estimated_final_subset_file": estimate.get("estimated_final_subset_file"),
        "estimated_total_data_transfer": estimate.get("estimated_total_data_transfer"),
        "variables": variables,
        "coordinates_extent": estimate.get("coordinates_extent"),
    }
    print(json.dumps(pre, indent=2, ensure_ascii=False))
    (out_root / "pre_download_report.json").write_text(
        json.dumps(make_json_safe(pre), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    subset_path = raw_dir / "currents_subset.nc"
    print("Downloading raw subset from Copernicus...")
    download_subset(
        dataset_id=cfg.dataset.dataset_id,
        dataset_version=cfg.dataset.dataset_version,
        bbox=bbox,
        start_dt=start_dt,
        end_dt=target_dt,
        variables=variables,
        output_path=subset_path,
        username=cfg.credentials.username,
        password=cfg.credentials.password,
    )

    desired_meta = subset_meta_payload(
        dataset_id=cfg.dataset.dataset_id,
        bbox=bbox,
        start_dt=start_dt,
        end_dt=target_dt,
        variables=variables,
        output_path=subset_path,
    )
    (raw_dir / "subset_meta.json").write_text(
        json.dumps(make_json_safe(desired_meta), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    ds = open_velocity_subset(subset_path, cfg.dataset)
    ftle_path = processed_dir / "ftle_field.nc"
    ftle_ds = compute_backward_ftle(ds, cfg.lcs, ftle_path)

    summary = detect_hotspots_and_clusters(ftle_ds, processed_dir, top_n=5)
    png_path = media_dir / "ftle_map.png"
    render_ftle_png(ftle_ds, summary, png_path)

    mp4_path = media_dir / "animation.mp4"
    render_mp4(ds, mp4_path)

    mp4_rel = str(mp4_path.relative_to(cfg.base_dir)).replace("\\", "/")
    png_rel = str(png_path.relative_to(cfg.base_dir)).replace("\\", "/")

    latest_summary = {
        "label": label,
        "target_time_utc": target_dt.isoformat(),
        "window_start_utc": start_dt.isoformat(),
        "window_end_utc": target_dt.isoformat(),
        "bbox": make_json_safe(bbox),
        "variables": variables,
        "media": {"png": png_rel, "mp4": mp4_rel},
        "summary": make_json_safe(summary),
    }
    (out_root / "latest_summary.json").write_text(
        json.dumps(latest_summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print("Run completed successfully.")


if __name__ == "__main__":
    main()
