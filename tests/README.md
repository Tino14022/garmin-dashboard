# Tests

Run with `python -m pytest tests/ -q` (needs `pytest` and `tzdata`), or as CI
does it: `uv run --with pytest --with tzdata python -m pytest tests/ -q`.

No Garmin credentials, no network. Every test drives the pipeline through
`FakeGarminApi` (raw Garmin-shaped payloads) or `FakeSource` (already-normalised
rows), which is the point of the source protocols.

| File | What it covers |
| --- | --- |
| `test_equivalence.py` | The SOLID refactor changed no computed value |
| `test_domain.py` | Pure transforms: formatting, nutrition, gamification, plan, health, config |
| `test_pipeline.py` | Full offline build, HTML assembly, failure reporting |
| `test_regressions.py` | Bugs found while refactoring |

## `legacy_reference.py`

A byte-identical copy of `dashboard.py` as it was before the refactor. It is
**not live code** — nothing outside `test_equivalence.py` imports it. It exists
so the refactor can be checked against the real previous implementation rather
than against my description of it: both are driven by the same fake API and the
same data files, and every key the old build produced is compared field by field.

Delete it once you no longer care about proving equivalence with the pre-refactor
build; `test_equivalence.py` goes with it.
