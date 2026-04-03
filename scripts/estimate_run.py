from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lcs_pipeline.config import load_config
from lcs_pipeline.copernicus_io import describe_dataset, estimate_subset, resolve_target_time, resolve_requested_variables


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default='config/defaults.json')
    ap.add_argument('--mode', choices=['today','tomorrow','custom'], default='today')
    ap.add_argument('--custom-date')
    ap.add_argument('--backward-days', type=float)
    ap.add_argument('--lon-min', type=float)
    ap.add_argument('--lon-max', type=float)
    ap.add_argument('--lat-min', type=float)
    ap.add_argument('--lat-max', type=float)
    ap.add_argument('--output', default='outputs/estimate_report.json')
    return ap.parse_args()


def human_size(n):
    if n is None:
        return 'unknown'
    n = float(n)
    for u in ['B','KB','MB','GB','TB']:
        if abs(n) < 1024 or u == 'TB':
            return f'{n:.2f} {u}'
        n /= 1024.0


def json_safe(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if hasattr(value, "model_dump"):
        try:
            return json_safe(value.model_dump())
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        try:
            return {k: json_safe(v) for k, v in vars(value).items() if not k.startswith('_')}
        except Exception:
            pass
    return str(value)

def main():
    args = parse_args()
    cfg = load_config(args.config)
    bbox = dict(cfg.raw['default_bbox'])
    for cli, key in [('lon_min','lon_min'),('lon_max','lon_max'),('lat_min','lat_min'),('lat_max','lat_max')]:
        val = getattr(args, cli)
        if val is not None:
            bbox[key] = val
    run_cfg = dict(cfg.raw)
    run_cfg['date_mode'] = args.mode
    if args.custom_date:
        run_cfg['custom_date'] = args.custom_date
    if args.backward_days is not None:
        run_cfg['backward_days'] = args.backward_days

    ds_meta = describe_dataset(cfg.raw['dataset_id'])
    start_dt, target_dt, mode = resolve_target_time(run_cfg, ds_meta)
    request_variables = resolve_requested_variables(ds_meta, cfg.raw['u_variable_candidates'], cfg.raw['v_variable_candidates'])
    est = estimate_subset(
        dataset_id=cfg.raw['dataset_id'],
        variables=request_variables,
        lon_min=bbox['lon_min'], lon_max=bbox['lon_max'], lat_min=bbox['lat_min'], lat_max=bbox['lat_max'],
        start_dt=start_dt, end_dt=target_dt,
        coordinates_selection_method=cfg.raw.get('coordinates_selection_method', 'nearest'),
    )
    payload = {
        'run_label': mode,
        'dataset_id': cfg.raw['dataset_id'],
        'dataset_name': ds_meta.get('dataset_name'),
        'bbox': bbox,
        'window_start_utc': start_dt.isoformat(),
        'window_end_utc': target_dt.isoformat(),
        'estimated_final_subset_file': {'bytes': est.get('file_size'), 'human': human_size(est.get('file_size'))},
        'estimated_total_data_transfer': {'bytes': est.get('data_transfer_size'), 'human': human_size(est.get('data_transfer_size'))},
        'variables': est.get('variables'),
        'coordinates_extent': est.get('coordinates_extent'),
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload_safe = json_safe(payload)
    out.write_text(json.dumps(payload_safe, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(payload_safe, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
