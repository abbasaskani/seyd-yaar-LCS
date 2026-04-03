from __future__ import annotations

from pathlib import Path
from io import BytesIO

import imageio.v2 as imageio
import matplotlib.pyplot as plt
import numpy as np


def make_surface_currents_mp4(ds, u_var: str, v_var: str, hotspots: list[dict], path: str | Path, max_frames: int = 72, quiver_stride: int = 3, fps: int = 6) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    times = ds["time"].values
    n_total = len(times)
    frame_inds = np.arange(n_total) if n_total <= max_frames else np.linspace(0, n_total - 1, max_frames).astype(int)

    lon = ds["longitude"].values
    lat = ds["latitude"].values
    LON, LAT = np.meshgrid(lon, lat, indexing="xy")

    writer = imageio.get_writer(str(path), fps=fps, codec="libx264", quality=7, macro_block_size=1)
    try:
        for idx in frame_inds:
            u = ds[u_var].isel(time=idx).values
            v = ds[v_var].isel(time=idx).values
            speed = np.sqrt(u ** 2 + v ** 2)
            fig, ax = plt.subplots(figsize=(8.5, 6.5), dpi=160)
            im = ax.pcolormesh(lon, lat, speed, shading="auto")
            plt.colorbar(im, ax=ax, label="|U| (m/s)")
            ax.quiver(LON[::quiver_stride, ::quiver_stride], LAT[::quiver_stride, ::quiver_stride], u[::quiver_stride, ::quiver_stride], v[::quiver_stride, ::quiver_stride], scale=None, width=0.002, alpha=0.9)
            for hs in hotspots:
                ax.scatter(hs["lon"], hs["lat"], s=30, marker="x")
                ax.text(hs["lon"], hs["lat"], f" H{hs['rank']}", fontsize=8)
            ax.set_title(str(np.datetime_as_string(times[idx], unit="m")))
            ax.set_xlabel("Longitude")
            ax.set_ylabel("Latitude")
            ax.set_aspect("equal", adjustable="box")
            fig.tight_layout()
            buf = BytesIO()
            fig.savefig(buf, format="png", bbox_inches="tight")
            plt.close(fig)
            buf.seek(0)
            writer.append_data(imageio.imread(buf))
    finally:
        writer.close()
    return path
