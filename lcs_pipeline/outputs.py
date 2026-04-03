from __future__ import annotations

from pathlib import Path
import json

import numpy as np
import pandas as pd
import xarray as xr
import matplotlib.pyplot as plt

from .ftle import FTLEOutputs


def save_ftle_netcdf(out: FTLEOutputs, path: str | Path) -> Path:
    path = Path(path)
    ds = xr.Dataset(
        data_vars={
            "ftle": (("x", "y"), out.ftle),
            "ftle_smooth": (("x", "y"), out.ftle_smooth),
            "lon": (("x", "y"), out.lon_grid),
            "lat": (("x", "y"), out.lat_grid),
        },
        coords={
            "x": out.x_grid[:, 0],
            "y": out.y_grid[0, :],
        },
        attrs={
            "target_time": out.target_time,
            "u_variable": out.u_variable,
            "v_variable": out.v_variable,
        },
    )
    ds.to_netcdf(path)
    return path


def save_hotspots_csv(out: FTLEOutputs, path: str | Path) -> Path:
    path = Path(path)
    pd.DataFrame(out.hotspots).to_csv(path, index=False)
    return path


def save_summary_json(out: FTLEOutputs, path: str | Path, extra: dict | None = None) -> Path:
    path = Path(path)
    payload = {
        "target_time": out.target_time,
        "u_variable": out.u_variable,
        "v_variable": out.v_variable,
        "hotspots": out.hotspots,
        "top_clusters": out.clusters[:10],
    }
    if extra:
        payload.update(extra)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_hotspots_geojson(out: FTLEOutputs, path: str | Path) -> Path:
    path = Path(path)
    features = []
    for hs in out.hotspots:
        features.append(
            {
                "type": "Feature",
                "properties": {k: v for k, v in hs.items() if k not in {"lon", "lat"}},
                "geometry": {"type": "Point", "coordinates": [hs["lon"], hs["lat"]]},
            }
        )
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_clusters_geojson(out: FTLEOutputs, path: str | Path) -> Path:
    path = Path(path)
    features = []
    for cl in out.clusters:
        features.append(
            {
                "type": "Feature",
                "properties": {k: v for k, v in cl.items() if k != "polygon_lonlat"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[list(map(float, pt)) for pt in cl["polygon_lonlat"]]],
                },
            }
        )
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_ridges_geojson(out: FTLEOutputs, path: str | Path) -> Path:
    path = Path(path)
    features = []
    for idx, ridge in enumerate(out.ridge_curves_lonlat, start=1):
        features.append(
            {
                "type": "Feature",
                "properties": {"ridge_id": idx, "n_points": int(len(ridge))},
                "geometry": {"type": "LineString", "coordinates": ridge.tolist()},
            }
        )
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def plot_ftle_map(out: FTLEOutputs, path: str | Path, title: str) -> Path:
    path = Path(path)
    fig, ax = plt.subplots(figsize=(9, 7), dpi=220)
    cf = ax.contourf(out.lon_grid, out.lat_grid, out.ftle_smooth, levels=80)
    plt.colorbar(cf, ax=ax, label="Backward FTLE")

    for ridge in out.ridge_curves_lonlat:
        ax.plot(ridge[:, 0], ridge[:, 1], color="black", lw=1.1, alpha=0.9)

    for cl in out.clusters[:10]:
        poly = np.array(cl["polygon_lonlat"], dtype=float)
        ax.plot(poly[:, 0], poly[:, 1], linestyle="--", lw=1.0, alpha=0.8)
        ax.text(cl["centroid_lon"], cl["centroid_lat"], f"C{cl['rank']}", fontsize=8)

    for hs in out.hotspots:
        ax.scatter(hs["lon"], hs["lat"], s=36, marker="x")
        ax.text(hs["lon"], hs["lat"], f" H{hs['rank']}", fontsize=9)

    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(title)
    ax.set_aspect("equal", adjustable="box")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path
