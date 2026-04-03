from __future__ import annotations

from pathlib import Path
import json
from html import escape

ROOT = Path(__file__).resolve().parents[1]


def load_summary(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def rel(path: str | None):
    return path or ''


def section(title: str, summary: dict | None) -> str:
    if not summary:
        return f'<section><h2>{escape(title)}</h2><p>No run published yet.</p></section>'
    proc = summary.get('processed', {})
    est = summary.get('estimate', {})
    hotspots = summary.get('hotspots', [])
    hotspot_rows = ''.join(f"<tr><td>{h.get('rank')}</td><td>{h.get('lon')}</td><td>{h.get('lat')}</td><td>{h.get('ftle')}</td></tr>" for h in hotspots)
    downloads = []
    for label, p in [
        ('FTLE PNG', proc.get('ftle_map_png')),
        ('MP4', proc.get('surface_currents_mp4')),
        ('FTLE NetCDF', proc.get('ftle_field_netcdf')),
        ('Hotspots CSV', proc.get('hotspots_csv')),
        ('Hotspots GeoJSON', proc.get('hotspots_geojson')),
        ('Clusters GeoJSON', proc.get('clusters_geojson')),
        ('Ridges GeoJSON', proc.get('ridges_geojson')),
        ('Raw subset NetCDF', summary.get('raw', {}).get('subset_netcdf')),
    ]:
        if p:
            downloads.append(f'<li><a href="../../{escape(p)}">{escape(label)}</a></li>')
    return f'''
<section>
  <h2>{escape(title)}</h2>
  <p><strong>Target time:</strong> {escape(summary.get('target_time',''))}</p>
  <p><strong>BBox:</strong> {escape(json.dumps(summary.get('bbox', {})))} | <strong>Backward days:</strong> {escape(str(summary.get('backward_days','')))}</p>
  <p><strong>Estimated subset file:</strong> {escape(est.get('estimated_final_subset_file',{}).get('human','unknown'))} | <strong>Estimated transfer:</strong> {escape(est.get('estimated_total_data_transfer',{}).get('human','unknown'))}</p>
  <div class="media-grid">
    <div><img src="../../{escape(rel(proc.get('ftle_map_png')))}" alt="FTLE map"></div>
    <div><video controls preload="metadata" src="../../{escape(rel(proc.get('surface_currents_mp4')))}"></video></div>
  </div>
  <h3>Top 5 hotspots</h3>
  <table><thead><tr><th>Rank</th><th>Lon</th><th>Lat</th><th>FTLE</th></tr></thead><tbody>{hotspot_rows}</tbody></table>
  <h3>Downloads</h3>
  <ul>{''.join(downloads)}</ul>
</section>
'''


def main():
    docs = ROOT / 'docs' / 'latest'
    docs.mkdir(parents=True, exist_ok=True)
    (docs / '.nojekyll').write_text('', encoding='utf-8')
    today = load_summary(ROOT / 'outputs' / 'latest' / 'today' / 'summary.json')
    tomorrow = load_summary(ROOT / 'outputs' / 'latest' / 'tomorrow' / 'summary.json')
    custom = load_summary(ROOT / 'outputs' / 'latest' / 'custom' / 'summary.json')
    html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>seyd-yaar-LCS latest outputs</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif;max-width:1200px;margin:0 auto;padding:24px;line-height:1.45}}
.media-grid{{display:grid;grid-template-columns:1fr;gap:16px}}
@media(min-width:900px){{.media-grid{{grid-template-columns:1fr 1fr;}}}}
img,video{{width:100%;height:auto;border:1px solid #ccc;border-radius:8px;background:#000}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:8px;text-align:left}}th{{background:#f4f4f4}}
code{{background:#f4f4f4;padding:2px 4px;border-radius:4px}}
</style></head><body>
<h1>seyd-yaar-LCS</h1>
<p>Single-page latest outputs for <strong>today</strong>, <strong>tomorrow</strong>, and latest <strong>custom</strong> run.</p>
{section('Today', today)}
{section('Tomorrow', tomorrow)}
{section('Custom (latest)', custom)}
</body></html>'''
    (docs / 'index.html').write_text(html, encoding='utf-8')
    print(f'Built page at {docs / "index.html"}')


if __name__ == '__main__':
    main()
