# /// script
# requires-python = ">=3.11"
# dependencies = ["garminconnect>=0.2.29", "tzdata>=2024.1"]
# ///
"""Garmin half-marathon training dashboard.

Run with:  uv run dashboard.py

Composition root: picks the concrete Garmin source, the on-disk data store and
the output path, then hands them to the pipeline. All the logic lives in the
garmin_dashboard package next to this file, which has no Garmin dependency and
is exercised offline by the tests.

Garmin credentials come from cached OAuth tokens (never a password prompt),
read from the GARMINTOKENS env var (a path or the raw token JSON, used in CI)
or ~/.garminconnect locally.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from garmin_dashboard.config import DEFAULT_SETTINGS
from garmin_dashboard.domain.health import FetchLog
from garmin_dashboard.pipeline import build_payload
from garmin_dashboard.rendering import build_html
from garmin_dashboard.sources.garmin import GarminSource, login
from garmin_dashboard.storage import JsonDataStore

HERE = Path(__file__).parent
OUTPUT_PATH = HERE / "index.html"

# A build that lost this much of its data is not worth deploying — better to
# fail loudly than to publish a page that looks fine with empty charts.
MAX_TOLERATED_FAILURES = 3


def main() -> int:
    settings = DEFAULT_SETTINGS
    log = FetchLog()

    print("Logging in to Garmin Connect (cached tokens)...")
    source = GarminSource(login(), log)
    print(f"Logged in as {source.athlete_name()}")

    print("Building payload (day-by-day endpoints take a while)...")
    data = build_payload(
        source,
        JsonDataStore(HERE / "data"),
        settings,
        log,
        generated_at_time=time.strftime("%Y-%m-%d %H:%M %Z"),
    )

    html = build_html(
        data,
        app_template=HERE / "app_template.html",
        running_template=HERE / "template.html",
    )
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"\nWrote {OUTPUT_PATH}")

    failures = log.failures
    if failures:
        print(f"\n{len(failures)} of {len(log.outcomes)} fetches failed:")
        for f in failures:
            print(f"  - {f.name}: {f.error}")
        if len(failures) > MAX_TOLERATED_FAILURES:
            print("\nToo many failures to publish a trustworthy page.")
            return 1
        print("\nPublishing anyway; the page will show a data-health warning.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
