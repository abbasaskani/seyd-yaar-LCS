from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
            sid = getattr(coord, 'coordinate_id', '') or getattr(coord, 'name', '') or getattr(coord, 'standard_name', '')
            if sid in {'time', 'valid_time'}:
                time_min = getattr(coord, 'minimum_value', time_min)
                time_max = getattr(coord, 'maximum_value', time_max)
    return time_min, time_max


def describe_dataset(dataset_id: str) -> dict[str, Any]:
    cat = copernicusmarine.describe(dataset_id=dataset_id, disable_progress_bar=True)
    prod = cat.products[0]
    ds = prod.datasets[0]
    version = ds.versions[0]
    part = version.parts[0]
    time_min, time_max = _coord_limits(version.parts)
    variables = []
    try:
        for var in part.services[0].variables:
            variables.append({
                'short_name': getattr(var, 'short_name', None),
                'standard_name': getattr(var, 'standard_name', None),
                'units': getattr(var, 'units', None),
            })
    except Exception:
        pass
    return {
        'dataset_id': ds.dataset_id,
        'dataset_name': ds.dataset_name,
        'product_id': prod.product_id,
        'part_name': getattr(part, 'name', None),
        'time_min': time_min,
        'time_max': time_max,
        'variables': variables,
    }


def resolve_requested_variables(ds_meta: dict[str, Any], u_candidates: list[str], v_candidates: list[str]) -> tuple[str, str]:
    short_names = []
    standard_to_short = {}
    for item in ds_meta.get('variables', []) or []:
        short = item.get('short_name')
        std = item.get('standard_name')
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
        raise KeyError(f'Could not resolve requested variable from {candidates!r}; available={sorted(set(short_names))}')

    return _pick(u_candidates), _pick(v_candidates)


def estimate_subset(dataset_id: str, bbox: dict[str, float], variables: list[str], start_utc: datetime, end_utc: datetime, coordinates_selection_method: str = 'nearest') -> dict[str, Any]:
    response = copernicusmarine.subset(
        dataset_id=dataset_id,
        variables=variables,
        minimum_longitude=float(bbox['lon_min']),
        maximum_longitude=float(bbox['lon_max']),
        minimum_latitude=float(bbox['lat_min']),
        maximum_latitude=float(bbox['lat_max']),
        start_datetime=start_utc,
        end_datetime=end_utc,
        coordinates_selection_method=coordinates_selection_method,
        dry_run=True,
    )
    return {
        'repr': repr(response),
        'start_utc': start_utc.isoformat(),
        'end_utc': end_utc.isoformat(),
        'bbox': bbox,
        'variables': variables,
    }


def download_subset(dataset_id: str, bbox: dict[str, float], variables: list[str], start_utc: datetime, end_utc: datetime, coordinates_selection_method: str, output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    copernicusmarine.subset(
        dataset_id=dataset_id,
        variables=variables,
        minimum_longitude=float(bbox['lon_min']),
        maximum_longitude=float(bbox['lon_max']),
        minimum_latitude=float(bbox['lat_min']),
        maximum_latitude=float(bbox['lat_max']),
        start_datetime=start_utc,
        end_datetime=end_utc,
        coordinates_selection_method=coordinates_selection_method,
        output_filename=output_path.name,
        output_directory=str(output_path.parent),
    )
    if output_path.exists():
        return output_path
    matches = sorted(output_path.parent.glob(f'{output_path.stem}*.nc'))
    if not matches:
        raise FileNotFoundError(f'Subset download finished but file was not found near {output_path}')
    return matches[0]


def normalize_dataset(ds_path: str | Path, u_var: str, v_var: str) -> xr.Dataset:
    ds = xr.open_dataset(ds_path)
    rename_map = {}
    if 'longitude' not in ds.coords and 'lon' in ds.coords:
        rename_map['lon'] = 'longitude'
    if 'latitude' not in ds.coords and 'lat' in ds.coords:
        rename_map['lat'] = 'latitude'
    if rename_map:
        ds = ds.rename(rename_map)
    if 'time' not in ds.coords:
        raise KeyError("Normalized subset dataset has no 'time' coordinate")
    for var in (u_var, v_var):
        if var not in ds:
            raise KeyError(f'Required velocity variable {var!r} is missing from subset dataset')
    return ds.sortby('time')
