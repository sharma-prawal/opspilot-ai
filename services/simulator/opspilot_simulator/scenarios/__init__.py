"""Scenario registry."""

from __future__ import annotations

from opspilot_simulator.scenarios.base import Scenario
from opspilot_simulator.scenarios.inc001_schema_migration import SchemaMigrationScenario
from opspilot_simulator.scenarios.inc002_pool_exhaustion import PoolExhaustionScenario
from opspilot_simulator.scenarios.inc003_invalid_payloads import InvalidPayloadScenario
from opspilot_simulator.scenarios.negative import (
    AmbiguousIncompleteScenario,
    ExternalDependencyScenario,
    TransientBlipScenario,
)

SCENARIOS: dict[str, Scenario] = {
    s.key: s
    for s in (
        SchemaMigrationScenario(),
        PoolExhaustionScenario(),
        InvalidPayloadScenario(),
        TransientBlipScenario(),
        ExternalDependencyScenario(),
        AmbiguousIncompleteScenario(),
    )
}

# Fixed anchor (fault onset) and seed make every generated dataset byte-for-byte reproducible.
DEFAULT_SEED = 1001


def get_scenario(key: str) -> Scenario:
    try:
        return SCENARIOS[key]
    except KeyError:
        raise KeyError(f"unknown scenario {key!r}; available: {sorted(SCENARIOS)}") from None
