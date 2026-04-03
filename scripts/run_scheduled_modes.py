from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import json

ROOT = Path(__file__).resolve().parents[1]


def main():
    cfg = json.loads((ROOT / 'config' / 'defaults.json').read_text(encoding='utf-8'))
    modes = cfg.get('scheduled_modes', ['today', 'tomorrow'])
    bbox = cfg['default_bbox']
    backward_days = cfg.get('backward_days', 7)
    for mode in modes:
        cmd = [
            sys.executable, str(ROOT / 'scripts' / 'run_pipeline.py'),
            '--config', str(ROOT / 'config' / 'defaults.json'),
            '--mode', mode,
            '--backward-days', str(backward_days),
            '--lon-min', str(bbox['lon_min']), '--lon-max', str(bbox['lon_max']),
            '--lat-min', str(bbox['lat_min']), '--lat-max', str(bbox['lat_max']),
            '--skip-confirm',
            '--label', mode,
        ]
        print('Running scheduled mode:', mode)
        subprocess.run(cmd, check=True)


if __name__ == '__main__':
    main()
