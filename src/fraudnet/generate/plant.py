"""Plant labelled fraud rings and benign look-alikes. Rules: docs/DATA_DICTIONARY.md section 8.

Choices are made here, but planted claims go through the same invoice and lifecycle code as all
other claims, using the same name, address, narrative and amount sources. Only the hidden labels
record which rows were planted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from fraudnet.generate import pools
from fraudnet.generate.config import GeneratorConfig
from fraudnet.generate.lifecycle import policy_status_on
from fraudnet.generate.master import MasterTables
from fraudnet.generate.scenario import knobs, noise_rng, reword, sharers
from fraudnet.generate.transactions import (
    INCIDENT_TYPES_BY_POLICY,
    WINDOW_DAYS,
    WINDOW_END,
    WINDOW_START,
    day_weights,
    narrative_text,
)

# Ring count, ring size, invoice inflation and the timing burst live in scenario.PlantKnobs, whose
# defaults are the normal generator's: 4 rings per pattern of 3 to 8 members, inflation 2.5 to 4.0.
HOUSEHOLDS, HOUSEHOLD_SIZE = 150, (2, 5)
REPEAT_CLAIMANTS, REPEAT_CLAIMS, REPEAT_MIN_GAP_DAYS = 200, (3, 6), 45
COMMON_ADDRESS_SITES, SITE_RESIDENTS = 10, (8, 25)
POPULAR_PROVIDERS = 10
BENIGN_EVENTS, EVENT_CLAIMANTS = 3, (12, 25)
PAST_TENANT_ADDRESSES = 20
ORPHAN_POLICY_CLAIMS = 5
OVERPAID_CLAIMS = 10
DUPLICATE_INVOICE_GROUPS, DUPLICATE_INVOICE_CLAIMANTS = 5, (2, 3)
MAX_TRIES = 500

# Label outcome by rule family: (label_kind, is_fraud, expected_decision). EC-4 and EC-5 are labelled
# on their rings and look-alikes, so they keep those outcomes and only add an issue_type.
RULE_OUTCOMES = {
    "R-": ("FRAUD_RING", 1, "INVESTIGATE"),
    "B-": ("BENIGN_LOOKALIKE", 0, "CLEAR"),
    "EC-1": ("EDGE_CASE", 0, "ROUTE_EXCEPTION"),
    "EC-2": ("EDGE_CASE", 0, "REVIEW_PAYMENT"),
    "EC-3": ("EDGE_CASE", 1, "INVESTIGATE"),
}

# Incident type, the policy types that cover it, and the provider type that treats it.
PROVIDER_SCENARIOS = (("COLLISION", ("AUTO",), "REPAIRER"), ("INJURY", ("AUTO", "HEALTH"), "MEDICAL"))


@dataclass
class PlannedClaim:
    claimant_key: int
    policy_key: int
    group_no: int
    report_lag_days: int | None = None
    provider_keys: tuple[int, ...] = ()
    amount_factor: float = 1.0
    invoice_lag_max_days: int = 30
    orphan_policy_ref: str | None = None  # EC-1: the claim names this policy, which does not exist.
    invoice_copy_group: int | None = None  # EC-3: claims in one group carry copies of a single invoice.


@dataclass
class PlannedIncident:
    incident_type: str
    day: date
    claims: list[PlannedClaim]
    narrative: str | None = None
    location: tuple[str, str] | None = None


@dataclass
class Group:
    """One documented planted pattern. `reason` may name {claimants}, {providers}, {claims}, {invoices}
    and {payments}, which are filled in with final IDs."""

    group_no: int
    rule_id: str
    label_kind: str
    is_fraud: int
    expected_decision: str
    reason: str
    ring_id: str | None = None
    group_id: str | None = None
    issue_type: str | None = None
    claimant_keys: list[int] = field(default_factory=list)
    provider_keys: list[int] = field(default_factory=list)
    label_providers: bool = False


@dataclass
class PlantingPlan:
    groups: list[Group] = field(default_factory=list)
    incidents: list[PlannedIncident] = field(default_factory=list)
    popular_provider_keys: list[int] = field(default_factory=list)
    no_baseline_claims: set[int] = field(default_factory=set)  # Repeat claimants have exactly their planned claims.

    @property
    def planned_claims(self) -> list[PlannedClaim]:
        return [claim for incident in self.incidents for claim in incident.claims]


def add_group(plan: PlantingPlan, rule_id: str, reason: str, members=(), providers=(), issue_type: str | None = None,
              label_providers: bool = False) -> Group:
    """Record one planted group. Its label outcome comes from RULE_OUTCOMES, never a random draw."""
    family = rule_id if rule_id in RULE_OUTCOMES else rule_id[:2]
    label_kind, is_fraud, decision = RULE_OUTCOMES[family]
    is_ring = label_kind == "FRAUD_RING"
    same_kind = sum((existing.ring_id is not None) == is_ring for existing in plan.groups) + 1
    group = Group(
        group_no=len(plan.groups) + 1, rule_id=rule_id, reason=reason,
        label_kind=label_kind, is_fraud=is_fraud, expected_decision=decision,
        ring_id=f"RING-{same_kind:03d}" if is_ring else None,
        group_id=None if is_ring else f"GRP-{same_kind:04d}",
        issue_type=issue_type or (rule_id if label_kind == "EDGE_CASE" else None),
        claimant_keys=list(members),
        provider_keys=list(providers),
        label_providers=label_providers,
    )
    plan.groups.append(group)
    return group


def _scaled(config: GeneratorConfig, base: int, minimum: int = 1) -> int:
    return max(minimum, round(base * config.scale))


def _between(rng: np.random.Generator, bounds: tuple[int, int]) -> int:
    return int(rng.integers(bounds[0], bounds[1] + 1))


def _variant_of_address(rng: np.random.Generator, line: str) -> str:
    """The same address written differently, as people do. Baseline data has the same variety."""
    words = line.title().split()
    forms = {**pools.STREET_SUFFIXES, **{short: full for full, short in pools.STREET_SUFFIXES.items()}}
    words[-1] = forms.get(words[-1], words[-1])
    text = " ".join(words)
    return text.upper() if rng.random() < 0.2 else text


def _near_copy(rng: np.random.Generator, text: str) -> str:
    """Change the clock time, and sometimes the time of day, so repeated text is nearly identical."""
    match = re.search(r"(\d\d):(\d\d)\.$", text)
    minutes = (int(match[1]) * 60 + int(match[2]) + int(rng.integers(-2, 3)) * 5) % (24 * 60)
    text = f"{text[:match.start()]}{minutes // 60:02d}:{minutes % 60:02d}."
    if rng.random() < 0.3:
        times = "|".join(sorted(pools.NARRATIVE_TIMES, key=len, reverse=True))
        replacement = pools.NARRATIVE_TIMES[int(rng.integers(len(pools.NARRATIVE_TIMES)))]
        text = re.sub(rf"\b({times})\b", replacement, text, count=1)
    return text


class _Planner:
    def __init__(self, config: GeneratorConfig, rng: np.random.Generator, master: MasterTables) -> None:
        self.config, self.rng, self.master = config, rng, master
        self.plan = PlantingPlan()
        self.claimants = {row["claimant_key"]: row for row in master.claimant.to_dict("records")}
        self.policies = {row["policy_key"]: row for row in master.policy.to_dict("records")}
        self.bridge = master.claimant_policy.to_dict("records")
        self.contacts: dict[int, list[dict]] = {}
        for row in master.claimant_contact.to_dict("records"):
            self.contacts.setdefault(row["claimant_key"], []).append(row)
        self.held: dict[int, list[int]] = {}
        for row in self.bridge:
            self.held.setdefault(row["claimant_key"], []).append(row["policy_key"])
        self.policy_events: dict[int, list[dict]] = {}
        for row in master.policy_events.to_dict("records"):
            self.policy_events.setdefault(row["policy_key"], []).append(row)
        self.providers = {row["provider_key"]: row for row in master.provider.to_dict("records")}

        self.pool = [int(key) for key in rng.permutation(list(self.claimants))]
        self.used: set[int] = set()
        self.provider_pool = [int(key) for key in rng.permutation(list(self.providers))
                              if pd.isna(self.providers[int(key)]["active_to"])]
        self.used_providers: set[int] = set()
        weights = day_weights()
        self.day_probabilities = weights / weights.sum()
        self.knobs = knobs(config)  # the normal generator's settings unless a stress scenario says otherwise
        self.noise = noise_rng(config)  # only drawn from by stress scenarios

    # ---- shared helpers

    def _day(self) -> date:
        return WINDOW_DAYS[int(self.rng.choice(len(WINDOW_DAYS), p=self.day_probabilities))]

    def _surname(self, key: int) -> str:
        return self.claimants[key]["full_name"].rsplit(" ", 1)[1]

    def _in_force(self, policy_key: int, day: date) -> bool:
        policy = self.policies[policy_key]
        return (policy["effective_from"] <= day <= policy["effective_to"]
                and policy_status_on(self.policy_events[policy_key], day) == "ACTIVE")

    def _covering(self, key: int, day: date, types: tuple[str, ...] | None = None) -> int | None:
        for policy_key in self.held[key]:
            if self._in_force(policy_key, day) and (types is None or self.policies[policy_key]["policy_type"] in types):
                return policy_key
        return None

    def _take(self, count: int, check=None, minimum: int | None = None, distinct_surnames: bool = True) -> list[tuple]:
        """Reserve unused claimants, each with the value `check` returns. Returns [] if too few qualify."""
        chosen, surnames = [], set()
        for key in self.pool:
            if key in self.used or (distinct_surnames and self._surname(key) in surnames):
                continue
            value = check(key) if check else True
            if value is None:
                continue
            chosen.append((key, value))
            surnames.add(self._surname(key))
            if len(chosen) == count:
                break
        if len(chosen) < (count if minimum is None else minimum):
            return []
        self.used.update(key for key, _ in chosen)
        return chosen

    def _require(self, finder, what: str):
        for _ in range(MAX_TRIES):
            result = finder()
            if result:
                return result
        raise ValueError(f"could not plant {what}: scale {self.config.scale} is too small")

    def _take_provider(self, provider_type: str) -> int:
        for key in self.provider_pool:
            if key not in self.used_providers and self.providers[key]["provider_type"] == provider_type:
                self.used_providers.add(key)
                return key
        raise ValueError(f"no unused {provider_type} provider left: scale {self.config.scale} is too small")

    def _group(self, rule_id: str, reason: str, members=(), providers=(), issue_type: str | None = None,
               label_providers: bool = False) -> Group:
        return add_group(self.plan, rule_id, reason, members, providers, issue_type, label_providers)

    def _share(self, members: list[int], field_name: str) -> str:
        """Give every member the first member's value. Phones change over time, so only the current one is shared."""
        values = [self.contacts[key][-1][field_name] for key in members]
        value = next((item for item in values if not pd.isna(item)), None)
        if value is None:  # Only bank tokens can be empty: none of these members had one.
            value = self._unused_bank_token()
        for key in members:
            rows = self.contacts[key][-1:] if field_name == "phone" else self.contacts[key]
            for row in rows:
                row[field_name] = value
        return value

    def _unused_bank_token(self) -> str:
        existing = {row["bank_token"] for rows in self.contacts.values() for row in rows}
        existing |= {row["bank_token"] for row in self.providers.values()}
        while True:
            token = f"ACCT-{int(self.rng.integers(100_000_000)):08d}"
            if token not in existing:
                return token

    def _share_address(self, members: list[int]) -> str:
        source = self.contacts[members[0]][-1]
        for key in members[1:]:
            row = self.contacts[key][-1]
            row["address_line"] = _variant_of_address(self.rng, source["address_line"])
            row["city"], row["postal_code"] = source["city"], source["postal_code"]
        return f"{source['address_line']}, {source['city']}"

    def _incident_type(self, policy_key: int) -> str:
        allowed, probabilities = INCIDENT_TYPES_BY_POLICY[self.policies[policy_key]["policy_type"]]
        return str(self.rng.choice(allowed, p=probabilities))

    def _days_around(self, policy_key: int, center: date, span: int, count: int) -> list[date]:
        """Up to `count` different days around a date, while cover is in force.

        Days fall on both sides of the center, so planted claims don't drift later than normal claims.
        """
        days = {center}
        half = span // 2
        for _ in range(count - 1):
            day = center + timedelta(days=int(self.rng.integers(-half, half + 1)))
            if WINDOW_START <= day <= WINDOW_END and self._in_force(policy_key, day):
                days.add(day)
        return sorted(days)

    def _add_claims_near(self, group: Group, key: int, policy_key: int, center: date, span: int, count: int,
                         incident_type: str | None = None, **claim_options) -> None:
        """Add up to `count` single-claimant incidents on different days."""
        for day in self._days_around(policy_key, center, span, count):
            self.plan.incidents.append(PlannedIncident(
                incident_type=incident_type or self._incident_type(policy_key),
                day=day,
                claims=[PlannedClaim(key, policy_key, group.group_no, **claim_options)],
            ))

    def _ring_start(self, size: int, types: tuple[str, ...] | None = None) -> tuple[date, list[tuple[int, int]]]:
        def attempt():
            day = self._day()
            members = self._take(size, lambda key: self._covering(key, day, types), minimum=self.knobs.ring_size[0])
            return (day, members) if members else None
        return self._require(attempt, "a ring")

    # ---- fraud rings

    def ring_shared_contacts(self) -> None:
        for _ in range(_scaled(self.config, self.knobs.rings_per_pattern)):
            start, members = self._ring_start(_between(self.rng, self.knobs.ring_size))
            keys = [key for key, _ in members]
            fields = [str(name) for name in self.rng.choice(("phone", "email", "bank_token"),
                                                            size=_between(self.rng, (1, 2)), replace=False)]
            values = "; ".join(f"{name} {self._share(sharers(keys, self.knobs), name)}" for name in fields)
            group = self._group("R-RING-01", f"Claimants {{claimants}} have different surnames and addresses "
                                             f"but share {values}.", keys)
            for key, policy_key in members:
                self._add_claims_near(group, key, policy_key, start, 90, _between(self.rng, (1, 3)))

    def ring_repeated_narratives(self) -> None:
        for number in range(_scaled(self.config, self.knobs.rings_per_pattern)):
            incident_type, types, provider_type = PROVIDER_SCENARIOS[number % len(PROVIDER_SCENARIOS)]
            start, members = self._ring_start(_between(self.rng, self.knobs.ring_size), types)
            provider = self._take_provider(provider_type)
            text = narrative_text(self.rng, incident_type)
            group = self._group("R-RING-02", f"Claimants {{claimants}} filed nearly identical narratives "
                                             f"(\"{text}\") across separate incidents and locations, "
                                             f"all using provider {{providers}}.",
                                [key for key, _ in members], [provider])
            for key, policy_key in members:
                for day in self._days_around(policy_key, start, 90, _between(self.rng, (1, 2))):
                    city_index = int(self.rng.integers(len(pools.CITIES)))
                    self.plan.incidents.append(PlannedIncident(
                        incident_type=incident_type, day=day,
                        narrative=reword(self.noise, _near_copy(self.rng, text), self.knobs.story_swaps),
                        location=(pools.CITIES[city_index], f"00{city_index * 10 + int(self.rng.integers(10)):03d}"),
                        claims=[PlannedClaim(key, policy_key, group.group_no, provider_keys=(provider,))],
                    ))

    def ring_unusual_timing(self) -> None:
        for _ in range(_scaled(self.config, self.knobs.rings_per_pattern)):
            size = _between(self.rng, self.knobs.ring_size)
            provider = self._take_provider("REPAIRER")

            def attempt():
                lead = self.knobs.early_days_max + 5 + self.knobs.burst_window_days  # 45 normally
                anchor = WINDOW_START + timedelta(days=int(self.rng.integers((WINDOW_END - WINDOW_START).days - lead)))

                def recent_start(key: int):
                    for policy_key in self.held[key]:
                        policy = self.policies[policy_key]
                        if policy["policy_type"] != "AUTO" or not anchor <= policy["effective_from"] <= anchor + timedelta(days=self.knobs.burst_window_days):
                            continue
                        day = policy["effective_from"] + timedelta(days=int(self.rng.integers(0, self.knobs.early_days_max + 1)))
                        if self._in_force(policy_key, day):
                            return policy_key, day
                    return None
                return self._take(size, recent_start, minimum=self.knobs.ring_size[0])

            members = self._require(attempt, "an unusual-timing ring")
            keys = [key for key, _ in members]
            phone = self._share(sharers(keys, self.knobs, max(2, len(keys) // 2)), "phone")
            group = self._group("R-RING-03", f"Claimants {{claimants}} all claimed within days of a new policy "
                                             f"starting, reported and invoiced in a tight burst through provider "
                                             f"{{providers}}, and some share phone {phone}.", keys, [provider])
            for key, (policy_key, day) in members:
                self.plan.incidents.append(PlannedIncident(
                    incident_type="COLLISION", day=day,
                    claims=[PlannedClaim(key, policy_key, group.group_no, report_lag_days=_between(self.rng, (0, 1)),
                                         provider_keys=(provider,), invoice_lag_max_days=self.knobs.invoice_lag_max_days)],
                ))

    def ring_provider_collusion(self) -> None:
        for number in range(_scaled(self.config, self.knobs.rings_per_pattern)):
            incident_type, types, provider_type = PROVIDER_SCENARIOS[number % len(PROVIDER_SCENARIOS)]
            start, members = self._ring_start(_between(self.rng, self.knobs.ring_size), types)
            provider = self._take_provider(provider_type)
            keys = [key for key, _ in members]
            bank = self.providers[provider]["bank_token"]
            for key in sharers(keys, self.knobs):
                for row in self.contacts[key]:
                    row["bank_token"] = bank
            group = self._group("R-RING-04", f"Claimants {{claimants}} concentrate on provider {{providers}} with "
                                             f"inflated invoices, and their bank token {bank} is the provider's.",
                                keys, [provider], label_providers=True)
            for key, policy_key in members:
                self._add_claims_near(group, key, policy_key, start, 90, _between(self.rng, (2, 3)),
                                      incident_type=incident_type, provider_keys=(provider,),
                                      amount_factor=float(self.rng.uniform(*self.knobs.inflation_range)))

    def ring_staged_incident(self) -> None:
        for _ in range(_scaled(self.config, self.knobs.rings_per_pattern)):
            day, members = self._ring_start(_between(self.rng, self.knobs.ring_size), ("AUTO",))
            keys = [key for key, _ in members]
            providers = tuple(self._take_provider("REPAIRER") for _ in range(2))
            field_name = str(self.rng.choice(("phone", "bank_token")))
            value = self._share(sharers(keys, self.knobs, max(2, len(keys) // 2)), field_name)
            group = self._group("R-RING-05", f"Claimants {{claimants}} all claimed on the same staged collision, "
                                             f"used only providers {{providers}}, and some share {field_name} {value}.",
                                keys, providers)
            self.plan.incidents.append(PlannedIncident(
                incident_type="COLLISION", day=day,
                claims=[PlannedClaim(key, policy_key, group.group_no,
                                     provider_keys=(providers[int(self.rng.integers(2))],))
                        for key, policy_key in members],
            ))

    def ring_hidden_link(self) -> None:
        for _ in range(_scaled(self.config, self.knobs.rings_per_pattern)):
            start, members = self._ring_start(_between(self.rng, self.knobs.ring_size), ("AUTO",))
            keys = [key for key, _ in members]
            provider = self._take_provider("REPAIRER")
            linked = sharers(keys, self.knobs)
            bank, phone = self._share(linked, "bank_token"), self._share(linked, "phone")
            address = self._share_address(sharers(keys, self.knobs, max(2, len(keys) // 2)))
            group = self._group("R-RING-06", f"Claimants {{claimants}} share bank token {bank} and phone {phone}, some "
                                             f"use address {address} in different spellings, and all use provider "
                                             f"{{providers}}. These links are left out of the recorded edges.",
                                keys, [provider], issue_type="EC-4")
            for key, policy_key in members:
                self._add_claims_near(group, key, policy_key, start, 60, _between(self.rng, (1, 2)),
                                      incident_type="COLLISION", provider_keys=(provider,))

    # ---- edge cases EC-1 and EC-3 (EC-2 is added by the lifecycle step; EC-4 and EC-5 are rules above)

    def orphan_policy_claims(self) -> None:
        """EC-1: a well-formed policy number that matches no policy."""
        existing = len(self.policies)
        used_numbers: set[int] = set()
        for _ in range(_scaled(self.config, ORPHAN_POLICY_CLAIMS)):
            def attempt():
                day = self._day()
                members = self._take(1, lambda key: self._covering(key, day))
                return (day, members[0]) if members else None
            day, (key, hint_policy) = self._require(attempt, "an orphan policy claim")
            number = int(self.rng.integers(existing + 1, 1_000_000))
            while number in used_numbers:
                number = int(self.rng.integers(existing + 1, 1_000_000))
            used_numbers.add(number)
            reference = f"POL-{number:06d}"
            group = self._group("EC-1", f"Claim {{claims}} by claimant {{claimants}} names policy {reference}, "
                                        f"which does not exist.", [key])
            self.plan.incidents.append(PlannedIncident(
                incident_type=self._incident_type(hint_policy), day=day,
                claims=[PlannedClaim(key, hint_policy, group.group_no, orphan_policy_ref=reference)],
            ))

    def duplicate_invoices(self) -> None:
        """EC-3: the same provider invoice (number, date and amount) appears on claims of different claimants."""
        for _ in range(_scaled(self.config, DUPLICATE_INVOICE_GROUPS)):
            size = _between(self.rng, DUPLICATE_INVOICE_CLAIMANTS)

            def attempt():
                day = self._day()
                members = self._take(size, lambda key: self._covering(key, day, ("AUTO",)), minimum=2)
                return (day, members) if members else None

            day, members = self._require(attempt, "a duplicate invoice")
            provider = self._take_provider("REPAIRER")
            group = self._group("EC-3", "Claims {claims} from different claimants {claimants} carry invoices "
                                        "{invoices} from provider {providers} with the same number, date and amount.",
                                [key for key, _ in members], [provider])
            for position, (key, policy_key) in enumerate(members):
                # The first claim's invoice is copied, so later claims happen no later than the first.
                earlier = day - timedelta(days=int(self.rng.integers(0, 4)))
                when = day if position == 0 or not self._in_force(policy_key, earlier) else earlier
                self.plan.incidents.append(PlannedIncident(
                    incident_type="COLLISION", day=when,
                    claims=[PlannedClaim(key, policy_key, group.group_no, provider_keys=(provider,),
                                         invoice_copy_group=group.group_no)],
                ))

    # ---- benign look-alikes

    def past_tenants(self) -> None:
        moved = [key for key in self.pool if len(self.contacts[key]) > 1 and key not in self.used]
        for _ in range(_scaled(self.config, PAST_TENANT_ADDRESSES)):
            pair = None
            for earlier in moved:
                if earlier in self.used:
                    continue
                old_row = self.contacts[earlier][0]
                for later in moved:
                    if later in self.used or later == earlier:
                        continue
                    new_row = self.contacts[later][-1]
                    if new_row["effective_from"] > old_row["effective_to"]:
                        pair = (earlier, later, old_row, new_row)
                        break
                if pair:
                    break
            if pair is None:
                raise ValueError(f"not enough moved claimants: scale {self.config.scale} is too small")
            earlier, later, old_row, new_row = pair
            self.used.update((earlier, later))
            new_row["address_line"] = _variant_of_address(self.rng, old_row["address_line"])
            new_row["city"], new_row["postal_code"] = old_row["city"], old_row["postal_code"]
            self._group("B-MOVE-01", f"Claimants {{claimants}} lived at {old_row['address_line']}, {old_row['city']} "
                                     f"in separate periods: one left on {old_row['effective_to']}, the other arrived "
                                     f"on {new_row['effective_from']}.", [earlier, later])

    def shared_households(self) -> None:
        for _ in range(_scaled(self.config, HOUSEHOLDS)):
            members = self._take(_between(self.rng, HOUSEHOLD_SIZE), distinct_surnames=False)
            if not members:
                raise ValueError(f"not enough claimants for households: scale {self.config.scale} is too small")
            keys = [key for key, _ in members]
            surname = self._surname(keys[0])
            for key in keys[1:]:
                first = self.claimants[key]["full_name"].rsplit(" ", 1)[0]
                self.claimants[key]["full_name"] = f"{first} {surname}"
                for row in self.contacts[key]:
                    number_and_domain = row["email"].split(".", 2)[2]
                    row["email"] = f"{first}.{surname}".lower() + f".{number_and_domain}"
            address = self._share_address(keys)
            shared = [f"address {address}"]
            if self.rng.random() < 0.4:
                shared.append(f"phone {self._share(keys, 'phone')}")
            if self.rng.random() < 0.5:
                policy_key = self.held[keys[0]][0]
                policy = self.policies[policy_key]
                for key in keys[1:]:
                    self.bridge.append({
                        "claimant_key": key, "policy_key": policy_key, "role": "NAMED_INSURED",
                        "effective_from": policy["effective_from"], "effective_to": policy["effective_to"],
                    })
                    self.held[key].append(policy_key)
                shared.append("a joint policy")
            self._group("B-HOUSE-01", f"Claimants {{claimants}} are one family with surname {surname} sharing "
                                      f"{', '.join(shared)}.", keys)

    def common_addresses(self) -> None:
        for _ in range(_scaled(self.config, COMMON_ADDRESS_SITES)):
            members = self._take(_between(self.rng, SITE_RESIDENTS))
            if not members:
                raise ValueError(f"not enough claimants for common addresses: scale {self.config.scale} is too small")
            keys = [key for key, _ in members]
            address = self._share_address(keys)
            group = self._group("B-ADDR-01", f"Claimants {{claimants}} are unrelated residents of one building, "
                                             f"{address}, with no other link.", keys, issue_type="EC-5")
            group.expected_decision = "CLEAR"

    def popular_providers(self) -> None:
        for number in range(_scaled(self.config, POPULAR_PROVIDERS)):
            key = self._take_provider(("REPAIRER", "MEDICAL")[number % 2])
            self.plan.popular_provider_keys.append(key)
            self._group("B-PROV-01", "Provider {providers} is busy serving many unrelated customers.", (), [key],
                        label_providers=True)

    def repeat_claimants(self) -> None:
        for _ in range(_scaled(self.config, REPEAT_CLAIMANTS)):
            def spaced_claims(key: int):
                wanted, picks = _between(self.rng, REPEAT_CLAIMS), []
                day = WINDOW_START + timedelta(days=int(self.rng.integers(60)))
                while day <= WINDOW_END and len(picks) < wanted:
                    policy_key = self._covering(key, day)
                    if policy_key is not None:
                        picks.append((day, policy_key))
                        day += timedelta(days=REPEAT_MIN_GAP_DAYS + int(self.rng.integers(30)))
                    else:
                        day += timedelta(days=7)
                return picks if len(picks) >= REPEAT_CLAIMS[0] else None

            members = self._take(1, spaced_claims)
            if not members:
                raise ValueError(f"not enough claimants for repeat claims: scale {self.config.scale} is too small")
            key, picks = members[0]
            self.plan.no_baseline_claims.add(key)
            group = self._group("B-REPEAT-01", f"Claimant {{claimants}} has {len(picks)} genuine claims at least "
                                               f"{REPEAT_MIN_GAP_DAYS} days apart with varied incidents and providers.",
                                [key])
            for day, policy_key in picks:
                self.plan.incidents.append(PlannedIncident(
                    incident_type=self._incident_type(policy_key), day=day,
                    claims=[PlannedClaim(key, policy_key, group.group_no)],
                ))

    def benign_events(self) -> None:
        for _ in range(_scaled(self.config, BENIGN_EVENTS)):
            size = _between(self.rng, EVENT_CLAIMANTS)

            def attempt():
                day = self._day()
                if day > WINDOW_END - timedelta(days=2):
                    return None
                members = self._take(size, lambda key: self._covering(key, day, ("HOME",)), minimum=4)
                return (day, members) if members else None

            day, members = self._require(attempt, "a storm event")
            city_index = int(self.rng.integers(len(pools.CITIES)))
            street = pools.STREET_NAMES[int(self.rng.integers(len(pools.STREET_NAMES)))]
            template = pools.NARRATIVE_TEMPLATES["WATER_DAMAGE"][2]
            group = self._group("B-EVENT-01", f"Claimants {{claimants}} all had flood damage near {street} in "
                                              f"{pools.CITIES[city_index]} from one storm on {day}, with similar "
                                              f"narratives but no contact links.", [key for key, _ in members])
            for key, policy_key in members:
                when = day + timedelta(days=int(self.rng.integers(0, 3)))
                self.plan.incidents.append(PlannedIncident(
                    incident_type="WATER_DAMAGE", day=when if self._in_force(policy_key, when) else day,
                    narrative=narrative_text(self.rng, "WATER_DAMAGE", template=template, street=street),
                    location=(pools.CITIES[city_index], f"00{city_index * 10 + int(self.rng.integers(10)):03d}"),
                    claims=[PlannedClaim(key, policy_key, group.group_no)],
                ))

    # ---- innocent groups the detector was not designed around (stress scenario S4 only)

    def flatmates(self) -> None:
        """B-ROOM-01: unrelated people sharing a flat; half the flats also share a landline."""
        for _ in range(_scaled(self.config, self.knobs.extra_benign_groups)):
            members = self._take(_between(self.rng, (2, 4)))
            if not members:
                raise ValueError(f"not enough claimants for flatmates: scale {self.config.scale} is too small")
            keys = [key for key, _ in members]
            shared = [f"address {self._share_address(keys)}"]
            if self.rng.random() < 0.5:
                shared.append(f"landline {self._share(keys, 'phone')}")
            self._group("B-ROOM-01", f"Claimants {{claimants}} are unrelated flatmates sharing {', '.join(shared)}.", keys)

    def blended_families(self) -> None:
        """B-FAMILY-02: relatives with different surnames at one address with a joint bank account."""
        for _ in range(_scaled(self.config, self.knobs.extra_benign_groups)):
            members = self._take(_between(self.rng, (2, 4)))
            if not members:
                raise ValueError(f"not enough claimants for blended families: scale {self.config.scale} is too small")
            keys = [key for key, _ in members]
            address, bank = self._share_address(keys), self._share(keys, "bank_token")
            self._group("B-FAMILY-02", f"Claimants {{claimants}} are one family with different surnames, living at "
                                       f"{address} with joint bank account {bank}.", keys)

    def company_fleets(self) -> None:
        """B-FLEET-01: employees whose claim payouts go to their employer's one account."""
        for _ in range(_scaled(self.config, self.knobs.extra_benign_groups)):
            members = self._take(_between(self.rng, (5, 12)))
            if not members:
                raise ValueError(f"not enough claimants for fleets: scale {self.config.scale} is too small")
            keys = [key for key, _ in members]
            account = self._unused_bank_token()
            for key in keys:
                for row in self.contacts[key]:
                    row["bank_token"] = account
            self._group("B-FLEET-01", f"Claimants {{claimants}} drive for one company, whose account {account} "
                                      f"receives their claim payouts.", keys)

    def boilerplate_body_shops(self) -> None:
        """B-AGENT-01: a body shop that files its customers' claims with its own standard text."""
        for _ in range(_scaled(self.config, self.knobs.extra_benign_groups)):
            size = _between(self.rng, (6, 10))
            provider = self._take_provider("REPAIRER")

            def own_day(key: int):
                day = self._day()
                policy_key = self._covering(key, day, ("AUTO",))
                return None if policy_key is None else (policy_key, day)

            members = self._take(size, own_day, minimum=6)
            if not members:
                raise ValueError(f"not enough claimants for body shops: scale {self.config.scale} is too small")
            text = narrative_text(self.rng, "COLLISION")
            group = self._group("B-AGENT-01", f"Provider {{providers}} filed claims {{claims}} for its unrelated "
                                              f"customers {{claimants}} with its standard text (\"{text}\").",
                                [key for key, _ in members], [provider])
            for key, (policy_key, day) in members:
                city_index = int(self.rng.integers(len(pools.CITIES)))
                self.plan.incidents.append(PlannedIncident(
                    incident_type="COLLISION", day=day, narrative=text,
                    location=(pools.CITIES[city_index], f"00{city_index * 10 + int(self.rng.integers(10)):03d}"),
                    claims=[PlannedClaim(key, policy_key, group.group_no, provider_keys=(provider,))],
                ))

    def apply_to_master(self) -> None:
        self.master.claimant = pd.DataFrame(list(self.claimants.values()))
        self.master.claimant_contact = pd.DataFrame([row for rows in self.contacts.values() for row in rows])
        self.master.claimant_policy = pd.DataFrame(self.bridge)


def plan_planting(config: GeneratorConfig, rng: np.random.Generator, master: MasterTables) -> PlantingPlan:
    """Choose every planted row and apply the master-data changes. The most constrained rules choose first."""
    planner = _Planner(config, rng, master)
    planner.past_tenants()
    if planner.knobs.plant_fraud:  # False only in stress scenario S0
        planner.ring_unusual_timing()
        planner.ring_shared_contacts()
        planner.ring_repeated_narratives()
        planner.ring_provider_collusion()
        planner.ring_staged_incident()
        planner.ring_hidden_link()
    planner.orphan_policy_claims()
    if planner.knobs.plant_fraud:
        planner.duplicate_invoices()
    planner.benign_events()
    extra = {"B-ROOM-01": planner.flatmates, "B-FAMILY-02": planner.blended_families,
             "B-FLEET-01": planner.company_fleets, "B-AGENT-01": planner.boilerplate_body_shops}
    if planner.knobs.extra_benign:
        extra[planner.knobs.extra_benign]()
    planner.repeat_claimants()
    planner.shared_households()
    planner.common_addresses()
    planner.popular_providers()
    planner.apply_to_master()
    return planner.plan
