"""Stress scenarios: deliberate changes to the generated world. Specification: docs/STRESS_PLAN.md section 4.

With no scenario, the generator is exactly the normal generator. A scenario changes the world in one of three
places:

- `PlantKnobs`: how fraud rings and extra innocent groups are planted (S0, S2, S3, S4).
- `perturb_tables`: raw values after the tables are final and before the relationship register is built (S1, S5b, S5c).
- `perturb_register`: rows dropped from the relationship register (S5a).

Value-level noise uses its own random generator, seeded from the generator seed and the scenario name. Each cell
draws one uniform number and is changed when that number is below the strength, so a stronger level changes a
superset of the cells a weaker level changes, in the same world.
"""
from __future__ import annotations

import math
import re
import zlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from fraudnet.generate.config import GeneratorConfig

STRENGTHS = (0.25, 0.5, 0.75, 1.0)
LEVELS = {
    "S0": ("no fraud",),
    "S1a": STRENGTHS, "S1b": STRENGTHS, "S1c": STRENGTHS,
    "S2": STRENGTHS,
    "S3a": ("pairs",), "S3b": ("large",), "S3c": ("x2", "x3", "x4"),
    "S4a": ("B-ROOM-01",), "S4b": ("B-FAMILY-02",), "S4c": ("B-FLEET-01",), "S4d": ("B-AGENT-01",),
    "S5a": STRENGTHS, "S5b": STRENGTHS, "S5c": STRENGTHS,
}
TITLES = {
    "S0": "A world with no fraud",
    "S1a": "Cosmetic identifier formats",
    "S1b": "Same identifier, uncovered form",
    "S1c": "Identifier typos",
    "S2": "Camouflaged rings",
    "S3a": "Two-person rings",
    "S3b": "Rings of 15 to 25",
    "S3c": "More rings per pattern",
    "S4a": "Flatmates",
    "S4b": "Blended families",
    "S4c": "Company fleets",
    "S4d": "Body shops with boilerplate",
    "S5a": "Gaps in the relationship register",
    "S5b": "Missing bank details",
    "S5c": "Placeholder narratives",
}
PLACEHOLDERS = ("No description provided.", "See attached report.", "N/A")

# Word swaps for reworded ring stories (S2). Every key appears in the COLLISION or INJURY narratives.
SYNONYMS = {
    "struck": "hit", "hit": "struck", "car": "vehicle", "vehicle": "car", "stopped": "waiting", "near": "by",
    "turning": "cornering", "driver": "motorist", "failed": "neglected", "yield": "stop", "injured": "hurt",
    "fall": "slip", "treatment": "care", "accident": "mishap", "needed": "required", "front": "forward",
    "bumper": "fender", "rear": "back", "dented": "bashed", "broke": "snapped", "smashed": "shattered",
    "bent": "buckled", "sprained": "twisted", "bruised": "battered", "strained": "pulled", "stitches": "sutures",
    "swollen": "puffy", "advised": "recommended", "junction": "intersection", "roundabout": "circle",
    "crossing": "crosswalk", "sidewalk": "pavement", "stairway": "staircase", "entrance": "doorway",
    "happened": "occurred", "close": "near", "about": "around", "collision": "crash", "while": "when",
    "damaged": "harmed", "another": "a", "behind": "the back",
}


@dataclass(frozen=True)
class Scenario:
    """One stress scenario at one level: a strength between 0 and 1, or a named level."""

    name: str
    level: float | str

    def __post_init__(self) -> None:
        if self.name not in LEVELS:
            raise ValueError(f"unknown scenario {self.name}")
        if isinstance(self.level, (int, float)):
            if not 0 <= self.level <= 1:
                raise ValueError(f"strength must be between 0 and 1, got {self.level}")
        elif self.level not in LEVELS[self.name]:
            raise ValueError(f"unknown level {self.level} for {self.name}")

    @property
    def strength(self) -> float:
        return float(self.level) if isinstance(self.level, (int, float)) else 1.0

    @property
    def label(self) -> str:
        return f"{self.name}@{self.level}"


@dataclass(frozen=True)
class PlantKnobs:
    """Planting settings. The defaults are the normal generator's."""

    rings_per_pattern: int = 4
    ring_size: tuple[int, int] = (3, 8)
    share_fraction: float = 1.0          # share of a ring's members that get its shared values
    story_swaps: int = 0                 # words swapped in each copy of a ring story
    early_days_max: int = 10             # R-RING-03: days after policy start
    burst_window_days: int = 30          # R-RING-03: policy starts within this window
    invoice_lag_max_days: int = 2        # R-RING-03
    inflation_range: tuple[float, float] = (2.5, 4.0)
    plant_fraud: bool = True             # False for S0: no rings and no duplicate invoices
    extra_benign: str | None = None      # S4: one innocent rule the detector has never seen
    extra_benign_groups: int = 20


def knobs(config: "GeneratorConfig") -> PlantKnobs:
    scenario = config.scenario
    if scenario is None:
        return PlantKnobs()
    s = scenario.strength
    if scenario.name == "S0":
        return PlantKnobs(plant_fraud=False)
    if scenario.name == "S2":
        low = 2.5 + (1.3 - 2.5) * s
        high = 4.0 + (2.0 - 4.0) * s
        return PlantKnobs(share_fraction=1 - 0.6 * s, story_swaps=round(6 * s),
                          early_days_max=round(10 + 30 * s), burst_window_days=round(30 + 90 * s),
                          invoice_lag_max_days=round(2 + 28 * s), inflation_range=(low, high))
    if scenario.name == "S3a":
        return PlantKnobs(ring_size=(2, 2))
    if scenario.name == "S3b":
        return PlantKnobs(ring_size=(15, 25))
    if scenario.name == "S3c":
        return PlantKnobs(rings_per_pattern=4 * int(str(scenario.level)[1:]))
    if scenario.name.startswith("S4"):
        return PlantKnobs(extra_benign=str(scenario.level))
    return PlantKnobs()


def sharers(keys: list[int], knob: PlantKnobs, base: int | None = None) -> list[int]:
    """The members that get a ring's shared values: `base` of them normally, fewer when camouflaged."""
    count = len(keys) if base is None else base
    if knob.share_fraction < 1.0:
        count = min(count, max(2, math.ceil(knob.share_fraction * len(keys))))
    return keys[:count]


def noise_rng(config: "GeneratorConfig") -> np.random.Generator:
    name = config.scenario.name if config.scenario else "none"
    return np.random.default_rng([config.seed, zlib.crc32(name.encode("utf-8"))])


def reword(rng: np.random.Generator, text: str, swaps: int) -> str:
    """Swap up to `swaps` words for synonyms (S2)."""
    if swaps <= 0:
        return text
    words = text.split(" ")
    candidates = [index for index, word in enumerate(words) if re.sub(r"[^a-z]", "", word.lower()) in SYNONYMS]
    chosen = rng.permutation(candidates)[:swaps] if candidates else []
    for index in chosen:
        word = words[index]
        core = re.sub(r"[^A-Za-z]", "", word)
        replacement = SYNONYMS[core.lower()]
        if core[:1].isupper():
            replacement = replacement[:1].upper() + replacement[1:]
        words[index] = word.replace(core, replacement, 1)
    return " ".join(words)


# ---- value-level noise (S1, S5b, S5c)

def _cosmetic(rng: np.random.Generator, field: str, value: str) -> str:
    if field == "phone":
        a, b, c = value.split("-")
        return (f"({a}) {b}-{c}", f"{a}.{b}.{c}", f"{a} {b} {c}")[int(rng.integers(3))]
    if field == "email":
        return value.upper() if rng.random() < 0.5 else f" {value} "
    if field == "bank_token":
        return value.lower()
    if field == "address_line":
        from fraudnet.generate.pools import STREET_SUFFIXES
        forms = {**STREET_SUFFIXES, **{short: full for full, short in STREET_SUFFIXES.items()}}
        words = value.split(" ")
        words[-1] = forms.get(words[-1].title(), words[-1])
        text = " ".join(words)
        return text.upper() if rng.random() < 0.5 else text.title()
    return value


def _uncovered(rng: np.random.Generator, field: str, value: str) -> str:
    pick = int(rng.integers(2))
    if field == "phone":
        a, b, c = value.split("-")
        return (f"+1 {a}-{b}-{c}", f"001 {a} {b} {c}")[pick]
    if field == "email":
        local, domain = value.split("@")
        return f"{local}+{('claims', 'ins')[pick]}@{domain}"
    if field == "bank_token":
        return (value.replace("-", " "), value.replace("-", ""))[pick]
    if field == "postal_code":
        return f"{value}-000{pick + 1}"
    return value


def _typo(rng: np.random.Generator, field: str, value: str) -> str:
    if field in ("phone", "bank_token"):
        positions = [index for index, char in enumerate(value) if char.isdigit()][-7:]
    elif field == "email":
        local = value.split("@")[0]
        positions = [index for index, char in enumerate(local) if char.isalpha()]
    else:  # address_line: a letter of the street name (between the house number and the suffix)
        words = value.split(" ")
        start = len(words[0]) + 1
        positions = list(range(start, start + len(" ".join(words[1:-1]))))
        positions = [index for index in positions if value[index].isalpha()]
    if not positions:
        return value
    index = positions[int(rng.integers(len(positions)))]
    old = value[index]
    alphabet = "0123456789" if old.isdigit() else "abcdefghijklmnopqrstuvwxyz"
    choices = [char for char in alphabet if char != old.lower()]
    new = choices[int(rng.integers(len(choices)))]
    return value[:index] + (new.upper() if old.isupper() else new) + value[index + 1:]


_CONTACT_NOISE = {
    "S1a": (("phone", "email", "bank_token", "address_line"), _cosmetic),
    "S1b": (("phone", "email", "bank_token", "postal_code"), _uncovered),
    "S1c": (("phone", "email", "bank_token", "address_line"), _typo),
}


def perturb_tables(tables: dict[str, pd.DataFrame], config: "GeneratorConfig") -> None:
    """Change raw values in place (S1, S5b, S5c). Does nothing without a value-level scenario."""
    scenario = config.scenario
    if scenario is None or scenario.name not in (*_CONTACT_NOISE, "S5b", "S5c"):
        return
    rng, s = noise_rng(config), scenario.strength
    if scenario.name in _CONTACT_NOISE:
        fields, change = _CONTACT_NOISE[scenario.name]
        contact = tables["claimant_contact"].copy()
        # One draw and one sub-seed per cell, made up front, so a cell's change never depends on other cells.
        draws = rng.random((len(contact), len(fields)))
        seeds = rng.integers(2**63, size=(len(contact), len(fields)))
        for column, field in enumerate(fields):
            values = contact[field].tolist()
            for row, value in enumerate(values):
                if draws[row, column] < s and isinstance(value, str):
                    values[row] = change(np.random.default_rng(int(seeds[row, column])), field, value)
            contact[field] = values
        tables["claimant_contact"] = contact
    elif scenario.name == "S5b":
        contact = tables["claimant_contact"].copy()
        claimants = sorted(contact["claimant_id"].unique())
        draws = dict(zip(claimants, rng.random(len(claimants))))
        missing = contact["claimant_id"].map(draws) < s
        if missing.any():
            contact.loc[missing, "bank_token"] = None
        tables["claimant_contact"] = contact
    else:  # S5c
        incident = tables["incident"].copy()
        draws = rng.random(len(incident))
        picks = rng.integers(len(PLACEHOLDERS), size=len(incident))
        incident["narrative"] = [PLACEHOLDERS[pick] if draw < s else text
                                 for text, draw, pick in zip(incident["narrative"], draws, picks)]
        tables["incident"] = incident


CLAIMANT_PAIR_EDGES = ("SHARED_ADDRESS", "SHARED_PHONE", "SHARED_EMAIL", "SHARED_BANK")


def perturb_register(edges: pd.DataFrame, config: "GeneratorConfig") -> pd.DataFrame:
    """Drop claimant-pair rows from the relationship register (S5a)."""
    scenario = config.scenario
    if scenario is None or scenario.name != "S5a":
        return edges
    rng = noise_rng(config)
    draws = rng.random(len(edges))
    keep = ~(edges["edge_type"].isin(CLAIMANT_PAIR_EDGES).to_numpy() & (draws < scenario.strength))
    kept = edges[keep].drop(columns="edge_id").reset_index(drop=True)
    kept.insert(0, "edge_id", [f"EDG-{number:06d}" for number in range(1, len(kept) + 1)])
    return kept
