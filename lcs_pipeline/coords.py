from __future__ import annotations

from math import cos, pi
from pathlib import Path
import json
import numpy as np

EARTH_RADIUS_KM = 6371.0088


def bbox_from_geojson(path: str | Path) -> dict[str, float]:
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    coords = obj["features"][0]["geometry"]["coordinates"][0]
    xs = [float(c[0]) for c in coords]
    ys = [float(c[1]) for c in coords]
    return {"lon_min": min(xs), "lon_max": max(xs), "lat_min": min(ys), "lat_max": max(ys)}


def geojson_from_bbox(bbox: dict[str, float], name: str = "bbox") -> dict:
    lon_min = float(bbox["lon_min"])
    lon_max = float(bbox["lon_max"])
    lat_min = float(bbox["lat_min"])
    lat_max = float(bbox["lat_max"])
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": name},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [lon_min, lat_min],
                        [lon_max, lat_min],
                        [lon_max, lat_max],
                        [lon_min, lat_max],
                        [lon_min, lat_min],
                    ]],
                },
            }
        ],
    }


def local_xy_from_lonlat(lon, lat, lon0: float, lat0: float):
    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    x = (lon - lon0) * (pi / 180.0) * EARTH_RADIUS_KM * cos(lat0 * pi / 180.0)
    y = (lat - lat0) * (pi / 180.0) * EARTH_RADIUS_KM
    return x, y


def lonlat_from_local_xy(x, y, lon0: float, lat0: float):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    lon = lon0 + (x / (EARTH_RADIUS_KM * cos(lat0 * pi / 180.0))) * (180.0 / pi)
    lat = lat0 + (y / EARTH_RADIUS_KM) * (180.0 / pi)
    return lon, lat
