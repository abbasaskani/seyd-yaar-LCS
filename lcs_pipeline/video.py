from __future__ import annotations
from pathlib import Path
from typing import Iterable
import imageio.v2 as imageio

def build_sequence_video(image_paths: Iterable[str | Path], out_path: str | Path, fps: int = 2) -> Path:
    out_path = Path(out_path)
    frames = []
    for p in image_paths:
        p = Path(p)
        if p.exists():
            frames.append(imageio.imread(p))
    if not frames:
        raise FileNotFoundError('No image frames available for MP4 sequence video')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with imageio.get_writer(out_path, fps=max(int(fps), 1)) as writer:
        for frame in frames:
            writer.append_data(frame)
    return out_path
