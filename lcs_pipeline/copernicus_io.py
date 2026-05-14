name: Run LCS pipeline

on:
  workflow_dispatch:
    inputs:
      mode_choice:
        description: routine | single_horizon | custom_range | custom_single
        required: true
        default: routine
        type: choice
        options:
          - routine
          - single_horizon
          - custom_range
          - custom_single
      horizon_offset:
        description: Single horizon offset in days for single_horizon mode
        required: false
        default: ''
        type: string
      timezone_preset:
        description: Timezone preset override key
        required: false
        default: utc_plus_4
        type: string
      range_start_local_date:
        description: Start local date for custom_range (YYYY-MM-DD)
        required: false
        default: ''
        type: string
      range_end_local_date:
        description: End local date for custom_range (YYYY-MM-DD)
        required: false
        default: ''
        type: string
      range_step_hours:
        description: Step hours for custom_range
        required: false
        default: '24'
        type: string
      single_local_datetime:
        description: Local datetime for custom_single (YYYY-MM-DDTHH:MM)
        required: false
        default: ''
        type: string
  schedule:
    - cron: '0 3 * * *'

permissions:
  contents: write
  pages: write
  id-token: write

concurrency:
  group: lcs-pages
  cancel-in-progress: false

jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 360
    env:
      COPERNICUSMARINE_SERVICE_USERNAME: ${{ secrets.COPERNICUSMARINE_SERVICE_USERNAME }}
      COPERNICUSMARINE_SERVICE_PASSWORD: ${{ secrets.COPERNICUSMARINE_SERVICE_PASSWORD }}
      PYTHONUNBUFFERED: '1'
      TQDM_DISABLE: '1'
      PYTHONWARNINGS: 'once'
      COPERNICUSMARINE_DISABLE_PROGRESS_BAR: '1'
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: '3.10'
          cache: 'pip'
          cache-dependency-path: requirements.txt
      - name: Install package and requirements
        run: |
          python -m pip install --upgrade pip
          python -m pip install -e .
          python -m pip install -r requirements.txt
      - name: Run routine horizons
        if: github.event_name == 'schedule' || github.event.inputs.mode_choice == 'routine'
        run: python scripts/run_scheduled_modes.py
      - name: Run one horizon
        if: github.event_name == 'workflow_dispatch' && github.event.inputs.mode_choice == 'single_horizon'
        run: |
          python scripts/run_pipeline.py --offset-days "${{ github.event.inputs.horizon_offset }}" --preset "${{ github.event.inputs.timezone_preset }}" --run-label manual_horizon --mode single_horizon
          python scripts/build_pages.py
      - name: Run custom range
        if: github.event_name == 'workflow_dispatch' && github.event.inputs.mode_choice == 'custom_range'
        run: |
          python scripts/run_custom_range.py --start-local-date "${{ github.event.inputs.range_start_local_date }}" --end-local-date "${{ github.event.inputs.range_end_local_date }}" --step-hours "${{ github.event.inputs.range_step_hours }}" --preset "${{ github.event.inputs.timezone_preset }}"
      - name: Run custom single target
        if: github.event_name == 'workflow_dispatch' && github.event.inputs.mode_choice == 'custom_single'
        run: |
          python scripts/run_single_target.py --target-local-datetime "${{ github.event.inputs.single_local_datetime }}" --preset "${{ github.event.inputs.timezone_preset }}"
      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: lcs-run
          path: |
            outputs/latest/
            outputs/archive/
            docs/latest/
      - name: Commit latest outputs
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add outputs/latest outputs/archive docs/latest config/aoi/current.geojson config/defaults.json pyproject.toml lcs_pipeline/__init__.py
          git diff --cached --quiet || git commit -m "Update LCS outputs"
          git push
      - name: Setup Pages
        uses: actions/configure-pages@v5
      - name: Upload Pages artifact
        uses: actions/upload-pages-artifact@v4
        with:
          path: docs
      - name: Deploy Pages
        uses: actions/deploy-pages@v4
