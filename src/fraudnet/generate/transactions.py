"""Baseline source rows: incidents, claims, provider links, invoices and invoice lines.

Only source facts are created here. Amount totals, events, payments and statuses are calculated
from these rows by lifecycle.py. Columns starting with `plan_` record a source decision, such as
a customer withdrawing, and are never exported.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from fraudnet.generate import pools
from fraudnet.generate.config import AS_OF_DATE, GeneratorConfig
from fraudnet.generate.master import MasterTables

WINDOW_START = date(2026, 1, 1)
WINDOW_END = date(2026, 9, 30)
WINDOW_DAYS = [WINDOW_START + timedelta(days=n) for n in range((WINDOW_END - WINDOW_START).days + 1)]

# Incident types each policy type covers, with selection probabilities.
INCIDENT_TYPES_BY_POLICY = {
    "AUTO": (("COLLISION", "THEFT", "INJURY"), (0.60, 0.20, 0.20)),
    "HOME": (("WATER_DAMAGE", "FIRE", "THEFT"), (0.45, 0.20, 0.35)),
    "HEALTH": (("ILLNESS", "INJURY"), (0.70, 0.30)),
}
ALL_INCIDENT_TYPES = tuple(pools.NARRATIVE_TEMPLATES)

# Median invoice size in dollars by incident type.
MEDIAN_INVOICE_DOLLARS = {
    "COLLISION": 2_500, "THEFT": 4_000, "INJURY": 1_800, "WATER_DAMAGE": 5_000, "FIRE": 9_000, "ILLNESS": 900,
}
# First entry is the usual provider type for the incident; others can appear on further invoices.
PROVIDER_TYPES_BY_INCIDENT = {
    "COLLISION": ("REPAIRER", "SERVICE", "MEDICAL"),
    "THEFT": ("REPAIRER", "SERVICE"),
    "INJURY": ("MEDICAL", "SERVICE"),
    "WATER_DAMAGE": ("REPAIRER", "SERVICE"),
    "FIRE": ("REPAIRER", "SERVICE"),
    "ILLNESS": ("MEDICAL",),
}

ACTIVITY_SHAPE = 5.0
ACTIVITY_MAX = 5.0
MAX_BASELINE_CLAIMS_PER_CLAIMANT = 8
OUTSIDE_COVERAGE_ACCEPT_RATE = 0.03  # Chance of keeping a drawn claimant and day with no cover in force.
TYPE_MISMATCH_RATE = 0.01
POLICY_BOUNDARY_DAY_RATE = 0.01
DEDUCTIBLE_BOUNDARY_RATE = 0.005
OVER_LIMIT_BOUNDARY_RATE = 0.003
WITHDRAW_RATE = 0.03
MANUAL_DENIAL_RATE = 0.05
INVOICE_REJECT_RATE = 0.04
LINE_COVERED_RATE = 0.90


@dataclass
class SourceTables:
    incident: list[dict]
    claim: list[dict]
    claim_provider: list[dict]
    invoice: list[dict]
    invoice_line: list[dict]


def _pick(rng: np.random.Generator, options):
    return options[int(rng.integers(len(options)))]


def _day_weights() -> np.ndarray:
    """Incidents vary by season and day of week."""
    weekday = (1.0, 1.0, 1.0, 1.0, 1.2, 0.85, 0.7)
    weights = [weekday[day.weekday()] * (1 + 0.20 * np.cos((day.timetuple().tm_yday - 15) / 365 * 2 * np.pi))
               for day in WINDOW_DAYS]
    return np.array(weights)


def _narrative(rng: np.random.Generator, incident_type: str) -> str:
    """Specific street and clock details keep unrelated narratives from matching by chance."""
    text = _pick(rng, pools.NARRATIVE_TEMPLATES[incident_type]).format(
        place=_pick(rng, pools.NARRATIVE_PLACES[incident_type]),
        time=_pick(rng, pools.NARRATIVE_TIMES),
        detail=_pick(rng, pools.NARRATIVE_DETAILS[incident_type]),
    )
    street = _pick(rng, pools.STREET_NAMES)
    return f"{text} It happened close to {street} at about {int(rng.integers(24)):02d}:{int(rng.integers(12)) * 5:02d}."


def _draw_incident(rng: np.random.Generator, claimant_keys: np.ndarray, activity: np.ndarray, day_weights: np.ndarray,
                   policy_keys_by_claimant: dict[int, list[int]], policies: dict[int, dict],
                   claims_by_claimant: dict[int, int]) -> tuple[int, int, date]:
    """Draw claimant and day together, and keep only pairs with cover in force.

    This gives every covered day the same chance of a claim. Choosing a policy first would squeeze
    all of a short overlap's claims into it and create false "claim soon after start" patterns.
    """
    while True:
        claimant_key = int(rng.choice(claimant_keys, p=activity))
        day = WINDOW_DAYS[int(rng.choice(len(WINDOW_DAYS), p=day_weights))]
        if claims_by_claimant.get(claimant_key, 0) >= MAX_BASELINE_CLAIMS_PER_CLAIMANT:
            continue
        held = policy_keys_by_claimant[claimant_key]
        covering = [key for key in held if policies[key]["effective_from"] <= day <= policies[key]["effective_to"]]
        if covering:
            policy_key = _pick(rng, covering)
            if rng.random() < POLICY_BOUNDARY_DAY_RATE:
                policy = policies[policy_key]
                edges = [d for d in (policy["effective_from"], policy["effective_to"]) if WINDOW_START <= d <= WINDOW_END]
                day = _pick(rng, edges) if edges else day
            return claimant_key, policy_key, day
        if rng.random() < OUTSIDE_COVERAGE_ACCEPT_RATE:
            return claimant_key, _pick(rng, held), day


def _incident_type(rng: np.random.Generator, policy_type: str) -> str:
    allowed, probabilities = INCIDENT_TYPES_BY_POLICY[policy_type]
    if rng.random() < TYPE_MISMATCH_RATE:
        return _pick(rng, tuple(t for t in ALL_INCIDENT_TYPES if t not in allowed))
    return str(rng.choice(allowed, p=probabilities))


def _location(rng: np.random.Generator, contacts: list[dict], day: date) -> tuple[str, str]:
    if rng.random() < 0.7:
        for contact in contacts:
            until = contact["effective_to"]
            if contact["effective_from"] <= day and (pd.isna(until) or day <= until):
                return contact["city"], contact["postal_code"]
    city_index = int(rng.integers(len(pools.CITIES)))
    return pools.CITIES[city_index], f"00{city_index * 10 + int(rng.integers(10)):03d}"


def _report_date(rng: np.random.Generator, incident_day: date) -> date:
    lag = min(45, int(rng.lognormal(1.3, 0.9)))
    return min(AS_OF_DATE, incident_day + timedelta(days=lag))


class _ProviderPicker:
    """Chooses an active provider. A few providers are genuinely much busier than others."""

    def __init__(self, rng: np.random.Generator, providers: list[dict]) -> None:
        self.providers = providers
        self.types = np.array([row["provider_type"] for row in providers])
        self.starts = np.array([row["active_from"].toordinal() for row in providers])
        self.ends = np.array([10**7 if pd.isna(row["active_to"]) else row["active_to"].toordinal()
                              for row in providers])
        ranks = rng.permutation(len(providers))
        self.weights = 1 / (ranks + 5.0)

    def choose(self, rng: np.random.Generator, provider_type: str, day: date) -> dict | None:
        ordinal = day.toordinal()
        active = (self.starts <= ordinal) & (ordinal <= self.ends)
        matches = np.flatnonzero(active & (self.types == provider_type))
        if not len(matches):
            matches = np.flatnonzero(active)
        if not len(matches):
            return None
        probabilities = self.weights[matches] / self.weights[matches].sum()
        return self.providers[int(rng.choice(matches, p=probabilities))]


class _ExternalNumbers:
    """Provider-printed invoice numbers. Baseline numbers never repeat."""

    def __init__(self, rng: np.random.Generator) -> None:
        self._rng = rng
        self._seen: set[int] = set()

    def next(self) -> str:
        while True:
            number = int(self._rng.integers(10_000_000))
            if number not in self._seen:
                self._seen.add(number)
                return f"EXT-{number:07d}"


def _build_lines(rng: np.random.Generator, invoice_key: int, role: str, incident_type: str,
                 exact_cents: int | None) -> list[dict]:
    if exact_cents is not None:
        return [{"invoice_key": invoice_key, "line_no": 1, "service_code": pools.SERVICE_CODES[role][0],
                 "quantity": 1, "unit_price_cents": exact_cents, "is_covered": 1}]
    line_count = int(rng.integers(1, 6))
    total = MEDIAN_INVOICE_DOLLARS[incident_type] * 100 * rng.lognormal(0, 0.7)
    shares = rng.dirichlet(np.full(line_count, 2.0))
    rows = []
    for number, share in enumerate(shares, start=1):
        quantity = int(rng.integers(1, 5))
        rows.append({
            "invoice_key": invoice_key,
            "line_no": number,
            "service_code": _pick(rng, pools.SERVICE_CODES[role]),
            "quantity": quantity,
            "unit_price_cents": max(100, int(round(total * share / quantity))),
            "is_covered": int(rng.random() < LINE_COVERED_RATE),
        })
    return rows


def _service_role(rng: np.random.Generator, provider_type: str) -> str:
    if provider_type == "REPAIRER":
        return "REPAIR"
    if provider_type == "MEDICAL":
        return "MEDICAL"
    return _pick(rng, ("TOWING", "LEGAL"))


def _build_invoices(rng: np.random.Generator, claims: list[dict], incidents_by_key: dict[int, dict],
                    policies_by_key: dict[int, dict], picker: _ProviderPicker) -> tuple[list[dict], list[dict], list[dict]]:
    invoices, lines, links = [], [], {}
    numbers = _ExternalNumbers(rng)
    for claim in claims:
        incident = incidents_by_key[claim["incident_key"]]
        policy = policies_by_key[claim["policy_key"]]
        count = int(rng.choice((0, 1, 2, 3), p=(0.03, 0.70, 0.22, 0.05)))

        draw = rng.random()
        exact_cents = None
        if count and draw < DEDUCTIBLE_BOUNDARY_RATE:
            count, exact_cents = 1, policy["deductible_cents"]
        elif count and draw < DEDUCTIBLE_BOUNDARY_RATE + OVER_LIMIT_BOUNDARY_RATE:
            count, exact_cents = 1, policy["coverage_limit_cents"] + policy["deductible_cents"] + 100_000

        provider_types = PROVIDER_TYPES_BY_INCIDENT[incident["incident_type"]]
        for position in range(count):
            lag = int(rng.integers(0, 31))
            invoice_day = min(AS_OF_DATE, claim["reported_date"] + timedelta(days=lag))
            wanted = provider_types[0] if position == 0 else _pick(rng, provider_types)
            provider = picker.choose(rng, wanted, invoice_day)
            if provider is None:
                continue

            link_key = (claim["claim_key"], provider["provider_key"])
            if link_key not in links:
                links[link_key] = {
                    "claim_key": claim["claim_key"],
                    "provider_key": provider["provider_key"],
                    "service_role": _service_role(rng, provider["provider_type"]),
                    "assigned_date": invoice_day,
                }
            links[link_key]["assigned_date"] = min(links[link_key]["assigned_date"], invoice_day)

            invoice_key = len(invoices)
            invoices.append({
                "invoice_key": invoice_key,
                "provider_key": provider["provider_key"],
                "claim_key": claim["claim_key"],
                "external_invoice_no": numbers.next(),
                "invoice_date": invoice_day,
                "plan_reject": bool(rng.random() < INVOICE_REJECT_RATE) and exact_cents is None,
            })
            lines.extend(_build_lines(rng, invoice_key, links[link_key]["service_role"],
                                      incident["incident_type"], exact_cents))
    return invoices, lines, list(links.values())


def build_transaction_source(config: GeneratorConfig, rng: np.random.Generator,
                             master: MasterTables) -> SourceTables:
    claimant_keys = master.claimant["claimant_key"].to_numpy()
    policies_by_key = {row["policy_key"]: row for row in master.policy.to_dict("records")}
    policy_keys_by_claimant: dict[int, list[int]] = {}
    for row in master.claimant_policy.to_dict("records"):
        policy_keys_by_claimant.setdefault(row["claimant_key"], []).append(row["policy_key"])
    contacts_by_claimant: dict[int, list[dict]] = {}
    for row in master.claimant_contact.to_dict("records"):
        contacts_by_claimant.setdefault(row["claimant_key"], []).append(row)

    day_weights = _day_weights()
    day_weights = day_weights / day_weights.sum()
    claim_count = config.count("claim")
    incident_count = min(config.count("incident"), claim_count)

    # Long tail: many claimants have 1-3 claims, some have none and a few have more.
    activity = np.minimum(rng.gamma(ACTIVITY_SHAPE, 1.0, size=len(claimant_keys)), ACTIVITY_MAX)
    activity = activity / activity.sum()

    incidents: list[dict] = []
    claims: list[dict] = []
    claims_by_claimant: dict[int, int] = {}

    def add_claim(claimant_key: int, policy_key: int, incident: dict) -> None:
        claims_by_claimant[claimant_key] = claims_by_claimant.get(claimant_key, 0) + 1
        claims.append({
            "claim_key": len(claims),
            "incident_key": incident["incident_key"],
            "claimant_key": claimant_key,
            "policy_key": policy_key,
            "reported_date": _report_date(rng, incident["incident_date"]),
            "plan_withdraw": bool(rng.random() < WITHDRAW_RATE),
            "plan_manual_denial": bool(rng.random() < MANUAL_DENIAL_RATE),
        })

    def add_incident() -> None:
        claimant_key, policy_key, day = _draw_incident(rng, claimant_keys, activity, day_weights,
                                                       policy_keys_by_claimant, policies_by_key, claims_by_claimant)
        policy = policies_by_key[policy_key]
        incident_type = _incident_type(rng, policy["policy_type"])
        city, postal_code = _location(rng, contacts_by_claimant[claimant_key], day)
        is_vehicle = policy["policy_type"] == "AUTO" and incident_type in {"COLLISION", "THEFT"}
        incident = {
            "incident_key": len(incidents),
            "incident_type": incident_type,
            "incident_date": day,
            "city": city,
            "postal_code": postal_code,
            "narrative": _narrative(rng, incident_type),
            "vehicle_ref": f"VEH-{policy_key + 1:06d}" if is_vehicle else None,
        }
        incidents.append(incident)
        add_claim(claimant_key, policy_key, incident)

    for _ in range(incident_count):
        add_incident()

    # Remaining claims come from a second, unrelated driver in a real two-party collision.
    auto_holders = [(row["claimant_key"], row["policy_key"]) for row in master.claimant_policy.to_dict("records")
                    if policies_by_key[row["policy_key"]]["policy_type"] == "AUTO"]
    collisions = [row for row in incidents if row["incident_type"] == "COLLISION"]
    parties = {claim["incident_key"]: {claim["claimant_key"]} for claim in claims}
    while len(claims) < claim_count:
        attached = False
        for _ in range(50):
            if not collisions or not auto_holders:
                break
            incident = _pick(rng, collisions)
            claimant_key, policy_key = _pick(rng, auto_holders)
            policy = policies_by_key[policy_key]
            if (claimant_key not in parties[incident["incident_key"]]
                    and claims_by_claimant.get(claimant_key, 0) < MAX_BASELINE_CLAIMS_PER_CLAIMANT
                    and policy["effective_from"] <= incident["incident_date"] <= policy["effective_to"]):
                parties[incident["incident_key"]].add(claimant_key)
                add_claim(claimant_key, policy_key, incident)
                attached = True
                break
        if not attached:
            add_incident()
            parties[incidents[-1]["incident_key"]] = {claims[-1]["claimant_key"]}

    incidents_by_key = {row["incident_key"]: row for row in incidents}
    picker = _ProviderPicker(rng, master.provider.to_dict("records"))
    invoices, lines, links = _build_invoices(rng, claims, incidents_by_key, policies_by_key, picker)
    return SourceTables(incident=incidents, claim=claims, claim_provider=links, invoice=invoices, invoice_line=lines)
