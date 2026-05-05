from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from lcs_pipeline.config import load_config
from lcs_pipeline.coords import aoi_from_geojson
from lcs_pipeline.copernicus_io import describe_dataset, estimate_subset, resolve_requested_variables
from lcs_pipeline.timezones import build_target_windows, select_preset


def main() -> None:
    project = load_config("config/defaults.json")
    cfg = project.raw
    aoi_path = project.aoi_path
    if not aoi_path.exists():
        raise FileNotFoundError(f"AOI file not found at {aoi_path}")
    aoi = aoi_from_geojson(aoi_path)
    tz_decision = select_preset(cfg, aoi.centroid_lon, aoi.centroid_lat)
    now_utc = datetime.now(timezone.utc)
    local_today = now_utc.astimezone(ZoneInfo(tz_decision.preset.tz)).replace(hour=0, minute=0, second=0, microsecond=0)
    nominal_local, windows_utc, subset_end_utc = build_target_windows(cfg, local_today, tz_decision.preset.tz)
    subset_start_utc = windows_utc[0][0] - timedelta(days=float(cfg.get("backward_days", 7)))
    ds_meta = describe_dataset(cfg["dataset_id"])
    u_var, v_var = resolve_requested_variables(ds_meta, cfg["u_variable_candidates"], cfg["v_variable_candidates"])
    estimate = estimate_subset(
        cfg["dataset_id"],
        aoi.bbox,
        [u_var, v_var],
        subset_start_utc,
        subset_end_utc,
        cfg.get("coordinates_selection_method", "nearest"),
    )
    estimate.update(
        {
            "aoi": aoi.bbox,
            "timezone_preset": tz_decision.preset.__dict__,
            "timezone_auto_selected": tz_decision.auto_selected,
            "nominal_local": nominal_local.isoformat(),
        }
    )
    out = project.outputs_dir / "estimate_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(estimate, indent=2, ensure_ascii=False), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
