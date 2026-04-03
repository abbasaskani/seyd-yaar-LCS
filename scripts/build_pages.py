from __future__ import annotations

from pathlib import Path
import json
import shutil
from html import escape

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / 'outputs' / 'latest'
DOCS = ROOT / 'docs' / 'latest'
RUNS_OUT = DOCS / 'runs'

LABEL_META = {
    'today': {'title': 'Today', 'emoji': '●', 'hint': 'Latest automatic or manual run for today.'},
    'tomorrow': {'title': 'Tomorrow', 'emoji': '◌', 'hint': 'Latest forecast-facing run for tomorrow.'},
    'custom': {'title': 'Custom', 'emoji': '◆', 'hint': 'Latest custom-date run.'},
}


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def to_rel_posix(path: Path) -> str:
    return path.as_posix()


def copy_run_tree(label: str) -> Path | None:
    src = OUTPUTS / label
    if not src.exists():
        return None
    dst = RUNS_OUT / label
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return dst


def asset_exists(rel_path: str | None) -> bool:
    return bool(rel_path) and (DOCS / rel_path).exists()


def mirrored_path(label: str, original_rel: str | None) -> str | None:
    if not original_rel:
        return None
    parts = Path(original_rel).parts
    if len(parts) >= 3 and parts[0] == 'outputs' and parts[1] == 'latest':
        return to_rel_posix(Path('runs').joinpath(*parts[2:]))
    return None


def build_manifest() -> dict:
    cfg = load_json(ROOT / 'config' / 'defaults.json') or {}
    show_custom_archive = int(cfg.get('page_show_custom_archive', 0))
    manifest = {
        'project_name': cfg.get('project_name', 'seyd-yaar-LCS'),
        'show_custom_archive': show_custom_archive,
        'sections': {},
    }
    RUNS_OUT.mkdir(parents=True, exist_ok=True)

    for label, meta in LABEL_META.items():
        copy_run_tree(label)
        summary = load_json(OUTPUTS / label / 'summary.json')
        if not summary:
            manifest['sections'][label] = {
                'label': label,
                'title': meta['title'],
                'emoji': meta['emoji'],
                'hint': meta['hint'],
                'available': False,
            }
            continue

        processed = summary.get('processed', {}) or {}
        raw = summary.get('raw', {}) or {}
        estimate = summary.get('estimate', {}) or {}
        hotspots = summary.get('hotspots', []) or []
        clusters_preview = summary.get('clusters_preview', []) or []

        assets = {
            'ftle_png': mirrored_path(label, processed.get('ftle_map_png')),
            'mp4': mirrored_path(label, processed.get('surface_currents_mp4')),
            'ftle_netcdf': mirrored_path(label, processed.get('ftle_field_netcdf')),
            'hotspots_csv': mirrored_path(label, processed.get('hotspots_csv')),
            'hotspots_geojson': mirrored_path(label, processed.get('hotspots_geojson')),
            'clusters_geojson': mirrored_path(label, processed.get('clusters_geojson')),
            'ridges_geojson': mirrored_path(label, processed.get('ridges_geojson')),
            'raw_subset_netcdf': mirrored_path(label, raw.get('subset_netcdf')),
            'subset_meta_json': mirrored_path(label, raw.get('subset_meta_json')),
            'pre_download_report_json': mirrored_path(label, f'outputs/latest/{label}/report/pre_download_report.json'),
            'region_used_geojson': mirrored_path(label, f'outputs/latest/{label}/report/region_used.geojson'),
            'summary_json': mirrored_path(label, f'outputs/latest/{label}/summary.json'),
        }

        download_items = [
            ('FTLE map (PNG)', assets['ftle_png']),
            ('Surface currents (MP4)', assets['mp4']),
            ('FTLE field (NetCDF)', assets['ftle_netcdf']),
            ('Hotspots (CSV)', assets['hotspots_csv']),
            ('Hotspots (GeoJSON)', assets['hotspots_geojson']),
            ('Clusters (GeoJSON)', assets['clusters_geojson']),
            ('Ridges (GeoJSON)', assets['ridges_geojson']),
            ('Raw subset (NetCDF)', assets['raw_subset_netcdf']),
            ('Subset metadata (JSON)', assets['subset_meta_json']),
            ('Pre-download report (JSON)', assets['pre_download_report_json']),
            ('Region used (GeoJSON)', assets['region_used_geojson']),
            ('Run summary (JSON)', assets['summary_json']),
        ]
        downloads = [
            {'label': dl_label, 'href': href}
            for dl_label, href in download_items
            if asset_exists(href)
        ]

        bbox = summary.get('bbox', {}) or {}
        bbox_text = (
            f"{bbox.get('lon_min', '?')} to {bbox.get('lon_max', '?')} E · "
            f"{bbox.get('lat_min', '?')} to {bbox.get('lat_max', '?')} N"
        )

        manifest['sections'][label] = {
            'label': label,
            'title': meta['title'],
            'emoji': meta['emoji'],
            'hint': meta['hint'],
            'available': True,
            'target_time': summary.get('target_time', ''),
            'timestamp_utc': summary.get('timestamp_utc', ''),
            'dataset_id': summary.get('dataset_id', ''),
            'u_variable': summary.get('u_variable', ''),
            'v_variable': summary.get('v_variable', ''),
            'backward_days': summary.get('backward_days', ''),
            'bbox_text': bbox_text,
            'bbox': bbox,
            'estimate_file': ((estimate.get('estimated_final_subset_file') or {}).get('human') if isinstance(estimate, dict) else ''),
            'estimate_transfer': ((estimate.get('estimated_total_data_transfer') or {}).get('human') if isinstance(estimate, dict) else ''),
            'ftle_png': assets['ftle_png'],
            'mp4': assets['mp4'],
            'downloads': downloads,
            'hotspots': hotspots,
            'clusters_count': len(clusters_preview),
            'hotspots_count': len(hotspots),
        }

    return manifest


def html_page(manifest: dict) -> str:
    title = escape(manifest.get('project_name', 'seyd-yaar-LCS'))
    data_json = json.dumps(manifest, ensure_ascii=False)
    template = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__TITLE__ · LCS dashboard</title>
  <meta name="color-scheme" content="dark">
  <style>
    :root {
      --bg: #07111f;
      --bg2: #0f1f3b;
      --card: rgba(17, 27, 46, 0.62);
      --card-strong: rgba(21, 33, 56, 0.82);
      --stroke: rgba(255,255,255,0.11);
      --text: #e8f1ff;
      --muted: #9fb2cf;
      --accent: #6ee7ff;
      --accent2: #8b5cf6;
      --accent3: #22c55e;
      --shadow: 0 30px 80px rgba(0,0,0,.35);
      --radius-xl: 24px;
      --radius-lg: 18px;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; color: var(--text); }
    body {
      background:
        radial-gradient(circle at top left, rgba(110,231,255,.18), transparent 28%),
        radial-gradient(circle at top right, rgba(139,92,246,.17), transparent 22%),
        radial-gradient(circle at bottom left, rgba(34,197,94,.12), transparent 26%),
        linear-gradient(135deg, var(--bg) 0%, var(--bg2) 100%);
      background-attachment: fixed;
    }
    a { color: inherit; text-decoration: none; }
    .page { width: min(1360px, calc(100vw - 32px)); margin: 0 auto; padding: 28px 0 56px; }
    .hero { position: relative; overflow: hidden; padding: 28px; border-radius: 30px; background: linear-gradient(135deg, rgba(18,32,58,.78), rgba(17,24,39,.55)); border: 1px solid var(--stroke); box-shadow: var(--shadow); backdrop-filter: blur(18px); margin-bottom: 22px; }
    .hero::before { content: ""; position: absolute; inset: -1px; background: linear-gradient(135deg, rgba(110,231,255,.35), rgba(139,92,246,.18), rgba(34,197,94,.18)); z-index: 0; opacity: .25; pointer-events: none; }
    .hero > * { position: relative; z-index: 1; }
    .eyebrow { display: inline-flex; gap: 10px; align-items: center; color: var(--accent); font-size: 13px; letter-spacing: .14em; text-transform: uppercase; font-weight: 700; }
    .title { font-size: clamp(30px, 5vw, 52px); line-height: 1.05; margin: 12px 0 10px; font-weight: 800; letter-spacing: -.03em; }
    .subtitle { margin: 0; max-width: 900px; color: var(--muted); font-size: 15px; line-height: 1.7; }
    .hero-grid { display: grid; grid-template-columns: 1.35fr .9fr; gap: 18px; margin-top: 22px; }
    .glass { background: var(--card); border: 1px solid var(--stroke); border-radius: var(--radius-xl); backdrop-filter: blur(18px); box-shadow: inset 0 1px 0 rgba(255,255,255,.03); }
    .hero-card { padding: 18px 18px 16px; }
    .hero-stats { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 12px; }
    .stat { padding: 14px 16px; border-radius: 18px; background: rgba(255,255,255,.03); border: 1px solid rgba(255,255,255,.06); }
    .stat .k { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; }
    .stat .v { margin-top: 7px; font-size: 18px; font-weight: 700; }
    .toolbar { display: flex; gap: 10px; flex-wrap: wrap; margin: 22px 0; }
    .tab-btn, .download-btn, .pill { position: relative; overflow: hidden; border: 1px solid rgba(255,255,255,.1); background: linear-gradient(135deg, rgba(255,255,255,.08), rgba(255,255,255,.02)); color: var(--text); backdrop-filter: blur(16px); box-shadow: 0 10px 28px rgba(0,0,0,.18), inset 0 1px 0 rgba(255,255,255,.05); }
    .tab-btn { border-radius: 999px; padding: 12px 18px; cursor: pointer; min-width: 135px; display: inline-flex; align-items: center; justify-content: center; gap: 8px; font-weight: 700; }
    .tab-btn.active { background: linear-gradient(135deg, rgba(110,231,255,.25), rgba(139,92,246,.28)); border-color: rgba(110,231,255,.38); }
    .section { display: none; }
    .section.active { display: block; }
    .empty { padding: 26px; text-align: center; color: var(--muted); font-size: 15px; }
    .content-grid { display: grid; grid-template-columns: 1.15fr .85fr; gap: 18px; }
    .card { padding: 18px; border-radius: var(--radius-xl); background: var(--card-strong); border: 1px solid var(--stroke); box-shadow: var(--shadow); backdrop-filter: blur(16px); }
    .card h2, .card h3 { margin: 0 0 12px; letter-spacing: -.02em; }
    .card h2 { font-size: 22px; }
    .card h3 { font-size: 16px; color: var(--muted); font-weight: 700; }
    .media-frame { border-radius: 18px; overflow: hidden; border: 1px solid rgba(255,255,255,.07); background: rgba(4,10,20,.78); }
    .media-frame img, .media-frame video { width: 100%; display: block; background: #020617; }
    .stack { display: grid; gap: 18px; }
    .meta-grid { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 12px; }
    .meta-box { padding: 14px 16px; border-radius: 18px; background: rgba(255,255,255,.03); border: 1px solid rgba(255,255,255,.06); }
    .meta-box .label { color: var(--muted); font-size: 12px; letter-spacing: .08em; text-transform: uppercase; }
    .meta-box .value { margin-top: 8px; font-size: 15px; font-weight: 700; line-height: 1.45; word-break: break-word; }
    .downloads { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 12px; }
    .download-btn { display: flex; justify-content: space-between; align-items: center; gap: 14px; border-radius: 18px; padding: 14px 16px; transition: transform .16s ease, border-color .16s ease; }
    .download-btn:hover { transform: translateY(-2px); border-color: rgba(110,231,255,.4); }
    .download-btn strong { display: block; font-size: 14px; }
    .download-btn span { display: block; color: var(--muted); font-size: 11px; margin-top: 2px; }
    .arrow { color: var(--accent); font-size: 18px; }
    .table-wrap { overflow: auto; border-radius: 18px; border: 1px solid rgba(255,255,255,.08); }
    table { width: 100%; border-collapse: collapse; min-width: 560px; }
    thead th { position: sticky; top: 0; background: rgba(13,24,43,.95); color: var(--muted); text-transform: uppercase; letter-spacing: .08em; font-size: 11px; }
    th, td { padding: 13px 14px; text-align: left; border-bottom: 1px solid rgba(255,255,255,.06); }
    tbody tr:hover { background: rgba(255,255,255,.03); }
    .footer-note { margin-top: 14px; color: var(--muted); font-size: 12px; line-height: 1.7; }
    .toprow { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 14px; flex-wrap: wrap; }
    .mode-badge { padding: 9px 12px; border-radius: 999px; font-weight: 700; font-size: 12px; color: white; background: linear-gradient(135deg, rgba(110,231,255,.28), rgba(139,92,246,.28)); border: 1px solid rgba(110,231,255,.35); }
    .small-muted { color: var(--muted); font-size: 13px; }
    .legend-row { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }
    .pill { border-radius: 999px; padding: 8px 12px; font-size: 12px; font-weight: 700; }
    .hero-links { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 16px; }
    .cta { display: inline-flex; gap: 10px; align-items: center; padding: 12px 16px; border-radius: 16px; background: linear-gradient(135deg, rgba(110,231,255,.18), rgba(139,92,246,.2)); border: 1px solid rgba(110,231,255,.3); font-weight: 700; }
    @media (max-width: 1080px) { .hero-grid, .content-grid { grid-template-columns: 1fr; } }
    @media (max-width: 760px) { .meta-grid, .downloads, .hero-stats { grid-template-columns: 1fr; } .page { width: min(100vw - 20px, 1360px); } .hero, .card { padding: 16px; } }
  </style>
</head>
<body>
  <div class="page">
    <section class="hero glass">
      <div class="eyebrow">LCS · Copernicus · GitHub Pages</div>
      <h1 class="title">Beautiful live dashboard for <span style="background: linear-gradient(135deg, var(--accent), #c084fc); -webkit-background-clip: text; background-clip: text; color: transparent;">__TITLE__</span></h1>
      <p class="subtitle">Latest <strong>today</strong>, <strong>tomorrow</strong>, and <strong>custom</strong> outputs are mirrored into the site itself so previews, videos, maps, and download buttons all work directly on GitHub Pages without depending on repository file views.</p>
      <div class="hero-links">
        <a class="cta" href="#today">Open Today</a>
        <a class="cta" href="#tomorrow">Open Tomorrow</a>
        <a class="cta" href="#custom">Open Custom</a>
      </div>
      <div class="hero-grid">
        <div class="hero-card glass">
          <h3 style="margin:0 0 10px; color:var(--muted);">What this page shows</h3>
          <p class="subtitle" style="max-width:none; margin:0;">FTLE map, MP4 preview, top hotspots, cluster count, time window metadata, download buttons for PNG/MP4/NetCDF/CSV/GeoJSON/JSON, and run details for each mode in one polished interface.</p>
          <div class="legend-row">
            <span class="pill">Dark gradient theme</span>
            <span class="pill">Glassy cards</span>
            <span class="pill">Single-page UI</span>
            <span class="pill">Direct downloads</span>
          </div>
        </div>
        <div class="hero-card glass">
          <h3 style="margin:0 0 12px; color:var(--muted);">Live dashboard stats</h3>
          <div class="hero-stats" id="heroStats"></div>
        </div>
      </div>
    </section>

    <nav class="toolbar" id="tabs"></nav>
    <main id="sections"></main>
  </div>

<script>
const manifest = __DATA_JSON__;
const labels = ['today', 'tomorrow', 'custom'];
function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function iconFor(label) {
  return label === 'today' ? '☀' : label === 'tomorrow' ? '⟶' : '✦';
}
function heroStats() {
  const root = document.getElementById('heroStats');
  const available = labels.filter(label => manifest.sections[label] && manifest.sections[label].available);
  const totalDownloads = available.reduce((acc, label) => acc + (manifest.sections[label].downloads || []).length, 0);
  const totalHotspots = available.reduce((acc, label) => acc + (manifest.sections[label].hotspots_count || 0), 0);
  const cards = [
    ['Available modes', available.length],
    ['Download buttons', totalDownloads],
    ['Visible hotspots', totalHotspots],
    ['Pages mode', 'Glass UI'],
  ];
  root.innerHTML = cards.map(([k,v]) => `<div class="stat"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`).join('');
}
function renderTabs() {
  const tabs = document.getElementById('tabs');
  tabs.innerHTML = labels.map(label => {
    const sec = manifest.sections[label] || {title: label, available: false, emoji:'•', hint:''};
    return `<button class="tab-btn" data-tab="${label}"><span>${iconFor(label)} ${esc(sec.title || label)}</span></button>`;
  }).join('');
  tabs.querySelectorAll('.tab-btn').forEach(btn => btn.addEventListener('click', () => activate(btn.dataset.tab, true)));
}
function downloadsHtml(downloads) {
  if (!downloads || !downloads.length) return `<div class="empty">No downloadable files published for this run yet.</div>`;
  return `<div class="downloads">${downloads.map(d => `<a class="download-btn" href="${esc(d.href)}" target="_blank" rel="noopener"><div><strong>${esc(d.label)}</strong><span>Open or download</span></div><div class="arrow">↗</div></a>`).join('')}</div>`;
}
function hotspotsHtml(hotspots) {
  if (!hotspots || !hotspots.length) return `<div class="empty">No hotspots found for this run.</div>`;
  const rows = hotspots.map(h => `<tr><td>${esc(h.rank)}</td><td>${esc(h.lon)}</td><td>${esc(h.lat)}</td><td>${esc(h.ftle)}</td><td>${esc(h.cluster_rank ?? '-')}</td></tr>`).join('');
  return `<div class="table-wrap"><table><thead><tr><th>Rank</th><th>Lon</th><th>Lat</th><th>FTLE</th><th>Cluster</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
function sectionHtml(label) {
  const sec = manifest.sections[label];
  if (!sec || !sec.available) {
    return `<section class="section" id="section-${label}"><div class="card empty"><h2 style="margin-bottom:8px;">${esc(sec?.title || label)}</h2><p>No published run yet for this mode.</p></div></section>`;
  }
  const imageBlock = sec.ftle_png ? `<div class="card"><div class="toprow"><div><h2>${esc(sec.title)} FTLE map</h2><div class="small-muted">Target time · ${esc(sec.target_time)}</div></div><div class="mode-badge">${iconFor(label)} ${esc(sec.title)}</div></div><div class="media-frame"><img src="${esc(sec.ftle_png)}" alt="${esc(sec.title)} FTLE map"></div></div>` : `<div class="card empty">No FTLE map published.</div>`;
  const videoBlock = sec.mp4 ? `<div class="card"><h2>Surface currents video</h2><div class="small-muted" style="margin-bottom:12px;">MP4 animation mirrored into the site.</div><div class="media-frame"><video controls preload="metadata" src="${esc(sec.mp4)}"></video></div></div>` : `<div class="card empty">No MP4 published for this run.</div>`;
  return `<section class="section" id="section-${label}"><div class="content-grid"><div class="stack">${imageBlock}<div class="card"><h2>Top hotspots</h2><div class="small-muted" style="margin-bottom:12px;">The 5 highest-ranked attracting hotspots detected in the current run.</div>${hotspotsHtml(sec.hotspots)}</div></div><div class="stack">${videoBlock}<div class="card"><h2>Run details</h2><div class="meta-grid"><div class="meta-box"><div class="label">Target time</div><div class="value">${esc(sec.target_time)}</div></div><div class="meta-box"><div class="label">Backward days</div><div class="value">${esc(sec.backward_days)}</div></div><div class="meta-box"><div class="label">BBox</div><div class="value">${esc(sec.bbox_text)}</div></div><div class="meta-box"><div class="label">Dataset</div><div class="value">${esc(sec.dataset_id)}</div></div><div class="meta-box"><div class="label">Velocity variables</div><div class="value">${esc(sec.u_variable)} / ${esc(sec.v_variable)}</div></div><div class="meta-box"><div class="label">Subset estimate</div><div class="value">${esc(sec.estimate_file || '—')} · ${esc(sec.estimate_transfer || '—')}</div></div><div class="meta-box"><div class="label">Hotspots</div><div class="value">${esc(sec.hotspots_count)}</div></div><div class="meta-box"><div class="label">Preview clusters</div><div class="value">${esc(sec.clusters_count)}</div></div></div><div class="footer-note">Run generated at ${esc(sec.timestamp_utc || 'unknown')} UTC. Page content is built from the latest run directory and mirrored into <code>docs/latest</code> so GitHub Pages can serve it directly.</div></div><div class="card"><h2>Downloads</h2><div class="small-muted" style="margin-bottom:12px;">All key outputs exposed as direct buttons.</div>${downloadsHtml(sec.downloads)}</div></div></div></section>`;
}
function renderSections() {
  document.getElementById('sections').innerHTML = labels.map(sectionHtml).join('');
}
function activate(label, pushHash=false) {
  labels.forEach(key => {
    document.getElementById(`section-${key}`)?.classList.toggle('active', key === label);
    document.querySelector(`.tab-btn[data-tab="${key}"]`)?.classList.toggle('active', key === label);
  });
  if (pushHash) history.replaceState(null, '', `#${label}`);
}
heroStats();
renderTabs();
renderSections();
const initial = (location.hash || '#today').replace('#', '');
activate(labels.includes(initial) ? initial : 'today');
</script>
</body>
</html>'''
    return template.replace('__TITLE__', title).replace('__DATA_JSON__', data_json)


def main():
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / '.nojekyll').write_text('', encoding='utf-8')
    manifest = build_manifest()
    (DOCS / 'site-manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    (DOCS / 'index.html').write_text(html_page(manifest), encoding='utf-8')
    print(f'Built page at {DOCS / "index.html"}')


if __name__ == '__main__':
    main()
