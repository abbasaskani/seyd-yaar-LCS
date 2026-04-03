# seyd-yaar-LCS

GitHub-first Copernicus Marine + numbacs pipeline for attracting LCS / backward FTLE.

## What it does
- Manual runs via **Actions > Run workflow** inputs
- Daily scheduled runs for **today** and **tomorrow**
- Pre-download **estimate** workflow using Copernicus `dry_run`
- Real run workflow that downloads/reuses raw subset, computes backward FTLE, builds MP4 + maps + GeoJSON/CSV/JSON, and publishes a single GitHub Pages site

## Repository layout
- `config/defaults.json` — defaults for bbox, backward days, outputs, page toggles
- `.github/workflows/estimate_lcs.yml` — dry-run size estimate only
- `.github/workflows/run_lcs.yml` — scheduled + manual real runs
- `outputs/latest/{today,tomorrow,custom}/` — latest raw + processed outputs
- `docs/latest/` — single-page site content published with GitHub Pages

## Secrets required
Set these repository secrets:
- `COPERNICUSMARINE_SERVICE_USERNAME`
- `COPERNICUSMARINE_SERVICE_PASSWORD`

## Manual run
Go to **Actions** → **Run LCS pipeline** → **Run workflow** and fill inputs.

## Change defaults
Edit `config/defaults.json`.
