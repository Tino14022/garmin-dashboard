"""End-to-end build with no network: fake source in, real HTML out."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from garmin_dashboard.config import DEFAULT_SETTINGS
from garmin_dashboard.domain.health import FetchLog
from garmin_dashboard.pipeline import build_payload
from garmin_dashboard.rendering import build_html
from garmin_dashboard.sources.fake import FakeSource
from garmin_dashboard.sources.garmin import GarminSource
from garmin_dashboard.storage import DictDataStore

ROOT = Path(__file__).resolve().parent.parent
ANCHOR = date(2026, 8, 14)


def build(api, data_files, log=None, today=ANCHOR):
    log = log or FetchLog()
    return build_payload(
        GarminSource(api, log, pause=0),
        DictDataStore(data_files),
        DEFAULT_SETTINGS,
        log,
        today=today,
        generated_at_time="fixed",
    )


def test_fake_source_satisfies_the_pipeline(data_files):
    """LSP: a substitute source drives the whole build with nothing stubbed out."""
    source = FakeSource(
        runs=[
            {
                "date": ANCHOR.isoformat(),
                "start_time_local": f"{ANCHOR.isoformat()} 07:00:00",
                "distance_km": 12.0,
                "duration_s": 4200,
                "pace_sec_per_km": 350,
                "pace_label": "5:50/km",
                "avg_hr": 150,
                "label": "BASE",
            }
        ],
    )
    log = FetchLog()
    payload = build_payload(
        source,
        DictDataStore(data_files),
        DEFAULT_SETTINGS,
        log,
        today=ANCHOR,
        generated_at_time="fixed",
    )
    assert payload["athlete_name"] == "Test Athlete"
    assert payload["race_plan"]["current_longest_km"] == 12.0
    assert payload["build_health"]["healthy"] is True


def test_build_produces_parseable_html_carrying_the_payload(fake_api, data_files):
    payload = build(fake_api, data_files)
    html = build_html(
        payload,
        app_template=ROOT / "app_template.html",
        running_template=ROOT / "template.html",
    )
    assert "__DASHBOARD_DATA__" not in html
    assert "__RUNNING_TAB_STYLE__" not in html
    assert "__RUNNING_TAB_CONTENT__" not in html
    assert "__RUNNING_TAB_SCRIPT__" not in html

    embedded = re.search(r"const DATA = (\{.*?\});\n", html, re.S)
    assert embedded, "payload was not embedded"
    assert json.loads(embedded.group(1))["athlete_name"] == "Test Athlete"


def test_failing_fetches_are_reported_not_swallowed(data_files):
    from conftest import FakeGarminApi

    api = FakeGarminApi(fail={"get_sleep_daily", "get_rhr_daily"})
    log = FetchLog()
    payload = build(api, data_files, log=log)

    assert payload["sleep_trend"] == []
    health = payload["build_health"]
    assert health["healthy"] is False
    assert health["failed"] == 2
    assert {f["name"] for f in health["failures"]} == {"sleep_trend", "rhr_trend"}


def test_a_healthy_build_says_so(fake_api, data_files):
    payload = build(fake_api, data_files)
    assert payload["build_health"] == {
        "healthy": True,
        "total": payload["build_health"]["total"],
        "failed": 0,
        "failures": [],
    }
    assert payload["build_health"]["total"] > 5


def test_todays_plan_shows_and_a_stale_one_does_not(fake_api, data_files):
    assert build(fake_api, data_files)["workout_plan"]["name"] == "Push Day"
    tomorrow = build(fake_api, data_files, today=ANCHOR + timedelta(days=1))
    assert tomorrow["workout_plan"] is None


def test_race_plan_is_present_and_finishes_at_the_race(fake_api, data_files):
    plan = build(fake_api, data_files)["race_plan"]
    assert plan["race_distance_km"] == 21.1
    assert plan["weeks"][-1]["kind"] == "race"
    assert plan["days_remaining"] == (date(2026, 10, 4) - ANCHOR).days


@pytest.mark.parametrize("missing", ["nutrition", "trainings", "muscle_presets", "body_comp"])
def test_build_survives_a_missing_data_file(fake_api, data_files, missing):
    reduced = {k: v for k, v in data_files.items() if k != missing}
    payload = build(fake_api, reduced)
    assert payload["generated_at"] == ANCHOR.isoformat()


def test_empty_store_still_builds(fake_api):
    payload = build(fake_api, {})
    assert payload["nutrition"] == []
    assert payload["training"]["sessions"]
