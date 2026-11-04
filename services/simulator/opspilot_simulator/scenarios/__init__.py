"""Scenario registry."""

from __future__ import annotations

from opspilot_simulator.scenarios.base import Scenario
from opspilot_simulator.scenarios.inc001_schema_migration import SchemaMigrationScenario

SCENARIOS: dict[str, Scenario] = {s.key: s for s in (SchemaMigrationScenario(),)}

# Fixed anchor (fault onset) and seed make every generated dataset byte-for-byte reproducible.
DEFAULT_SEED = 1001


def get_scenario(key: str) -> Scenario:
    try:
        return SCENARIOS[key]
    except KeyError:
        raise KeyError(f"unknown scenario {key!r}; available: {sorted(SCENARIOS)}") from None
