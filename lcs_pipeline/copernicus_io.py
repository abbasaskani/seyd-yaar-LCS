from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import json

import copernicusmarine
import xarray as xr


def _coord_limits(parts) -> tuple[Any, Any]:
    time_min = None
    time_max = None
    for part in parts:
        try:
            coords = part.get_coordinates()
        except Exception:
            coords = []
        for coord in coords:
            sid = getattr(coord, "coordinate_id", "") or getattr(coord, "name", "") or getattr(coord, "standard_name", "")
            if sid == "time" or sid == "valid_time":
                time_min = getattr(coord, "minimum_value", time_min)
                time_max = getattr(coord, "maximum_value", time_max)
    return time_min, time_max


def describe_dataset(dataset_id: str) -> dict[str, Any]:
    cat = copernicusmarine.describe(dataset_id=dataset_id, disable_progress_bar=True)
    ds = cat.products[0].datasets[0]
    version = ds.versions[0]
    parts = version.parts
    variables = []
    for part in parts:
        for service in getattr(part, "services", []) or []:
            for var in getattr(service, "variables", []) or []:
                variables.append({
                    "short_name": getattr(var, "short_name", None),
                    "standard_name": getattr(var, "standard_name", None),
                    "units": getattr(var, "units", None),
                })
    time_min, time_max = _coord_limits(parts)
    return {
        "dataset_id": ds.dataset_id,
        "dataset_name": ds.dataset_name,
        "time_min": time_min,
        "time_max": time_max,
        "variables": variables,
    }


def parse_dataset_time_limit(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        x = float(value)
        if x > 1e16:
            x /= 1e9
        elif x > 1e12:
            x /= 1e3
        return datetime.fromtimestamp(x, tz=timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    return None


def resolve_target_time(run_cfg: dict[str, Any], ds_meta: dict[str, Any]) -> tuple[datetime, datetime, str]:
    mode = run_cfg.get("date_mode", "today")
    dataset_end = parse_dataset_time_limit(ds_meta.get("time_max"))
    dataset_start = parse_dataset_time_limit(ds_meta.get("time_min"))
    lag = int(run_cfg.get("analysis_lag_hours", 6))
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    if mode == "custom":
        target = datetime.fromisoformat(run_cfg["custom_date"].replace("Z", "+00:00")).astimezone(timezone.utc)
    elif mode == "tomorrow":
        target = (now + timedelta(days=1)).replace(hour=12)
    else:
        target = now - timedelta(hours=lag)
    if dataset_end is not None:
        target = min(target, dataset_end)
    start = target - timedelta(days=float(run_cfg.get("backward_days", 7)))
    if dataset_start is not None and start < dataset_start:
        start = dataset_start
    return start, target, mode




def resolve_requested_variables(ds_meta: dict[str, Any], u_candidates: list[str], v_candidates: list[str]) -> list[str]:
    short_names = []
    standard_to_short = {}
    for item in ds_meta.get("variables", []) or []:
        short = item.get("short_name")
        std = item.get("standard_name")
        if short:
            short_names.append(short)
        if std and short:
            standard_to_short[std] = short

    def _pick(candidates: list[str]) -> str:
        for cand in candidates:
            if cand in short_names:
                return cand
            mapped = standard_to_short.get(cand)
            if mapped:
                return mapped
        available = ", ".join(sorted(set(short_names)))
        raise KeyError(f"Could not resolve requested variable from candidates {candidates!r}. Available dataset variables: {available}")

    u_var = _pick(u_candidates)
    v_var = _pick(v_candidates)
    return [u_var, v_var]

def estimate_subset(dataset_id: str, variables: list[str], lon_min: float, lon_max: float, lat_min: float, lat_max: float, start_dt: datetime, end_dt: datetime, coordinates_selection_method: str = "nearest") -> dict[str, Any]:
    resp = copernicusmarine.subset(
        dataset_id=dataset_id,
        variables=variables,
        minimum_longitude=lon_min,
        maximum_longitude=lon_max,
        minimum_latitude=lat_min,
        maximum_latitude=lat_max,
        start_datetime=start_dt.isoformat(),
        end_datetime=end_dt.isoformat(),
        coordinates_selection_method=coordinates_selection_method,
        file_format="netcdf",
        dry_run=True,
        disable_progress_bar=True,
    )
    return {
        "file_size": getattr(resp, "file_size", None),
        "data_transfer_size": getattr(resp, "data_transfer_size", None),
        "coordinates_extent": getattr(resp, "coordinates_extent", None),
        "variables": getattr(resp, "variables", None),
    }


def download_subset(dataset_id: str, variables: list[str], lon_min: float, lon_max: float, lat_min: float, lat_max: float, start_dt: datetime, end_dt: datetime, output_path: str | Path, coordinates_selection_method: str = "nearest") -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    copernicusmarine.subset(
        dataset_id=dataset_id,
        variables=variables,
        minimum_longitude=lon_min,
        maximum_longitude=lon_max,
        minimum_latitude=lat_min,
        maximum_latitude=lat_max,
        start_datetime=start_dt.isoformat(),
        end_datetime=end_dt.isoformat(),
        coordinates_selection_method=coordinates_selection_method,
        output_directory=str(output_path.parent),
        output_filename=output_path.name,
        file_format="netcdf",
        overwrite=True,
        disable_progress_bar=True,
    )
    return output_path


def open_subset(path: str | Path) -> xr.Dataset:
    return xr.open_dataset(Path(path))


def candidate_velocity_vars(ds: xr.Dataset, u_candidates: list[str], v_candidates: list[str]) -> tuple[str, str]:
    u_var = next((name for name in u_candidates if name in ds.data_vars), None)
    v_var = next((name for name in v_candidates if name in ds.data_vars), None)
    if u_var is None or v_var is None:
        available = ", ".join(sorted(ds.data_vars))
        raise KeyError(f"Could not resolve velocity variables. Available variables: {available}")
    return u_var, v_var


def guess_coord_name(ds: xr.Dataset, candidates: list[str]) -> str:
    for name in candidates:
        if name in ds.coords or name in ds.dims:
            return name
    raise KeyError(f"None of the coordinate candidates {candidates!r} were found.")


def normalize_velocity_dataset(ds: xr.Dataset, u_var: str, v_var: str) -> xr.Dataset:
    lon_name = guess_coord_name(ds, ["longitude", "lon", "x"])
    lat_name = guess_coord_name(ds, ["latitude", "lat", "y"])
    time_name = guess_coord_name(ds, ["time", "valid_time"])

    work = ds[[u_var, v_var]].copy()
    if lon_name != "longitude":
        work = work.rename({lon_name: "longitude"})
    if lat_name != "latitude":
        work = work.rename({lat_name: "latitude"})
    if time_name != "time":
        work = work.rename({time_name: "time"})
    if "depth" in work.coords:
        work = work.sel(depth=work["depth"].min(), method="nearest")
    if "depth" in work.dims:
        work = work.isel(depth=0)
    work = work.sortby("longitude").sortby("latitude").sortby("time")
    return work.transpose("time", "latitude", "longitude")


def subset_meta_payload(dataset_id: str, bbox: dict[str, float], start_dt: datetime, target_dt: datetime, mode_label: str, estimate: dict[str, Any], raw_path: str) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "bbox": bbox,
        "window_start_utc": start_dt.isoformat(),
        "window_end_utc": target_dt.isoformat(),
        "run_label": mode_label,
        "estimate": estimate,
        "raw_subset_path": raw_path,
    }


def reuse_subset_if_match(meta_path: Path, subset_path: Path, desired_meta: dict[str, Any]) -> bool:
    if not meta_path.exists() or not subset_path.exists():
        return False
    try:
        old = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    keys = ["dataset_id", "bbox", "window_start_utc", "window_end_utc", "run_label"]
    return all(old.get(k) == desired_meta.get(k) for k in keys)
