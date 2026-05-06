from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from typing import Any

import numpy as np
import xarray as xr
from scipy.ndimage import distance_transform_edt, gaussian_filter, label, maximum_filter
from scipy.spatial import ConvexHull

from .coords import AOIInfo, local_xy_from_lonlat, lonlat_from_local_xy, polygon_mask


@dataclass
class FTLEOutputs:
    ftle: np.ndarray
    ftle_smooth: np.ndarray
    ridge_curves_xy: list[np.ndarray]
    ridge_curves_lonlat: list[np.ndarray]
    ridge_support: np.ndarray
    hotspots: list[dict[str, Any]]
    clusters: list[dict[str, Any]]
    lon_grid: np.ndarray
    lat_grid: np.ndarray
    x_grid: np.ndarray
    y_grid: np.ndarray
    target_time: str
    u_variable: str
    v_variable: str
    aoi_mask: np.ndarray | None = None
    ocean_mask: np.ndarray | None = None
    metadata: dict[str, Any] | None = None
    persistence_3d: np.ndarray | None = None
    persistence_5d: np.ndarray | None = None
    balanced_composite: np.ndarray | None = None
    physics_first_composite: np.ndarray | None = None
    accumulation_potential_balanced: np.ndarray | None = None
    accumulation_potential_physics_first: np.ndarray | None = None


def _upsampled_axis(arr: np.ndarray, factor: float) -> np.ndarray:
    n_native = len(arr)
    n_out = max(n_native, int(round((n_native - 1) * factor)) + 1)
    return np.linspace(float(arr[0]), float(arr[-1]), n_out)


def _pick_well_separated_points(candidates: list[dict[str, Any]], min_sep_px: int, top_n: int) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    for cand in candidates:
        i, j = cand['i'], cand['j']
        ok = True
        for prev in chosen:
            if (i - prev['i']) ** 2 + (j - prev['j']) ** 2 < min_sep_px**2:
                ok = False
                break
        if ok:
            chosen.append(cand)
            if len(chosen) >= top_n:
                break
    return chosen


def _component_polygon(lons: np.ndarray, lats: np.ndarray) -> list[list[float]]:
    pts = np.column_stack([lons, lats])
    if len(pts) == 1:
        lon, lat = pts[0]
        eps = 1e-3
        return [[lon - eps, lat - eps], [lon + eps, lat - eps], [lon + eps, lat + eps], [lon - eps, lat + eps], [lon - eps, lat - eps]]
    if len(pts) == 2:
        p0, p1 = pts
        return [p0.tolist(), p1.tolist(), p1.tolist(), p0.tolist(), p0.tolist()]
    hull = ConvexHull(pts)
    poly = pts[hull.vertices].tolist()
    poly.append(poly[0])
    return poly


def robust_normalize(field: np.ndarray, q_low: float = 5.0, q_high: float = 95.0) -> np.ndarray:
    arr = np.array(field, dtype=float, copy=True)
    arr[~np.isfinite(arr)] = np.nan
    lo = np.nanpercentile(arr, q_low)
    hi = np.nanpercentile(arr, q_high)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        out = np.zeros_like(arr)
        out[np.isfinite(arr)] = 0.0
        return out
    out = (arr - lo) / (hi - lo)
    out = np.clip(out, 0.0, 1.0)
    out[~np.isfinite(arr)] = np.nan
    return out


def compute_ridge_support(lon_grid: np.ndarray, lat_grid: np.ndarray, ridge_curves_lonlat: list[np.ndarray], ftle_smooth: np.ndarray, d0_deg: float = 0.15) -> np.ndarray:
    if not ridge_curves_lonlat:
        return np.zeros_like(ftle_smooth, dtype=float)
    support_terms = []
    ftle_norm = robust_normalize(ftle_smooth)
    lon_axis = lon_grid[:, 0]
    lat_axis = lat_grid[0, :]
    for ridge in ridge_curves_lonlat:
        if len(ridge) == 0:
            continue
        d2 = (lon_grid[..., None] - ridge[:, 0]) ** 2 + (lat_grid[..., None] - ridge[:, 1]) ** 2
        d = np.sqrt(np.nanmin(d2, axis=-1))
        ix = np.abs(lon_axis[:, None] - ridge[:, 0][None, :]).argmin(axis=0)
        iy = np.abs(lat_axis[None, :] - ridge[:, 1][:, None]).argmin(axis=1)
        strengths = [float(ftle_norm[a, b]) for a, b in zip(ix, iy)]
        ridge_strength = float(np.nanmean(strengths)) if strengths else 0.5
        term = np.clip(ridge_strength, 0.0, 1.0) * np.exp(-d / max(d0_deg, 1e-6))
        support_terms.append(np.clip(term, 0.0, 1.0))
    if not support_terms:
        return np.zeros_like(ftle_smooth, dtype=float)
    prod = np.ones_like(ftle_smooth, dtype=float)
    for term in support_terms:
        prod *= 1.0 - term
    return np.clip(1.0 - prod, 0.0, 1.0)


def _first_existing(names: list[str], candidates: list[str]) -> str | None:
    lowered = {str(n).lower(): str(n) for n in names}
    for cand in candidates:
        if cand.lower() in lowered:
            return lowered[cand.lower()]
    return None


def _fill_invalid_nearest_2d(arr2d: np.ndarray) -> np.ndarray:
    arr2d = np.asarray(arr2d, dtype=float)
    valid = np.isfinite(arr2d)
    if valid.all():
        return arr2d
    if not np.any(valid):
        raise RuntimeError('No finite values available in 2D velocity slice for nearest fill')
    idx = distance_transform_edt(~valid, return_distances=False, return_indices=True)
    return arr2d[tuple(idx)]


def _nearest_mask_resample(native_mask: np.ndarray, lon_native: np.ndarray, lat_native: np.ndarray, lon_out: np.ndarray, lat_out: np.ndarray) -> np.ndarray:
    ix = np.abs(lon_native[:, None] - lon_out[None, :]).argmin(axis=0)
    iy = np.abs(lat_native[:, None] - lat_out[None, :]).argmin(axis=0)
    return native_mask[np.ix_(ix, iy)]


@contextlib.contextmanager
def _suppress_solver_output(enabled: bool):
    if not enabled:
        yield
        return
    devnull = os.open(os.devnull, os.O_WRONLY)
    saved_stdout = os.dup(1)
    saved_stderr = os.dup(2)
    try:
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved_stdout, 1)
        os.dup2(saved_stderr, 2)
        os.close(saved_stdout)
        os.close(saved_stderr)
        os.close(devnull)


def _prepare_velocity_cube(ds: xr.Dataset, var_name: str, target_time: np.datetime64) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    da = ds[var_name]
    notes: list[str] = []

    time_name = _first_existing(list(da.dims), ['time', 'valid_time'])
    lon_name = _first_existing(list(da.dims), ['longitude', 'lon', 'x'])
    lat_name = _first_existing(list(da.dims), ['latitude', 'lat', 'y'])

    if lon_name is None or lat_name is None:
        raise KeyError(f'Could not locate longitude/latitude dims for {var_name}; dims={tuple(da.dims)!r}')

    if time_name is None:
        da = da.expand_dims({'time': [target_time]})
        time_name = 'time'
        notes.append(f'{var_name}: expanded missing time dimension')

    base_dims = {time_name, lon_name, lat_name}
    extra_dims = [d for d in da.dims if d not in base_dims]
    for dim in extra_dims:
        size = int(da.sizes[dim])
        da = da.isel({dim: 0}, drop=True)
        notes.append(f'{var_name}: selected index 0 from extra dim {dim} (size={size})')

    da = da.transpose(time_name, lon_name, lat_name)

    lon = da[lon_name].values.astype(float)
    lat = da[lat_name].values.astype(float)
    time = da[time_name].values
    cube = da.values.astype(np.float64)

    if cube.ndim != 3:
        raise ValueError(f'{var_name}: expected 3D cube after normalization, got shape={cube.shape}')

    if len(lon) > 1 and lon[1] < lon[0]:
        lon = lon[::-1]
        cube = cube[:, ::-1, :]
        notes.append(f'{var_name}: reversed descending longitude axis')
    if len(lat) > 1 and lat[1] < lat[0]:
        lat = lat[::-1]
        cube = cube[:, :, ::-1]
        notes.append(f'{var_name}: reversed descending latitude axis')

    if cube.shape[0] < 2:
        cube = np.repeat(cube, 2, axis=0)
        if len(time) >= 1:
            time = np.array([time[0], target_time])
        notes.append(f'{var_name}: duplicated singleton time slice to keep solver stable')

    return lon, lat, time, cube, notes


def compute_attracting_ftle(ds, u_var: str, v_var: str, config_raw: dict[str, Any], aoi_info: AOIInfo | None = None) -> FTLEOutputs:
    from math import copysign

    from numbacs.diagnostics import C_eig_2D, ftle_from_eig
    from numbacs.extraction import ftle_ordered_ridges
    from numbacs.flows import get_flow_2D, get_interp_arrays_2D
    from numbacs.integration import flowmap_grid_2D

    preprocess_cfg = config_raw.get('velocity_preprocess', {})
    min_valid_time_fraction = float(preprocess_cfg.get('min_valid_time_fraction', 0.5))
    min_valid_ocean_cells = int(preprocess_cfg.get('min_valid_ocean_cells', 25))
    suppress_solver_output = bool(preprocess_cfg.get('suppress_solver_output', True))

    target_time = np.datetime64(ds['time'].values[-1])
    u_lon, u_lat, u_time, u_cube, u_notes = _prepare_velocity_cube(ds, u_var, target_time)
    v_lon, v_lat, v_time, v_cube, v_notes = _prepare_velocity_cube(ds, v_var, target_time)

    if not np.array_equal(u_lon, v_lon) or not np.array_equal(u_lat, v_lat):
        raise ValueError('u/v longitude-latitude grids do not match after normalization')

    lon = u_lon
    lat = u_lat
    time = u_time if len(u_time) >= len(v_time) else v_time

    lon0 = float(lon.mean())
    lat0 = float(lat.mean())
    x_native, _ = local_xy_from_lonlat(lon, np.full_like(lon, lat0), lon0=lon0, lat0=lat0)
    _, y_native = local_xy_from_lonlat(np.full_like(lat, lon0), lat, lon0=lon0, lat0=lat0)
    t_hours = ((time - target_time) / np.timedelta64(1, 'h')).astype(float)

    finite_native = np.isfinite(u_cube) & np.isfinite(v_cube)
    valid_fraction_native = finite_native.mean(axis=0)
    ocean_mask_native = valid_fraction_native >= min_valid_time_fraction
    if not np.any(ocean_mask_native):
        raise RuntimeError('Velocity field contains no valid ocean cells after preprocessing')

    u_filled = np.empty_like(u_cube)
    v_filled = np.empty_like(v_cube)
    for k in range(u_cube.shape[0]):
        u_filled[k] = _fill_invalid_nearest_2d(u_cube[k])
        v_filled[k] = _fill_invalid_nearest_2d(v_cube[k])

    T = -24.0 * float(config_raw['backward_days'])
    t0 = 0.0
    params = np.array([copysign(1.0, T)], dtype=float)

    scale = 3.6
    u = u_filled * scale
    v = v_filled * scale

    grid_vel, C_eval_u, C_eval_v = get_interp_arrays_2D(t_hours, x_native, y_native, u, v)
    funcptr = get_flow_2D(grid_vel, C_eval_u, C_eval_v, extrap_mode='linear')

    factor = float(config_raw.get('compute_grid_factor', 3.0))
    x = _upsampled_axis(x_native, factor)
    y = _upsampled_axis(y_native, factor)
    dx = float(x[1] - x[0]) if len(x) > 1 else 1.0
    dy = float(y[1] - y[0]) if len(y) > 1 else 1.0

    integ = config_raw['integrator']
    with _suppress_solver_output(suppress_solver_output):
        flowmap = flowmap_grid_2D(
            funcptr,
            t0,
            T,
            x,
            y,
            params,
            method=integ.get('method', 'dop853'),
            rtol=float(integ.get('rtol', 1e-6)),
            atol=float(integ.get('atol', 1e-8)),
        )

    eigvals, eigvecs = C_eig_2D(flowmap, dx, dy)
    eigval_max = eigvals[:, :, 1]
    eigvec_max = eigvecs[:, :, :, 1]
    ftle = ftle_from_eig(eigval_max, T)

    ridge_cfg = config_raw['ridge_extraction']
    sigma = float(ridge_cfg.get('smooth_sigma', 1.0))
    ftle_smooth = gaussian_filter(ftle, sigma=sigma, mode='nearest')
    dist_tol = float(ridge_cfg.get('dist_tol_grid_cells', 3.0)) * max(dx, dy)

    ridge_curves_xy = ftle_ordered_ridges(
        ftle_smooth,
        eigvec_max,
        x,
        y,
        dist_tol,
        percentile=float(ridge_cfg.get('percentile', 70)),
        sdd_thresh=float(ridge_cfg.get('sdd_thresh', 0.0)),
    )
    ridge_curves_xy = list(ridge_curves_xy) if ridge_curves_xy is not None else []

    lon_grid_1d, _ = lonlat_from_local_xy(x, np.zeros_like(x), lon0=lon0, lat0=lat0)
    _, lat_grid_1d = lonlat_from_local_xy(np.zeros_like(y), y, lon0=lon0, lat0=lat0)
    lon_grid, lat_grid = np.meshgrid(lon_grid_1d, lat_grid_1d, indexing='ij')
    x_grid, y_grid = np.meshgrid(x, y, indexing='ij')

    ridge_curves_lonlat: list[np.ndarray] = []
    for rc in ridge_curves_xy:
        if rc.size == 0:
            continue
        rlon, rlat = lonlat_from_local_xy(rc[:, 0], rc[:, 1], lon0=lon0, lat0=lat0)
        ridge_curves_lonlat.append(np.column_stack([rlon, rlat]))

    ocean_mask = _nearest_mask_resample(ocean_mask_native, lon, lat, lon_grid_1d, lat_grid_1d)
    final_mask = ocean_mask.copy()
    aoi_mask = None
    if aoi_info is not None:
        aoi_mask = polygon_mask(lon_grid, lat_grid, aoi_info.polygons)
        final_mask &= aoi_mask

    valid_count = int(np.count_nonzero(final_mask))
    if valid_count < min_valid_ocean_cells:
        raise RuntimeError(
            f'Insufficient valid ocean cells after automatic land/island handling: valid_cells={valid_count}, min_required={min_valid_ocean_cells}'
        )

    ftle = np.where(final_mask, ftle, np.nan)
    ftle_smooth = np.where(final_mask, ftle_smooth, np.nan)

    ridge_support = compute_ridge_support(lon_grid, lat_grid, ridge_curves_lonlat, ftle_smooth)
    ridge_support = np.where(final_mask, ridge_support, np.nan)

    hot_cfg = config_raw['hotspots']
    field = np.array(ftle_smooth, copy=True)
    field[~np.isfinite(field)] = np.nan
    valid = np.isfinite(field)
    threshold = np.nanpercentile(field, float(hot_cfg.get('percentile', 98.5)))
    peak_mask = valid & (field >= threshold)
    localmax = field == maximum_filter(field, size=int(hot_cfg.get('localmax_window', 7)), mode='nearest')
    inds = np.argwhere(peak_mask & localmax)
    candidates = []
    for i, j in inds:
        candidates.append(
            {
                'i': int(i),
                'j': int(j),
                'ftle': float(field[i, j]),
                'x_km': float(x_grid[i, j]),
                'y_km': float(y_grid[i, j]),
                'lon': float(lon_grid[i, j]),
                'lat': float(lat_grid[i, j]),
            }
        )
    candidates.sort(key=lambda d: d['ftle'], reverse=True)
    hotspots = _pick_well_separated_points(
        candidates,
        min_sep_px=int(hot_cfg.get('min_separation_px', 8)),
        top_n=int(hot_cfg.get('top_n', 5)),
    )
    for rank, hs in enumerate(hotspots, start=1):
        hs['rank'] = rank

    cl_cfg = config_raw['clusters']
    cluster_thr = np.nanpercentile(field, float(cl_cfg.get('percentile', 94.0)))
    labels, n_labels = label(valid & (field >= cluster_thr))
    clusters = []
    cell_area_km2 = abs(dx * dy)
    for lab in range(1, n_labels + 1):
        mask_lab = labels == lab
        if not np.any(mask_lab):
            continue
        coords = np.argwhere(mask_lab)
        vals = field[mask_lab]
        peak_idx_local = int(np.nanargmax(vals))
        peak_ij = coords[peak_idx_local]
        pts_lon = lon_grid[mask_lab]
        pts_lat = lat_grid[mask_lab]
        polygon = _component_polygon(pts_lon, pts_lat)
        cluster = {
            'cluster_id': lab,
            'n_cells': int(mask_lab.sum()),
            'area_km2': float(mask_lab.sum() * cell_area_km2),
            'peak_ftle': float(vals[peak_idx_local]),
            'peak_lon': float(lon_grid[tuple(peak_ij)]),
            'peak_lat': float(lat_grid[tuple(peak_ij)]),
            'centroid_lon': float(np.nanmean(pts_lon)),
            'centroid_lat': float(np.nanmean(pts_lat)),
            'polygon_lonlat': polygon,
        }
        clusters.append(cluster)
    clusters.sort(key=lambda d: d['peak_ftle'], reverse=True)
    for rank, cl in enumerate(clusters, start=1):
        cl['rank'] = rank

    target_iso = str(np.datetime_as_string(target_time, unit='s')) + 'Z'
    metadata = {
        'velocity_debug': {
            'u_notes': u_notes,
            'v_notes': v_notes,
            'u_shape_normalized': list(u.shape),
            'v_shape_normalized': list(v.shape),
            'native_valid_fraction_min': float(np.nanmin(valid_fraction_native)),
            'native_valid_fraction_max': float(np.nanmax(valid_fraction_native)),
            'native_valid_ocean_cells': int(np.count_nonzero(ocean_mask_native)),
            'output_valid_ocean_cells': valid_count,
            'solver_output_suppressed': suppress_solver_output,
        }
    }

    return FTLEOutputs(
        ftle=ftle,
        ftle_smooth=ftle_smooth,
        ridge_curves_xy=ridge_curves_xy,
        ridge_curves_lonlat=ridge_curves_lonlat,
        ridge_support=ridge_support,
        hotspots=hotspots,
        clusters=clusters,
        lon_grid=lon_grid,
        lat_grid=lat_grid,
        x_grid=x_grid,
        y_grid=y_grid,
        target_time=target_iso,
        u_variable=u_var,
        v_variable=v_var,
        aoi_mask=aoi_mask,
        ocean_mask=ocean_mask,
        metadata=metadata,
    )
