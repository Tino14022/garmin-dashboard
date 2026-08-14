"""Fetch-outcome tracking.

The old build wrapped every Garmin call in a retry helper that swallowed the
exception and returned a default. A page built from an expired token therefore
deployed successfully with silently empty charts. This records what actually
happened so the payload — and the page — can say so.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class FetchOutcome:
    name: str
    ok: bool
    error: str | None = None


@dataclass
class FetchLog:
    """Collects per-fetch outcomes over one build."""

    outcomes: list[FetchOutcome] = field(default_factory=list)

    def record(self, name: str, ok: bool, error: str | None = None) -> None:
        self.outcomes.append(FetchOutcome(name=name, ok=ok, error=error))

    @property
    def failures(self) -> list[FetchOutcome]:
        return [o for o in self.outcomes if not o.ok]

    @property
    def healthy(self) -> bool:
        return not self.failures

    def call(self, name, fn, *args, default=None, retries: int = 3, delay: float = 0.5):
        """Run a source call, retrying transient errors, and record the outcome."""
        last_error = None
        for attempt in range(retries):
            try:
                result = fn(*args)
                self.record(name, ok=True)
                return result
            except Exception as e:  # noqa: BLE001 - third-party client raises broadly
                last_error = e
                if attempt < retries - 1:
                    time.sleep(delay * (attempt + 1))
        message = f"{type(last_error).__name__}: {last_error}"
        print(f"  ! {name} failed after {retries} tries: {message}")
        self.record(name, ok=False, error=message)
        return default

    def to_payload(self) -> dict:
        return {
            "healthy": self.healthy,
            "total": len(self.outcomes),
            "failed": len(self.failures),
            "failures": [
                {"name": o.name, "error": o.error} for o in self.failures
            ],
        }
