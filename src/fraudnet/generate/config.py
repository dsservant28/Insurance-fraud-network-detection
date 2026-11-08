"""Generator settings: seed, scale, fixed dates and baseline counts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fraudnet.generate.scenario import Scenario

DEFAULT_SEED = 20261022
AS_OF_DATE = date(2026, 10, 22)

# Counts at scale 1.0. Claimant, provider and claim come from the brief; the others are design targets.
BASE_COUNTS = {
    "claimant": 2_000,
    "provider": 500,
    "policy": 2_600,
    "incident": 4_700,
    "claim": 5_000,
}


@dataclass(frozen=True)
class GeneratorConfig:
    seed: int = DEFAULT_SEED
    scale: float = 1.0
    scenario: "Scenario | None" = None  # stress scenarios only (docs/STRESS_PLAN.md); None is the normal world

    def __post_init__(self) -> None:
        if self.scale <= 0:
            raise ValueError(f"scale must be above 0, got {self.scale}")

    def count(self, entity: str) -> int:
        """Return the row count for an entity at this scale (at least 1)."""
        return max(1, round(BASE_COUNTS[entity] * self.scale))
