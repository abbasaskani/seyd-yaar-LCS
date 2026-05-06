from __future__ import annotations

import argparse
import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from zoneinfo import ZoneInfo

from lcs_pipeline.config import load_config
from lcs_pipeline.coords import aoi_from_geojson
from lcs_pipeline.copernicus_io import (
    describe_dataset,
    download_subset,
    estimate_subset,
    normalize_dataset,
    resolve_requested_variables,
)
from lcs_pipeline.ftle import compute_attracting_ftle
from lcs_pipeline.outputs import (
    plot_field_map,
    save_clusters_geojson,
    save_field_layers_json,
    save_ftle_netcdf,
    save_hotspots_csv,
    save_hotspots_geojson,
    save_ridges_geojson,
    save_summary_json,
)
from lcs_pipeline.timezones import build_target_windows, choose_actual_time, select_preset


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run Seyd Yar LCS pipeline for one target")
    p.add_argument("--config", default="config/defaults.json")
    p.add_argument("--offset-days", type=int, default=0)
    p.add_argument("--run-label", default=None)
    p.add_argument("--preset", default=None, help="timezone preset key override")
    p.add_argument("--aoi-file", default=None)
    p.add_argument("--mode", default="routine")
    p.add_argument("--target-local-date", default=None, help="YYYY-MM-DD local date override")
    p.add_argument("--target-local-datetime", default=None, help="ISO local datetime override without timezone or with timezone")
    return p.parse_args()


def resolve_aoi(project, args):
    path = project.resolve_path(args.aoi_file) if args.aoi_file else project.aoi_path
    if not path.exists():
        raise FileNotFoundError(f"AOI file not found at {path}")
    return aoi_from_geojson(path), str(path)


def parse_local_target(args: argparse.Namespace, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    now_utc = datetime.now(timezone.utc)
    local_today = now_utc.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    if args.target_local_datetime:
        dt = datetime.fromisoformat(args.target_local_datetime)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        else:
            dt = dt.astimezone(tz)
        return dt
    if args.target_local_date:
        d = date.fromisoformat(args.target_local_date)
        return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=tz)
    return local_today + timedelta(days=int(args.offset_days))


def iso_utc_tag(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def main() -> None:
    args = parse_args()
    project = load_config(args.config)
    cfg = project.raw
    project.outputs_dir.mkdir(parents=True, exist_ok=True)
    project.archive_dir.mkdir(parents=True, exist_ok=True)

    aoi_info, aoi_source = resolve_aoi(project, args)
    tz_decision = select_preset(cfg, aoi_info.centroid_lon, aoi_info.centroid_lat, override_key=args.preset)
    preset_tz = tz_decision.preset.tz
    target_anchor_local = parse_local_target(args, preset_tz)
    target_local_date = target_anchor_local.replace(hour=0, minute=0, second=0, microsecond=0)
    nominal_local, windows_utc, subset_end_utc = build_target_windows(cfg, target_local_date, preset_tz)
    subset_start_utc = windows_utc[0][0] - timedelta(days=float(cfg.get("backward_days", 7)))

    ds_meta = describe_dataset(cfg["dataset_id"])
    u_var, v_var = resolve_requested_variables(ds_meta, cfg["u_variable_candidates"], cfg["v_variable_candidates"])
    variables = [u_var, v_var]

    label_default = f"day_{args.offset_days:+d}".replace("+", "plus").replace("-", "minus")
    run_label = args.run_label or label_default

    staging_dir = project.outputs_dir / "_staging" / f"{run_label}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    ensure_clean_dir(staging_dir)

    estimate = estimate_subset(
        dataset_id=cfg["dataset_id"],
        bbox=aoi_info.bbox,
        variables=variables,
        start_utc=subset_start_utc,
        end_utc=subset_end_utc,
        coordinates_selection_method=cfg.get("coordinates_selection_method", "nearest"),
    )
    (staging_dir / "estimate_report.json").write_text(json.dumps(estimate, indent=2, ensure_ascii=False), encoding="utf-8")

    subset_path = download_subset(
        dataset_id=cfg["dataset_id"],
        bbox=aoi_info.bbox,
        variables=variables,
        start_utc=subset_start_utc,
        end_utc=subset_end_utc,
        coordinates_selection_method=cfg.get("coordinates_selection_method", "nearest"),
        output_path=staging_dir / "subset_raw.nc",
    )

    ds = normalize_dataset(subset_path, u_var, v_var)
    actual_candidates = []
    for val in ds["time"].values:
        if isinstance(val, np.datetime64):
            s = np.datetime_as_string(val, unit="s")
            actual_candidates.append(datetime.fromisoformat(s).replace(tzinfo=timezone.utc))
    selection = choose_actual_time(actual_candidates, windows_utc, tz_decision.preset, tz_decision.auto_selected, nominal_local)

    chosen_np = np.datetime64(selection.actual_utc.replace(tzinfo=None))
    ds_run = ds.sel(time=ds["time"] <= chosen_np)
    if ds_run.sizes.get("time", 0) < 2:
        ds_run = ds

    ftle_out = compute_attracting_ftle(ds_run, u_var=u_var, v_var=v_var, config_raw=cfg, aoi_info=aoi_info)
    existing_meta = ftle_out.metadata or {}
    ftle_out.metadata = {**existing_meta,
        "run_label": run_label,
        "mode": args.mode,
        "aoi_source": aoi_source,
        "centroid_lon": aoi_info.centroid_lon,
        "centroid_lat": aoi_info.centroid_lat,
        "bbox": aoi_info.bbox,
        "timezone_preset_key": tz_decision.preset.key,
        "timezone_preset_label": tz_decision.preset.label,
        "timezone_name": tz_decision.preset.tz,
        "timezone_utc_offset_hint": tz_decision.preset.utc_offset_hint,
        "timezone_auto_selected": tz_decision.auto_selected,
        "nominal_local_target": selection.local_nominal.isoformat(),
        "actual_selected_utc": selection.actual_utc.isoformat(),
        "actual_selected_local": selection.actual_local.isoformat(),
        "fallback_status": selection.fallback_status,
        "requested_target_date_local": selection.requested_target_date_local,
        "backward_days": cfg.get("backward_days", 7),
    }

    save_ftle_netcdf(ftle_out, staging_dir / "ftle.nc")
    save_hotspots_csv(ftle_out, staging_dir / "hotspots.csv")
    save_hotspots_geojson(ftle_out, staging_dir / "hotspots.geojson")
    save_clusters_geojson(ftle_out, staging_dir / "clusters.geojson")
    save_ridges_geojson(ftle_out, staging_dir / "ridges.geojson")
    save_field_layers_json(ftle_out, staging_dir / "field_layers.json")
    plot_field_map(
        ftle_out,
        staging_dir / "map_ftle.png",
        title=f"FTLE | {run_label} | {selection.actual_local.strftime('%Y-%m-%d %H:%M %Z')} | {selection.actual_utc.strftime('%Y-%m-%d %H:%M UTC')}",
        layer_name="ftle_smooth",
        colorbar_label="FTLE (smoothed)",
    )
    save_summary_json(ftle_out, staging_dir / "summary.json")

    archive_key = iso_utc_tag(selection.actual_utc)
    archive_dir = project.archive_dir / archive_key
    ensure_clean_dir(archive_dir)
    for item in staging_dir.iterdir():
        target = archive_dir / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)

    latest_dir = project.outputs_dir / "latest" / run_label
    ensure_clean_dir(latest_dir)
    for item in archive_dir.iterdir():
        target = latest_dir / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)

    shutil.rmtree(staging_dir, ignore_errors=True)
    print(json.dumps({"archive_dir": str(archive_dir), "latest_dir": str(latest_dir), "selection": ftle_out.metadata}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
