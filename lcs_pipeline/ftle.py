from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.ndimage import gaussian_filter, maximum_filter, label
from scipy.spatial import ConvexHull

from .coords import local_xy_from_lonlat, lonlat_from_local_xy


@dataclass
class FTLEOutputs:
    ftle: np.ndarray
    ftle_smooth: np.ndarray
    ridge_curves_xy: list[np.ndarray]
    ridge_curves_lonlat: list[np.ndarray]
    hotspots: list[dict[str, Any]]
    clusters: list[dict[str, Any]]
    lon_grid: np.ndarray
    lat_grid: np.ndarray
    x_grid: np.ndarray
    y_grid: np.ndarray
    target_time: str
    u_variable: str
    v_variable: str


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
            if (i - prev["i"]) ** 2 + (j - prev["j"]) ** 2 < min_sep_px ** 2:
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


def compute_attracting_ftle(ds, u_var: str, v_var: str, config_raw: dict[str, Any]) -> FTLEOutputs:
    from math import copysign
    from numbacs.flows import get_interp_arrays_2D, get_flow_2D
    from numbacs.integration import flowmap_grid_2D
    from numbacs.diagnostics import C_eig_2D, ftle_from_eig
    from numbacs.extraction import ftle_ordered_ridges

    lon = ds["longitude"].values.astype(float)
    lat = ds["latitude"].values.astype(float)
    time = ds["time"].values
    target_time = np.datetime64(ds["time"].values[-1])

    lon0 = float(lon.mean())
    lat0 = float(lat.mean())
    x_native, _ = local_xy_from_lonlat(lon, np.full_like(lon, lat0), lon0=lon0, lat0=lat0)
    _, y_native = local_xy_from_lonlat(np.full_like(lat, lon0), lat, lon0=lon0, lat0=lat0)

    t_hours = ((time - target_time) / np.timedelta64(1, "h")).astype(float)
    T = -24.0 * float(config_raw["backward_days"])
    t0 = 0.0
    params = np.array([copysign(1.0, T)], dtype=float)

    u = ds[u_var].values.astype(np.float64)
    v = ds[v_var].values.astype(np.float64)
    scale = 3.6
    u = np.transpose(u, (0, 2, 1)) * scale
    v = np.transpose(v, (0, 2, 1)) * scale

    grid_vel, C_eval_u, C_eval_v = get_interp_arrays_2D(t_hours, x_native, y_native, u, v)
    funcptr = get_flow_2D(grid_vel, C_eval_u, C_eval_v, extrap_mode="linear")

    factor = float(config_raw.get("compute_grid_factor", 3.0))
    x = _upsampled_axis(x_native, factor)
    y = _upsampled_axis(y_native, factor)
    dx = float(x[1] - x[0])
    dy = float(y[1] - y[0])

    integ = config_raw["integrator"]
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

    ridge_curves_lonlat: list[np.ndarray] = []
    for rc in ridge_curves_xy:
        rlon, rlat = lonlat_from_local_xy(rc[:, 0], rc[:, 1], lon0=lon0, lat0=lat0)
        ridge_curves_lonlat.append(np.column_stack([rlon, rlat]))

    hot_cfg = config_raw["hotspots"]
    field = np.array(ftle_smooth, copy=True)
    field[~np.isfinite(field)] = np.nan
    valid = np.isfinite(field)
    threshold = np.nanpercentile(field, float(hot_cfg.get("percentile", 98.5)))
    peak_mask = valid & (field >= threshold)
    localmax = field == maximum_filter(field, size=int(hot_cfg.get("localmax_window", 7)), mode="nearest")
    inds = np.argwhere(peak_mask & localmax)
    candidates = []
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
    cluster_thr = np.nanpercentile(field, float(cl_cfg.get("percentile", 94.0)))
    labels, n_labels = label(valid & (field >= cluster_thr))
    clusters = []
    cell_area_km2 = abs(dx * dy)
    for lab in range(1, n_labels + 1):
        mask = labels == lab
        if not np.any(mask):
            continue
        coords = np.argwhere(mask)
        vals = field[mask]
        peak_idx_local = int(np.nanargmax(vals))
        peak_ij = coords[peak_idx_local]
        pts_lon = lon_grid[mask]
        pts_lat = lat_grid[mask]
        polygon = _component_polygon(pts_lon, pts_lat)
        cluster = {
            "cluster_id": lab,
            "n_cells": int(mask.sum()),
            "area_km2": float(mask.sum() * cell_area_km2),
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
    return FTLEOutputs(
        ftle=ftle,
        ftle_smooth=ftle_smooth,
        ridge_curves_xy=ridge_curves_xy,
        ridge_curves_lonlat=ridge_curves_lonlat,
        hotspots=hotspots,
        clusters=clusters,
        lon_grid=lon_grid,
        lat_grid=lat_grid,
        x_grid=x_grid,
        y_grid=y_grid,
        target_time=target_iso,
        u_variable=u_var,
        v_variable=v_var,
    )
