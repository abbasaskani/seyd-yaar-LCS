# seyd-yaar-LCS

GitHub-first Copernicus Marine + numbacs pipeline for attracting LCS / backward FTLE, with AOI-driven runs, local-ocean-time target selection, persistence layers, composite indices, and a glass-style GitHub Pages dashboard.

## AOI

Only edit this file for polygon AOI input:

- `config/aoi/current.geojson`

If the AOI file exists, it has priority. If not, the pipeline falls back to bbox values from `config/defaults.json` or CLI overrides.

## Secrets required

Set these repository secrets:

- `COPERNICUSMARINE_SERVICE_USERNAME`
- `COPERNICUSMARINE_SERVICE_PASSWORD`
