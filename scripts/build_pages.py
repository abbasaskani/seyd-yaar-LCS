from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import xarray as xr

from lcs_pipeline.config import load_config
from lcs_pipeline.ftle import FTLEOutputs
from lcs_pipeline.indices import attach_persistence_and_scores
from lcs_pipeline.outputs import plot_field_map, save_field_layers_json, save_summary_json
from lcs_pipeline.video import build_sequence_video


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config/defaults.json")
    return p.parse_args()


def load_output_from_nc(run_dir: Path) -> FTLEOutputs:
    ds = xr.open_dataset(run_dir / "ftle.nc")
    meta = json.loads((run_dir / "summary.json").read_text(encoding="utf-8")).get("metadata", {}) if (run_dir / "summary.json").exists() else {}
    ridge_geo = json.loads((run_dir / "ridges.geojson").read_text(encoding="utf-8")) if (run_dir / "ridges.geojson").exists() else {"features": []}
    ridges = [np.asarray(f["geometry"]["coordinates"], dtype=float) for f in ridge_geo.get("features", [])]
    hotspots = json.loads((run_dir / "hotspots.geojson").read_text(encoding="utf-8")) if (run_dir / "hotspots.geojson").exists() else {"features": []}
    hot_rows = []
    for feat in hotspots.get("features", []):
        row = dict(feat.get("properties", {}))
        row["lon"], row["lat"] = feat["geometry"]["coordinates"]
        hot_rows.append(row)
    clusters_geo = json.loads((run_dir / "clusters.geojson").read_text(encoding="utf-8")) if (run_dir / "clusters.geojson").exists() else {"features": []}
    cl_rows = []
    for feat in clusters_geo.get("features", []):
        row = dict(feat.get("properties", {}))
        row["polygon_lonlat"] = feat["geometry"]["coordinates"][0]
        cl_rows.append(row)
    out = FTLEOutputs(
        ftle=ds["ftle"].values,
        ftle_smooth=ds["ftle_smooth"].values,
        ridge_support=ds["ridge_support"].values,
        ridge_curves_xy=[],
        ridge_curves_lonlat=ridges,
        hotspots=hot_rows,
        clusters=cl_rows,
        lon_grid=ds["lon"].values,
        lat_grid=ds["lat"].values,
        x_grid=np.meshgrid(ds["x"].values, ds["y"].values, indexing="ij")[0],
        y_grid=np.meshgrid(ds["x"].values, ds["y"].values, indexing="ij")[1],
        target_time=str(ds.attrs.get("target_time", "")),
        u_variable=str(ds.attrs.get("u_variable", "uo")),
        v_variable=str(ds.attrs.get("v_variable", "vo")),
        metadata=meta,
    )
    return out


def render_dashboard(manifest: dict, target: Path) -> None:
    html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Seyd Yar LCS</title>
<style>
:root{{--bg:#09111d;--glass:rgba(255,255,255,.12);--glass2:rgba(255,255,255,.08);--line:rgba(255,255,255,.18);--txt:#eef6ff;--muted:#9ab0c9;--accent:#4ec6ff;--ok:#7fffb7;}}
*{{box-sizing:border-box}}body{{margin:0;font-family:Inter,Segoe UI,Arial,sans-serif;background:radial-gradient(circle at top,#102038 0,#09111d 55%,#050a12 100%);color:var(--txt)}}
.app{{display:grid;grid-template-columns:330px 1fr;min-height:100vh;gap:18px;padding:18px}}
.glass{{backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);background:var(--glass);border:1px solid var(--line);border-radius:24px;box-shadow:0 10px 40px rgba(0,0,0,.25)}}
.sidebar{{padding:18px;display:flex;flex-direction:column;gap:14px}}
.main{{padding:18px;display:grid;grid-template-rows:auto auto 1fr auto;gap:16px}}
.h1{{font-size:26px;font-weight:800}} .muted{{color:var(--muted)}}
.badge{{display:inline-flex;gap:8px;align-items:center;padding:8px 12px;background:var(--glass2);border:1px solid var(--line);border-radius:999px;font-size:12px;margin:4px 6px 0 0}}
.group{{display:flex;flex-wrap:wrap;gap:8px}}
button,select{{background:rgba(255,255,255,.10);color:var(--txt);border:1px solid var(--line);border-radius:14px;padding:10px 12px;cursor:pointer}}
button.active{{outline:2px solid var(--accent)}}
.controls{{display:grid;gap:10px}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
.card{{padding:14px}} .card .k{{font-size:12px;color:var(--muted)}} .card .v{{font-size:22px;font-weight:700}}
.stage{{display:grid;grid-template-columns:1.35fr .65fr;gap:16px;min-height:560px}}
.viewer{{padding:12px;position:relative}} .viewer img{{width:100%;border-radius:16px;border:1px solid var(--line)}}
.videoBox{{padding:12px;display:flex;flex-direction:column;gap:10px}} video{{width:100%;border-radius:16px;border:1px solid var(--line);background:#000}}
.popup{{padding:12px;white-space:pre-wrap;font-family:ui-monospace,Consolas,monospace;font-size:12px;background:rgba(255,255,255,.06);border:1px solid var(--line);border-radius:14px;min-height:168px}}
.downloads a{{display:inline-block;margin:6px 8px 0 0;padding:10px 12px;color:var(--txt);text-decoration:none;border:1px solid var(--line);border-radius:12px;background:var(--glass2)}}
legend{{padding:0}} .small{{font-size:12px}}
@media (max-width:1100px){{.app{{grid-template-columns:1fr}} .cards{{grid-template-columns:repeat(2,1fr)}} .stage{{grid-template-columns:1fr}}}}
</style></head>
<body>
<div class="app">
  <aside class="glass sidebar">
    <div>
      <div class="h1">Seyd Yar LCS</div>
      <div class="muted">Interactive FTLE / composite dashboard with full-raster popup query.</div>
    </div>
    <div id="runButtons" class="group"></div>
    <div class="controls">
      <label class="small muted">Main layer</label>
      <select id="layerSelect">
        <option value="ftle_smooth">FTLE smooth</option>
        <option value="balanced_composite">Balanced composite</option>
        <option value="physics_first_composite">Physics-first composite</option>
        <option value="persistence_3d">Persistence 3d</option>
        <option value="persistence_5d">Persistence 5d</option>
        <option value="ridge_support">Ridge support</option>
      </select>
      <label class="small muted">Overlays</label>
      <div class="group">
        <button id="toggleRidges" class="active">Ridges</button>
        <button id="toggleClusters" class="active">Clusters</button>
        <button id="toggleHotspots" class="active">Hotspots</button>
      </div>
    </div>
    <div id="metaBadges"></div>
    <div class="downloads" id="downloads"></div>
  </aside>
  <main class="glass main">
    <section class="cards">
      <div class="glass card"><div class="k">Timezone preset</div><div class="v" id="cardPreset">—</div></div>
      <div class="glass card"><div class="k">Nominal local target</div><div class="v" id="cardNominal">—</div></div>
      <div class="glass card"><div class="k">Actual selected UTC</div><div class="v" id="cardActual">—</div></div>
      <div class="glass card"><div class="k">Fallback</div><div class="v" id="cardFallback">—</div></div>
    </section>
    <section class="glass card"><div class="small muted">Selection note</div><div id="selectionNote"></div></section>
    <section class="stage">
      <div class="glass viewer">
        <img id="mapImage" src="" alt="map">
        <div class="small muted" style="margin-top:10px">Click anywhere on the map image to query the nearest raster cell.</div>
      </div>
      <div class="videoBox">
        <video id="video" controls></video>
        <div class="popup" id="popupBox">Click the map to inspect FTLE / smooth FTLE / ridge support / persistence / composite values.</div>
      </div>
    </section>
    <section class="glass card small muted">Auto preset selection is based on AOI centroid unless manually overridden. Outputs show preset and UTC offset explicitly.</section>
  </main>
</div>
<script>
const manifest = {json.dumps(manifest, ensure_ascii=False)};
let activeRun = manifest.runs[0] || null;
let activeLayer = 'ftle_smooth';
let overlay = {{ridges:true, clusters:true, hotspots:true}};
let layerImageMap = {{ftle_smooth:'map_ftle.png', balanced_composite:'map_balanced.png', physics_first_composite:'map_physics_first.png', persistence_3d:'map_persistence_3d.png', persistence_5d:'map_persistence_5d.png', ridge_support:'map_ridge_support.png'}};
let fieldData = null;

function qs(id){{return document.getElementById(id)}}
function fmt(s){{return s || '—'}}
function runUrl(run, file){{return 'runs/' + run.name + '/' + file}}

async function loadRun(run){{
  activeRun = run;
  const r = await fetch(runUrl(run, 'field_layers.json')); fieldData = await r.json();
  qs('mapImage').src = runUrl(run, layerImageMap[activeLayer] || 'map_ftle.png') + '?v=' + encodeURIComponent(run.name + activeLayer);
  qs('video').src = manifest.sequence_video || '';
  qs('cardPreset').textContent = fmt(run.summary.metadata.timezone_preset_label);
  qs('cardNominal').textContent = fmt(run.summary.metadata.nominal_local_target);
  qs('cardActual').textContent = fmt(run.summary.metadata.actual_selected_utc);
  qs('cardFallback').textContent = fmt(run.summary.metadata.fallback_status);
  qs('selectionNote').textContent = `${{run.summary.metadata.timezone_preset_label || '—'}} | ${{run.summary.metadata.timezone_name || '—'}} (${{run.summary.metadata.timezone_utc_offset_hint || '—'}}) | auto=${{String(run.summary.metadata.timezone_auto_selected)}} | fallback=${{run.summary.metadata.fallback_status || '—'}}`;
  renderDownloads(run);
  renderBadges(run);
  highlightActiveButton();
}}

function renderBadges(run){{
  const host = qs('metaBadges'); host.innerHTML = '';
  const pairs = [
    ['Preset', run.summary.metadata.timezone_preset_key],
    ['TZ', run.summary.metadata.timezone_name],
    ['UTC', run.summary.metadata.timezone_utc_offset_hint],
    ['Run', run.name],
    ['AOI mode', run.summary.metadata.aoi_mode],
  ];
  pairs.forEach(([k,v])=>{{ const d=document.createElement('div'); d.className='badge'; d.textContent=`${{k}}: ${{fmt(v)}}`; host.appendChild(d); }});
}}

function renderDownloads(run){{
  const host = qs('downloads'); host.innerHTML='';
  ['summary.json','ftle.nc','field_layers.json','hotspots.csv','hotspots.geojson','clusters.geojson','ridges.geojson'].forEach(name=>{{
    const a=document.createElement('a'); a.href=runUrl(run,name); a.textContent=name; a.target='_blank'; host.appendChild(a);
  }});
}}

function renderRunButtons(){{
  const host = qs('runButtons'); host.innerHTML='';
  manifest.runs.forEach(run=>{{
    const b=document.createElement('button'); b.textContent=run.name; b.onclick=()=>loadRun(run); b.dataset.run=run.name; host.appendChild(b);
  }});
}}
function highlightActiveButton(){{ [...qs('runButtons').children].forEach(x=>x.classList.toggle('active', x.dataset.run===activeRun.name)); }}

qs('layerSelect').addEventListener('change', e=>{{ activeLayer=e.target.value; if(activeRun) qs('mapImage').src = runUrl(activeRun, layerImageMap[activeLayer]||'map_ftle.png') + '?v=' + encodeURIComponent(activeRun.name + activeLayer); }});
['toggleRidges','toggleClusters','toggleHotspots'].forEach(id=>qs(id).onclick=()=>qs(id).classList.toggle('active'));

qs('mapImage').addEventListener('click', (ev)=>{{
  if(!fieldData) return;
  const rect = ev.target.getBoundingClientRect();
  const fx = (ev.clientX - rect.left) / rect.width;
  const fy = (ev.clientY - rect.top) / rect.height;
  const i = Math.max(0, Math.min(fieldData.lon_axis.length - 1, Math.round(fx * (fieldData.lon_axis.length - 1))));
  const j = Math.max(0, Math.min(fieldData.lat_axis.length - 1, Math.round((1-fy) * (fieldData.lat_axis.length - 1))));
  const read = (name)=>{{ const arr = fieldData.layers[name]; if(!arr) return null; const v = arr[i][j]; return v === -9999 ? null : v; }};
  const txt = [
    `lon: ${{fieldData.lon_axis[i]}}`,
    `lat: ${{fieldData.lat_axis[j]}}`,
    `ftle: ${{read('ftle')}}`,
    `ftle_smooth: ${{read('ftle_smooth')}}`,
    `ridge_support: ${{read('ridge_support')}}`,
    `persistence_3d: ${{read('persistence_3d')}}`,
    `persistence_5d: ${{read('persistence_5d')}}`,
    `balanced_composite: ${{read('balanced_composite')}}`,
    `physics_first_composite: ${{read('physics_first_composite')}}`,
    `actual UTC: ${{activeRun.summary.metadata.actual_selected_utc || '—'}}`,
    `actual local: ${{activeRun.summary.metadata.actual_selected_local || '—'}}`,
    `fallback: ${{activeRun.summary.metadata.fallback_status || '—'}}`,
  ].join('\n');
  qs('popupBox').textContent = txt;
}});

renderRunButtons();
if(activeRun) loadRun(activeRun);
</script></body></html>'''
    target.write_text(html, encoding="utf-8")


def main() -> None:
    args = parse_args()
    project = load_config(args.config)
    latest_root = project.outputs_dir / "latest"
    pages_root = project.pages_dir
    pages_root.mkdir(parents=True, exist_ok=True)
    runs_root = pages_root / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)

    run_dirs = [p for p in sorted(latest_root.iterdir()) if p.is_dir() and (p / "ftle.nc").exists()]
    outs = [load_output_from_nc(p) for p in run_dirs]
    outs = attach_persistence_and_scores(outs, project.raw)

    video_frames = []
    manifest_runs = []
    for run_dir, out in zip(run_dirs, outs):
        plot_field_map(out, run_dir / "map_balanced.png", f"Balanced composite | {run_dir.name}", "balanced_composite", "0..1")
        plot_field_map(out, run_dir / "map_physics_first.png", f"Physics-first composite | {run_dir.name}", "physics_first_composite", "0..1")
        plot_field_map(out, run_dir / "map_persistence_3d.png", f"Persistence 3d | {run_dir.name}", "persistence_3d", "0..1")
        plot_field_map(out, run_dir / "map_persistence_5d.png", f"Persistence 5d | {run_dir.name}", "persistence_5d", "0..1")
        plot_field_map(out, run_dir / "map_ridge_support.png", f"Ridge support | {run_dir.name}", "ridge_support", "0..1")
        save_field_layers_json(out, run_dir / "field_layers.json")
        save_summary_json(out, run_dir / "summary.json")
        target_run_dir = runs_root / run_dir.name
        if target_run_dir.exists():
            shutil.rmtree(target_run_dir)
        shutil.copytree(run_dir, target_run_dir)
        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        manifest_runs.append({"name": run_dir.name, "summary": summary})
        if (run_dir / "map_physics_first.png").exists():
            video_frames.append(run_dir / "map_physics_first.png")

    video_rel = None
    if video_frames:
        video_path = pages_root / "sequence.mp4"
        build_sequence_video(video_frames, video_path, fps=int(project.raw.get("media", {}).get("fps", 2)))
        video_rel = "sequence.mp4"

    manifest = {"runs": manifest_runs, "sequence_video": video_rel}
    (pages_root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    render_dashboard(manifest, pages_root / "index.html")


if __name__ == "__main__":
    main()
