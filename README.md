# Garmin Training Dashboard

Self-refreshing half-marathon training dashboard built from live Garmin Connect data.

`dashboard.py` pulls training load, VO2 max, HRV, sleep, resting HR, and recent runs via `garminconnect`, then writes `index.html`. A scheduled GitHub Actions workflow (`.github/workflows/deploy.yml`) rebuilds it every 2 hours and deploys it to GitHub Pages.

Run locally with `uv run dashboard.py`.
