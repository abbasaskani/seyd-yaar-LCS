from __future__ import annotations

import numpy as np

from .ftle import FTLEOutputs, robust_normalize


def centered_persistence(normalized_fields: list[np.ndarray], index: int, half_window: int) -> np.ndarray:
    start = max(0, index - half_window)
    end = min(len(normalized_fields), index + half_window + 1)
    stack = np.stack(normalized_fields[start:end], axis=0)
    with np.errstate(invalid="ignore"):
        return np.nanmean(stack, axis=0)


def attach_persistence_and_scores(outputs: list[FTLEOutputs], config_raw: dict) -> list[FTLEOutputs]:
    q_low, q_high = config_raw["persistence"].get("robust_quantiles", [5, 95])
    ftle_norms = [robust_normalize(out.ftle_smooth, q_low=q_low, q_high=q_high) for out in outputs]
    balanced_w = config_raw["composites"]["balanced"]
    physics_w = config_raw["composites"]["physics_first"]
    for i, out in enumerate(outputs):
        p3 = centered_persistence(ftle_norms, i, half_window=1)
        p5 = centered_persistence(ftle_norms, i, half_window=2)
        out.persistence_3d = p3
        out.persistence_5d = p5
        ftle_norm = ftle_norms[i]
        ridge = np.clip(out.ridge_support, 0.0, 1.0)
        default_p = p5
        out.balanced_composite = np.clip(
            balanced_w["ftle"] * ftle_norm + balanced_w["ridge_support"] * ridge + balanced_w["persistence"] * default_p,
            0.0,
            1.0,
        )
        out.physics_first_composite = np.clip(
            physics_w["ftle"] * ftle_norm + physics_w["ridge_support"] * ridge + physics_w["persistence"] * default_p,
            0.0,
            1.0,
        )
    return outputs
