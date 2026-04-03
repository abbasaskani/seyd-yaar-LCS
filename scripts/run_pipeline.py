from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lcs_pipeline.config import load_config
from lcs_pipeline.copernicus_io import (
    candidate_velocity_vars,
    describe_dataset,
    download_subset,
    estimate_subset,
    resolve_requested_variables,
    normalize_velocity_dataset,
    open_subset,
    resolve_target_time,
    subset_meta_payload,
    reuse_subset_if_match,
    make_json_safe,
    human_size_mb,
)
from lcs_pipeline.ftle import compute_attracting_ftle
from lcs_pipeline.outputs import (
    plot_ftle_map,
    save_clusters_geojson,
    save_ftle_netcdf,
    save_hotspots_csv,
    save_hotspots_geojson,
    save_ridges_geojson,
    save_summary_json,
)
from lcs_pipeline.video import make_surface_currents_mp4
from lcs_pipeline.coords import geojson_from_bbox


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default='config/defaults.json')
    ap.add_argument('--mode', choices=['today', 'tomorrow', 'custom'])
    ap.add_argument('--custom-date')
    ap.add_argument('--backward-days', type=float)
    ap.add_argument('--lon-min', type=float)
    ap.add_argument('--lon-max', type=float)
    ap.add_argument('--lat-min', type=float)
    ap.add_argument('--lat-max', type=float)
    ap.add_argument('--skip-confirm', action='store_true')
    ap.add_argument('--label', help='Output label override (today/tomorrow/custom)')
    return ap.parse_args()


def build_run_config(cfg_raw: dict, args: argparse.Namespace) -> tuple[dict, dict]:
    bbox = dict(cfg_raw['default_bbox'])
    for key_cli, key in [('lon_min','lon_min'),('lon_max','lon_max'),('lat_min','lat_min'),('lat_max','lat_max')]:
        val = getattr(args, key_cli)
        if val is not None:
            bbox[key] = val
    run_cfg = dict(cfg_raw)
    run_cfg['date_mode'] = args.mode or 'today'
    if args.custom_date:
        run_cfg['custom_date'] = args.custom_date
    if args.backward_days is not None:
        run_cfg['backward_days'] = args.backward_days
    return run_cfg, bbox


def ensure_paths(base: Path, label: str):
    latest = base / 'outputs' / 'latest' / label
    raw_dir = latest / 'raw'
    processed = latest / 'processed'
    report = latest / 'report'
    for p in [raw_dir, processed, report]:
        p.mkdir(parents=True, exist_ok=True)
    return latest, raw_dir, processed, report


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    run_cfg, bbox = build_run_config(cfg.raw, args)
    ds_meta = describe_dataset(cfg.raw['dataset_id'])
    start_dt, target_dt, mode = resolve_target_time(run_cfg, ds_meta)
    label = args.label or mode

    latest_dir, raw_dir, processed_dir, report_dir = ensure_paths(cfg.base_dir, label)
    subset_path = raw_dir / 'currents_subset.nc'
    subset_meta_path = raw_dir / 'subset_meta.json'

    request_variables = resolve_requested_variables(ds_meta, cfg.raw['u_variable_candidates'], cfg.raw['v_variable_candidates'])

    estimate = estimate_subset(
        dataset_id=cfg.raw['dataset_id'],
        variables=request_variables,
        lon_min=bbox['lon_min'], lon_max=bbox['lon_max'], lat_min=bbox['lat_min'], lat_max=bbox['lat_max'],
        start_dt=start_dt, end_dt=target_dt,
        coordinates_selection_method=cfg.raw.get('coordinates_selection_method', 'nearest'),
    )

    pre = {
        'dataset_id': cfg.raw['dataset_id'],
        'dataset_name': ds_meta.get('dataset_name'),
        'dataset_time_coverage': {'time_min': str(ds_meta.get('time_min')), 'time_max': str(ds_meta.get('time_max'))},
        'run_label': label,
        'bbox': bbox,
        'target_time_utc': target_dt.isoformat(),
        'window_start_utc': start_dt.isoformat(),
        'window_end_utc': target_dt.isoformat(),
        'estimated_final_subset_file': {'mb': estimate.get('file_size'), 'human': human_size_mb(estimate.get('file_size'))},
        'estimated_total_data_transfer': {'mb': estimate.get('data_transfer_size'), 'human': human_size_mb(estimate.get('data_transfer_size'))},
        'variables': estimate.get('variables'),
        'coordinates_extent': estimate.get('coordinates_extent'),
        'status': estimate.get('status'),
        'message': estimate.get('message'),
        'file_path': estimate.get('file_path'),
        'filename': estimate.get('filename'),
    }
    pre = make_json_safe(pre)
    (report_dir / 'pre_download_report.json').write_text(json.dumps(pre, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(pre, indent=2, ensure_ascii=False))
    if not args.skip_confirm and sys.stdin.isatty():
        ans = input('Continue with download and analysis? (y/N): ').strip().lower()
        if ans not in {'y','yes'}:
            print('Stopped by user.')
            return

    desired_meta = subset_meta_payload(cfg.raw['dataset_id'], bbox, start_dt, target_dt, label, estimate, str(subset_path))
    reused = reuse_subset_if_match(subset_meta_path, subset_path, desired_meta)
    if reused:
        print(f'Reusing raw subset: {subset_path}')
    else:
        print('Downloading raw subset from Copernicus...')
        download_subset(
            dataset_id=cfg.raw['dataset_id'],
            variables=request_variables,
            lon_min=bbox['lon_min'], lon_max=bbox['lon_max'], lat_min=bbox['lat_min'], lat_max=bbox['lat_max'],
            start_dt=start_dt, end_dt=target_dt,
            output_path=subset_path,
            coordinates_selection_method=cfg.raw.get('coordinates_selection_method', 'nearest'),
        )
        subset_meta_path.write_text(json.dumps(make_json_safe(desired_meta), indent=2, ensure_ascii=False), encoding='utf-8')

    raw_ds = open_subset(subset_path)
    u_var, v_var = candidate_velocity_vars(raw_ds, cfg.raw['u_variable_candidates'], cfg.raw['v_variable_candidates'])
    ds = normalize_velocity_dataset(raw_ds, u_var=u_var, v_var=v_var)
    out = compute_attracting_ftle(ds=ds, u_var=u_var, v_var=v_var, config_raw=run_cfg)

    save_ftle_netcdf(out, processed_dir / 'ftle_field.nc')
    save_hotspots_csv(out, processed_dir / 'hotspots.csv')
    save_hotspots_geojson(out, processed_dir / 'hotspots.geojson')
    save_clusters_geojson(out, processed_dir / 'clusters.geojson')
    save_ridges_geojson(out, processed_dir / 'ridges.geojson')
    plot_ftle_map(out, processed_dir / 'ftle_map.png', title=f'Attracting LCS proxy (backward FTLE) | {label} | target={out.target_time}')

    media_cfg = cfg.raw.get('media', {})
    mp4_rel = None
    if media_cfg.get('create_mp4', True):
        mp4_path = processed_dir / 'surface_currents.mp4'
        make_surface_currents_mp4(ds, u_var=u_var, v_var=v_var, hotspots=out.hotspots, path=mp4_path, max_frames=int(media_cfg.get('max_frames',72)), quiver_stride=int(media_cfg.get('quiver_stride',3)), fps=int(media_cfg.get('fps',6)))
        mp4_rel = str(mp4_path.relative_to(cfg.base_dir)).replace('\\', '/')

    region_geojson_path = report_dir / 'region_used.geojson'
    region_geojson_path.write_text(json.dumps(geojson_from_bbox(bbox, name=f'{label}_bbox'), indent=2), encoding='utf-8')

    summary = {
        'run_label': label,
        'target_time': out.target_time,
        'bbox': bbox,
        'backward_days': run_cfg['backward_days'],
        'dataset_id': cfg.raw['dataset_id'],
        'u_variable': out.u_variable,
        'v_variable': out.v_variable,
        'hotspots': out.hotspots,
        'clusters_preview': out.clusters[:10],
        'processed': {
            'ftle_map_png': str((processed_dir / 'ftle_map.png').relative_to(cfg.base_dir)).replace('\\', '/'),
            'surface_currents_mp4': mp4_rel,
            'ftle_field_netcdf': str((processed_dir / 'ftle_field.nc').relative_to(cfg.base_dir)).replace('\\', '/'),
            'hotspots_csv': str((processed_dir / 'hotspots.csv').relative_to(cfg.base_dir)).replace('\\', '/'),
            'hotspots_geojson': str((processed_dir / 'hotspots.geojson').relative_to(cfg.base_dir)).replace('\\', '/'),
            'clusters_geojson': str((processed_dir / 'clusters.geojson').relative_to(cfg.base_dir)).replace('\\', '/'),
            'ridges_geojson': str((processed_dir / 'ridges.geojson').relative_to(cfg.base_dir)).replace('\\', '/'),
        },
        'raw': {
            'subset_netcdf': str(subset_path.relative_to(cfg.base_dir)).replace('\\', '/'),
            'subset_meta_json': str(subset_meta_path.relative_to(cfg.base_dir)).replace('\\', '/'),
        },
        'estimate': pre,
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
    }
    save_summary_json(out, report_dir / 'summary.json', extra=summary)
    shutil.copy2(report_dir / 'summary.json', latest_dir / 'summary.json')
    print(f'Run completed. Outputs under: {latest_dir}')


if __name__ == '__main__':
    main()
