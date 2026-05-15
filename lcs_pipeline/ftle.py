from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from typing import Any

import numpy as np
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
    metadata: dict[str, Any] | None = None
    persistence_3d: np.ndarray | None = None
    persistence_5d: np.ndarray | None = None
    balanced_composite: np.ndarray | None = None
    physics_first_composite: np.ndarray | None = None
    accumulation_potential_balanced: np.ndarray | None = None
    accumulation_potential_physics_first: np.ndarray | None = None


@contextlib.contextmanager
def _suppress_fd_output(enabled: bool = True):
    """Suppress noisy native/Fortran stdout+stderr while keeping Python exceptions.

    numbacs/DOP853 may print one warning per bad start point. We validate/fill
    velocity fields before integration, but this guard prevents accidental log
    explosions in GitHub Actions if the native solver still prints diagnostics.
    """
    if not enabled:
        yield
        return

    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    saved_out = os.dup(1)
    saved_err = os.dup(2)
    try:
        os.dup2(devnull_fd, 1)
        os.dup2(devnull_fd, 2)
        yield
    finally:
        os.dup2(saved_out, 1)
        os.dup2(saved_err, 2)
        os.close(saved_out)
        os.close(saved_err)
        os.close(devnull_fd)


def _upsampled_axis(arr: np.ndarray, factor: float) -> np.ndarray:
    n_native = len(arr)
    n_out = max(n_native, int(round((n_native - 1) * factor)) + 1)
    return np.linspace(float(arr[0]), float(arr[-1]), n_out)


def _pick_well_separated_points(candidates: list[dict[str, Any]], min_sep_px: int, top_n: int) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    for cand in candidates:
        i, j = cand["i"], cand["j"]
        ok = True
        for prev in chosen:
            if (i - prev["i"]) ** 2 + (j - prev["j"]) ** 2 < min_sep_px**2:
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


def _finite_percentile(field: np.ndarray, percentile: float, default: float | None = None) -> float:
    vals = np.asarray(field, dtype=float)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        if default is None:
            raise ValueError("Cannot compute percentile because the field has no finite values.")
        return float(default)
    return float(np.percentile(vals, percentile))


def robust_normalize(field: np.ndarray, q_low: float = 5.0, q_high: float = 95.0) -> np.ndarray:
    arr = np.array(field, dtype=float, copy=True)
    finite = np.isfinite(arr)
    out = np.zeros_like(arr, dtype=float)
    out[~finite] = np.nan
    if not np.any(finite):
        return out

    vals = arr[finite]
    lo = float(np.percentile(vals, q_low))
    hi = float(np.percentile(vals, q_high))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        out[finite] = 0.0
        return out

    out[finite] = np.clip((arr[finite] - lo) / (hi - lo), 0.0, 1.0)
    return out


def compute_ridge_support(lon_grid: np.ndarray, lat_grid: np.ndarray, ridge_curves_lonlat: list[np.ndarray], ftle_smooth: np.ndarray, d0_deg: float = 0.15) -> np.ndarray:
    """Build a multi-ridge structural support layer.

    Invalid ridges are skipped. A ridge with only NaN/masked FTLE samples should
    not receive an arbitrary default strength, because that biases the derived
    Accumulation Potential.
    """
    if not ridge_curves_lonlat:
        return np.zeros_like(ftle_smooth, dtype=float)

    support_terms: list[np.ndarray] = []
    ftle_norm = robust_normalize(ftle_smooth)
    lon_axis = lon_grid[:, 0]
    lat_axis = lat_grid[0, :]

    for ridge in ridge_curves_lonlat:
        ridge = np.asarray(ridge, dtype=float)
        if ridge.ndim != 2 or ridge.shape[1] < 2 or ridge.shape[0] == 0:
            continue

        finite_ridge = np.isfinite(ridge[:, 0]) & np.isfinite(ridge[:, 1])
        ridge = ridge[finite_ridge]
        if ridge.shape[0] == 0:
            continue

        d2 = (lon_grid[..., None] - ridge[:, 0]) ** 2 + (lat_grid[..., None] - ridge[:, 1]) ** 2
        d = np.sqrt(np.nanmin(d2, axis=-1))

        ix = np.abs(lon_axis[:, None] - ridge[:, 0][None, :]).argmin(axis=0)
        iy = np.abs(lat_axis[None, :] - ridge[:, 1][:, None]).argmin(axis=1)

        strengths = np.asarray([ftle_norm[a, b] for a, b in zip(ix, iy)], dtype=float)
        strengths = strengths[np.isfinite(strengths)]
        if strengths.size == 0:
            continue

        ridge_strength = float(np.mean(strengths))
        if not np.isfinite(ridge_strength) or ridge_strength <= 0.0:
            continue

        term = np.clip(ridge_strength, 0.0, 1.0) * np.exp(-d / max(d0_deg, 1e-6))
        term = np.clip(term, 0.0, 1.0)
        term[~np.isfinite(term)] = 0.0
        support_terms.append(term)

    if not support_terms:
        return np.zeros_like(ftle_smooth, dtype=float)

    prod = np.ones_like(ftle_smooth, dtype=float)
    for term in support_terms:
        prod *= 1.0 - term

    support = np.clip(1.0 - prod, 0.0, 1.0)
    support[~np.isfinite(support)] = 0.0
    return support


def _find_dim(da, candidates: tuple[str, ...]) -> str | None:
    dims_lower = {d.lower(): d for d in da.dims}
    for cand in candidates:
        if cand.lower() in dims_lower:
            return dims_lower[cand.lower()]
    for dim in da.dims:
        low = dim.lower()
        if any(cand.lower() in low for cand in candidates):
            return dim
    return None


def _prepare_velocity_component(ds, var_name: str, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Return velocity component as (time, lon, lat), regardless of source dim order.

    This is the critical fix for the previous:
        ValueError: axes don't match array
    caused by blindly transposing every dataset as if it were always
    (time, lat, lon). Copernicus subsets can include depth/extra singleton dims
    or a different dimension order.
    """
    da = ds[var_name]

    time_dim = _find_dim(da, ("time",))
    lon_dim = _find_dim(da, ("longitude", "lon"))
    lat_dim = _find_dim(da, ("latitude", "lat"))

    if lon_dim is None or lat_dim is None:
        raise ValueError(f"Velocity variable {var_name!r} must have lon/lat dimensions; dims={da.dims!r}")

    # If time is absent, allow only a single-time dataset and add time explicitly.
    if time_dim is None:
        if "time" not in ds.coords or len(ds["time"]) != 1:
            raise ValueError(f"Velocity variable {var_name!r} has no time dimension and dataset time is not singleton; dims={da.dims!r}")
        da = da.expand_dims(time=ds["time"].values)
        time_dim = "time"

    # Select surface / first slice for any extra dimensions. This is deliberate:
    # this product may carry depth-like dimensions, while the LCS branch is a
    # surface-current pipeline.
    for dim in list(da.dims):
        if dim not in {time_dim, lon_dim, lat_dim}:
            da = da.isel({dim: 0})

    # Re-identify dimensions after possible slicing.
    time_dim = _find_dim(da, ("time",)) or time_dim
    lon_dim = _find_dim(da, ("longitude", "lon")) or lon_dim
    lat_dim = _find_dim(da, ("latitude", "lat")) or lat_dim

    da = da.transpose(time_dim, lon_dim, lat_dim)
    arr = np.asarray(da.values, dtype=np.float64)

    if arr.ndim != 3:
        raise ValueError(f"Velocity variable {var_name!r} did not normalize to 3D (time, lon, lat); shape={arr.shape}, dims={da.dims!r}")
    if arr.shape[1] != len(lon) or arr.shape[2] != len(lat):
        raise ValueError(
            f"Velocity variable {var_name!r} shape does not match coordinate axes after normalization: "
            f"shape={arr.shape}, lon={len(lon)}, lat={len(lat)}, dims={da.dims!r}"
        )

    return arr


def _fill_invalid_nearest_3d(arr: np.ndarray, name: str) -> tuple[np.ndarray, np.ndarray]:
    """Fill invalid velocity cells per time slice using nearest finite ocean cell.

    Returns (filled_array, valid_fraction_mask_native), where valid_fraction is
    computed before filling. This prevents DOP853 from seeing NaN/Inf values
    while still allowing final FTLE products to be masked back to valid ocean.
    """
    arr = np.asarray(arr, dtype=np.float64)
    finite = np.isfinite(arr)
    valid_fraction = np.mean(finite, axis=0)
    out = arr.copy()

    for t in range(out.shape[0]):
        frame = out[t]
        valid = np.isfinite(frame)
        if not np.any(valid):
            raise ValueError(f"Velocity component {name!r} time index {t} has no finite ocean cells.")
        if np.all(valid):
            continue
        nearest_idx = distance_transform_edt(~valid, return_distances=False, return_indices=True)
        nearest_values = frame[tuple(nearest_idx)]
        frame[~valid] = nearest_values[~valid]
        out[t] = frame

    return out, valid_fraction


def _mask_to_output_grid(native_mask: np.ndarray, x_native: np.ndarray, y_native: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    ix = np.abs(x_native[:, None] - x[None, :]).argmin(axis=0)
    iy = np.abs(y_native[:, None] - y[None, :]).argmin(axis=0)
    return native_mask[ix[:, None], iy[None, :]]


def compute_attracting_ftle(ds, u_var: str, v_var: str, config_raw: dict[str, Any], aoi_info: AOIInfo | None = None) -> FTLEOutputs:
    from math import copysign

    from numbacs.diagnostics import C_eig_2D, ftle_from_eig
    from numbacs.extraction import ftle_ordered_ridges
    from numbacs.flows import get_flow_2D, get_interp_arrays_2D
    from numbacs.integration import flowmap_grid_2D

    # Keep coordinate axes monotonic and aligned with variables.
    if "longitude" not in ds.coords or "latitude" not in ds.coords or "time" not in ds.coords:
        raise KeyError("Dataset must contain longitude, latitude and time coordinates before FTLE computation.")

    if len(ds["longitude"]) < 2 or len(ds["latitude"]) < 2 or len(ds["time"]) < 2:
        raise ValueError(
            f"FTLE requires at least 2 longitude, 2 latitude and 2 time samples; "
            f"got lon={len(ds['longitude'])}, lat={len(ds['latitude'])}, time={len(ds['time'])}."
        )

    ds = ds.sortby("longitude")
    ds = ds.sortby("latitude")
    ds = ds.sortby("time")

    lon = ds["longitude"].values.astype(float)
    lat = ds["latitude"].values.astype(float)
    time = ds["time"].values
    target_time = np.datetime64(ds["time"].values[-1])
    lon0 = float(lon.mean())
    lat0 = float(lat.mean())

    x_native, _ = local_xy_from_lonlat(lon, np.full_like(lon, lat0), lon0=lon0, lat0=lat0)
    _, y_native = local_xy_from_lonlat(np.full_like(lat, lon0), lat, lon0=lon0, lat0=lat0)
    t_hours = ((time - target_time) / np.timedelta64(1, "h")).astype(float)

    if not np.all(np.diff(t_hours) > 0):
        raise ValueError(f"Time axis must be strictly increasing after sorting; t_hours={t_hours!r}")

    T = -24.0 * float(config_raw["backward_days"])
    t0 = 0.0
    params = np.array([copysign(1.0, T)], dtype=float)

    scale = float(config_raw.get("velocity_scale_to_km_per_hour", 3.6))
    u_raw = _prepare_velocity_component(ds, u_var, lon, lat)
    v_raw = _prepare_velocity_component(ds, v_var, lon, lat)

    if u_raw.shape != v_raw.shape:
        raise ValueError(f"u/v velocity arrays have different shapes after normalization: {u_raw.shape} vs {v_raw.shape}")

    u_filled, u_valid_fraction = _fill_invalid_nearest_3d(u_raw, u_var)
    v_filled, v_valid_fraction = _fill_invalid_nearest_3d(v_raw, v_var)

    pre_cfg = config_raw.get("preprocessing", {})
    min_valid_fraction = float(pre_cfg.get("min_valid_time_fraction", 0.50))
    min_valid_ocean_cells = int(pre_cfg.get("min_valid_ocean_cells", 20))

    native_ocean_mask = (u_valid_fraction >= min_valid_fraction) & (v_valid_fraction >= min_valid_fraction)
    if int(np.sum(native_ocean_mask)) < min_valid_ocean_cells:
        raise ValueError(
            "AOI/subset has too few valid ocean velocity cells for FTLE after land/island masking: "
            f"valid_cells={int(np.sum(native_ocean_mask))}, required={min_valid_ocean_cells}, "
            f"u_shape={u_raw.shape}, v_shape={v_raw.shape}."
        )

    u = u_filled * scale
    v = v_filled * scale

    grid_vel, C_eval_u, C_eval_v = get_interp_arrays_2D(t_hours, x_native, y_native, u, v)
    funcptr = get_flow_2D(grid_vel, C_eval_u, C_eval_v, extrap_mode="linear")

    factor = float(config_raw.get("compute_grid_factor", 3.0))
    x = _upsampled_axis(x_native, factor)
    y = _upsampled_axis(y_native, factor)
    dx = float(x[1] - x[0])
    dy = float(y[1] - y[0])

    integ = config_raw["integrator"]
    suppress_solver_output = bool(pre_cfg.get("suppress_solver_output", True))

    with _suppress_fd_output(suppress_solver_output):
        flowmap = flowmap_grid_2D(
            funcptr,
            t0,
            T,
            x,
            y,
            params,
            method=integ.get("method", "dop853"),
            rtol=float(integ.get("rtol", 1e-6)),
            atol=float(integ.get("atol", 1e-8)),
        )

    eigvals, eigvecs = C_eig_2D(flowmap, dx, dy)
    eigval_max = eigvals[:, :, 1]
    eigvec_max = eigvecs[:, :, :, 1]
    ftle = ftle_from_eig(eigval_max, T)

    ridge_cfg = config_raw["ridge_extraction"]
    sigma = float(ridge_cfg.get("smooth_sigma", 1.0))
    ftle_smooth = gaussian_filter(ftle, sigma=sigma, mode="nearest")
    dist_tol = float(ridge_cfg.get("dist_tol_grid_cells", 3.0)) * max(dx, dy)

    ridge_curves_xy = ftle_ordered_ridges(
        ftle_smooth,
        eigvec_max,
        x,
        y,
        dist_tol,
        percentile=float(ridge_cfg.get("percentile", 70)),
        sdd_thresh=float(ridge_cfg.get("sdd_thresh", 0.0)),
    )
    ridge_curves_xy = list(ridge_curves_xy) if ridge_curves_xy is not None else []

    lon_grid_1d, _ = lonlat_from_local_xy(x, np.zeros_like(x), lon0=lon0, lat0=lat0)
    _, lat_grid_1d = lonlat_from_local_xy(np.zeros_like(y), y, lon0=lon0, lat0=lat0)
    lon_grid, lat_grid = np.meshgrid(lon_grid_1d, lat_grid_1d, indexing="ij")
    x_grid, y_grid = np.meshgrid(x, y, indexing="ij")

    ocean_mask = _mask_to_output_grid(native_ocean_mask, x_native, y_native, x, y)
    mask = ocean_mask.copy()
    if aoi_info is not None:
        aoi_mask = polygon_mask(lon_grid, lat_grid, aoi_info.polygons)
        mask = mask & aoi_mask

    if int(np.sum(mask)) < min_valid_ocean_cells:
        raise ValueError(
            "AOI contains too few valid ocean cells on the output grid after land/island masking: "
            f"valid_cells={int(np.sum(mask))}, required={min_valid_ocean_cells}."
        )

    ftle = np.where(mask, ftle, np.nan)
    ftle_smooth = np.where(mask, ftle_smooth, np.nan)

    ridge_curves_lonlat: list[np.ndarray] = []
    for rc in ridge_curves_xy:
        if rc is None or len(rc) == 0:
            continue
        rlon, rlat = lonlat_from_local_xy(rc[:, 0], rc[:, 1], lon0=lon0, lat0=lat0)
        ridge_curves_lonlat.append(np.column_stack([rlon, rlat]))

    ridge_support = compute_ridge_support(lon_grid, lat_grid, ridge_curves_lonlat, ftle_smooth)
    ridge_support = np.where(mask, ridge_support, np.nan)

    hot_cfg = config_raw["hotspots"]
    field = np.array(ftle_smooth, copy=True)
    field[~np.isfinite(field)] = np.nan
    valid = np.isfinite(field)

    candidates: list[dict[str, Any]] = []
    hotspots: list[dict[str, Any]] = []
    clusters: list[dict[str, Any]] = []

    if np.any(valid):
        threshold = _finite_percentile(field, float(hot_cfg.get("percentile", 98.5)))
        peak_mask = valid & (field >= threshold)
        localmax = field == maximum_filter(np.where(valid, field, -np.inf), size=int(hot_cfg.get("localmax_window", 7)), mode="nearest")
        inds = np.argwhere(peak_mask & localmax)

        for i, j in inds:
            candidates.append(
                {
                    "i": int(i),
                    "j": int(j),
                    "ftle": float(field[i, j]),
                    "x_km": float(x_grid[i, j]),
                    "y_km": float(y_grid[i, j]),
                    "lon": float(lon_grid[i, j]),
                    "lat": float(lat_grid[i, j]),
                }
            )
        candidates.sort(key=lambda d: d["ftle"], reverse=True)
        hotspots = _pick_well_separated_points(
            candidates,
            min_sep_px=int(hot_cfg.get("min_separation_px", 8)),
            top_n=int(hot_cfg.get("top_n", 5)),
        )
        for rank, hs in enumerate(hotspots, start=1):
            hs["rank"] = rank

        cl_cfg = config_raw["clusters"]
        cluster_thr = _finite_percentile(field, float(cl_cfg.get("percentile", 94.0)))
        labels, n_labels = label(valid & (field >= cluster_thr))
        cell_area_km2 = abs(dx * dy)
        for lab in range(1, n_labels + 1):
            mask_lab = labels == lab
            if not np.any(mask_lab):
                continue
            coords = np.argwhere(mask_lab)
            vals = field[mask_lab]
            finite_vals = vals[np.isfinite(vals)]
            if finite_vals.size == 0:
                continue
            peak_idx_local = int(np.nanargmax(vals))
            peak_ij = coords[peak_idx_local]
            pts_lon = lon_grid[mask_lab]
            pts_lat = lat_grid[mask_lab]
            polygon = _component_polygon(pts_lon, pts_lat)
            cluster = {
                "cluster_id": int(lab),
                "n_cells": int(mask_lab.sum()),
                "area_km2": float(mask_lab.sum() * cell_area_km2),
                "peak_ftle": float(vals[peak_idx_local]),
                "peak_lon": float(lon_grid[tuple(peak_ij)]),
                "peak_lat": float(lat_grid[tuple(peak_ij)]),
                "centroid_lon": float(np.nanmean(pts_lon)),
                "centroid_lat": float(np.nanmean(pts_lat)),
                "polygon_lonlat": polygon,
            }
            clusters.append(cluster)
        clusters.sort(key=lambda d: d["peak_ftle"], reverse=True)
        for rank, cl in enumerate(clusters, start=1):
            cl["rank"] = rank

    target_iso = str(np.datetime_as_string(target_time, unit="s")) + "Z"
    metadata = {
        "velocity_shape_time_lon_lat": list(u_raw.shape),
        "native_valid_ocean_cells": int(np.sum(native_ocean_mask)),
        "output_valid_ocean_cells": int(np.sum(mask)),
        "min_valid_time_fraction": min_valid_fraction,
        "velocity_scale_to_km_per_hour": scale,
        "solver_output_suppressed": suppress_solver_output,
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
        aoi_mask=mask,
        metadata=metadata,
    )
