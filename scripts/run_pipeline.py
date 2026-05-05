from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from lcs_pipeline.config import load_config
from lcs_pipeline.coords import aoi_from_geojson, bbox_info
from lcs_pipeline.copernicus_io import (
    describe_dataset,
    estimate_subset,
    download_subset,
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
    p = argparse.ArgumentParser(description="Run Seyd Yar LCS pipeline for one target horizon")
    p.add_argument("--config", default="config/defaults.json")
    p.add_argument("--offset-days", type=int, default=0)
    p.add_argument("--run-label", default=None)
    p.add_argument("--preset", default=None, help="timezone preset key override")
    p.add_argument("--bbox", nargs=4, type=float, metavar=("LON_MIN", "LON_MAX", "LAT_MIN", "LAT_MAX"))
    p.add_argument("--aoi-file", default=None)
    p.add_argument("--mode", default="manual")
    return p.parse_args()


def resolve_aoi(project, args):
    cfg = project.raw
    if args.aoi_file:
        path = project.resolve_path(args.aoi_file)
        if path.exists():
            return aoi_from_geojson(path), "geojson_override"
    cfg_aoi = project.resolve_path(cfg.get("aoi_geojson", "config/aoi/current.geojson"))
    if cfg_aoi.exists():
        return aoi_from_geojson(cfg_aoi), "geojson"
    if args.bbox:
        lon_min, lon_max, lat_min, lat_max = args.bbox
        return bbox_info({"lon_min": lon_min, "lon_max": lon_max, "lat_min": lat_min, "lat_max": lat_max}), "bbox_override"
    return bbox_info(cfg["default_bbox"]), "bbox_default"


def main() -> None:
    args = parse_args()
    project = load_config(args.config)
    cfg = project.raw
    out_root = project.outputs_dir
    out_root.mkdir(parents=True, exist_ok=True)

    aoi_info, aoi_mode = resolve_aoi(project, args)
    tz_decision = select_preset(cfg, aoi_info.centroid_lon, aoi_info.centroid_lat, override_key=args.preset)

    now_utc = datetime.now(timezone.utc)
    base_local = now_utc.astimezone(datetime.now().astimezone().tzinfo)
    # nominal local date is based on selected preset local time
    preset_tz = tz_decision.preset.tz
    from zoneinfo import ZoneInfo
    local_today = now_utc.astimezone(ZoneInfo(preset_tz)).replace(hour=0, minute=0, second=0, microsecond=0)
    target_local_date = local_today + timedelta(days=int(args.offset_days))
    nominal_local, windows_utc, subset_end_utc = build_target_windows(cfg, target_local_date, preset_tz)
    subset_start_utc = windows_utc[0][0] - timedelta(days=float(cfg.get("backward_days", 7)))

    ds_meta = describe_dataset(cfg["dataset_id"])
    u_var, v_var = resolve_requested_variables(ds_meta, cfg["u_variable_candidates"], cfg["v_variable_candidates"])
    variables = [u_var, v_var]

    run_label = args.run_label or f"day_{args.offset_days:+d}".replace("+", "plus").replace("-", "minus")
    run_dir = out_root / "latest" / run_label
    run_dir.mkdir(parents=True, exist_ok=True)

    estimate = estimate_subset(
        dataset_id=cfg["dataset_id"],
        bbox=aoi_info.bbox,
        variables=variables,
        start_utc=subset_start_utc,
        end_utc=subset_end_utc,
        coordinates_selection_method=cfg.get("coordinates_selection_method", "nearest"),
    )
    (run_dir / "estimate_report.json").write_text(json.dumps(estimate, indent=2, ensure_ascii=False), encoding="utf-8")

    subset_path = download_subset(
        dataset_id=cfg["dataset_id"],
        bbox=aoi_info.bbox,
        variables=variables,
        start_utc=subset_start_utc,
        end_utc=subset_end_utc,
        coordinates_selection_method=cfg.get("coordinates_selection_method", "nearest"),
        output_path=run_dir / "subset_raw.nc",
    )

    ds = normalize_dataset(subset_path, u_var, v_var)
    times = [t.astype("datetime64[s]").tolist().replace(tzinfo=timezone.utc) if hasattr(t.astype("datetime64[s]").tolist(), 'replace') else None for t in ds["time"].values]
    # robust conversion
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
    ftle_out.metadata = {
        "run_label": run_label,
        "mode": args.mode,
        "aoi_mode": aoi_mode,
        "aoi_source": aoi_info.source_path,
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

    save_ftle_netcdf(ftle_out, run_dir / "ftle.nc")
    save_hotspots_csv(ftle_out, run_dir / "hotspots.csv")
    save_hotspots_geojson(ftle_out, run_dir / "hotspots.geojson")
    save_clusters_geojson(ftle_out, run_dir / "clusters.geojson")
    save_ridges_geojson(ftle_out, run_dir / "ridges.geojson")
    save_field_layers_json(ftle_out, run_dir / "field_layers.json")
    plot_field_map(
        ftle_out,
        run_dir / "map_ftle.png",
        title=f"FTLE | {run_label} | {selection.actual_local.strftime('%Y-%m-%d %H:%M %Z')} | {selection.actual_utc.strftime('%Y-%m-%d %H:%M UTC')}",
        layer_name="ftle_smooth",
        colorbar_label="FTLE (smoothed)",
    )
    save_summary_json(ftle_out, run_dir / "summary.json")
    print(json.dumps({"run_dir": str(run_dir), "selection": ftle_out.metadata}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
