"""Baseline master data: claimants, contacts, providers, policies and policy events.

Rows use temporary integer keys here. Final IDs are assigned by finalize.py after all
planting is done, so an ID can never reveal how or when a row was created.

Baseline phones, emails, bank tokens and addresses are all unique. Any shared value in
the final data must therefore come from a documented planting rule.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from fraudnet.generate.config import AS_OF_DATE, GeneratorConfig
from fraudnet.generate import pools

CUSTOMER_SINCE_EARLIEST = date(2012, 1, 1)
CUSTOMER_SINCE_LATEST = date(2025, 1, 31)
POLICY_START_EARLIEST = date(2025, 2, 1)
POLICY_START_LATEST = date(2026, 8, 31)
PROVIDER_START_EARLIEST = date(2010, 1, 1)
PROVIDER_START_LATEST = date(2025, 6, 30)
PROVIDER_END_EARLIEST = date(2026, 3, 1)

# (limit options in dollars, deductible options in dollars, selection probability)
POLICY_TERMS = {
    "AUTO": ((25_000, 50_000, 100_000), (250, 500, 1_000), 0.60),
    "HOME": ((100_000, 250_000, 500_000), (1_000, 2_500), 0.25),
    "HEALTH": ((50_000, 100_000, 250_000), (250, 500, 1_000), 0.15),
}
OPS_ANALYST_IDS = tuple(f"USR-OPS-{n:03d}" for n in range(1, 11))


@dataclass
class MasterTables:
    claimant: pd.DataFrame
    claimant_contact: pd.DataFrame
    provider: pd.DataFrame
    policy: pd.DataFrame
    claimant_policy: pd.DataFrame
    policy_events: pd.DataFrame


def _pick(rng: np.random.Generator, options) -> str:
    return options[int(rng.integers(len(options)))]


def _random_date(rng: np.random.Generator, start: date, end: date) -> date:
    return start + timedelta(days=int(rng.integers((end - start).days + 1)))


def _add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 29 February
        return day.replace(year=day.year + years, day=28)


def _timestamp(rng: np.random.Generator, day: date) -> str:
    return f"{day.isoformat()}T{int(rng.integers(8, 18)):02d}:{int(rng.integers(60)):02d}:{int(rng.integers(60)):02d}Z"


class _UniqueValues:
    """Hands out globally unique fictional contact values."""

    def __init__(self, rng: np.random.Generator, size: int) -> None:
        self._rng = rng
        self._phones = iter(rng.choice(10_000_000, size=size, replace=False).tolist())
        self._banks = iter(rng.choice(100_000_000, size=size, replace=False).tolist())
        self._email_numbers = iter(rng.choice(1_000_000, size=size, replace=False).tolist())
        space = 9_999 * len(pools.STREET_NAMES) * len(pools.CITIES)
        self._addresses = iter(rng.choice(space, size=size, replace=False).tolist())

    def phone(self) -> str:
        digits = f"{next(self._phones):07d}"
        return f"555-{digits[:3]}-{digits[3:]}"

    def bank_token(self) -> str:
        return f"ACCT-{next(self._banks):08d}"

    def email(self, local_part: str) -> str:
        return f"{local_part}.{next(self._email_numbers):06d}@{_pick(self._rng, pools.EMAIL_DOMAINS)}"

    def address(self) -> dict[str, str]:
        index = next(self._addresses)
        index, house = divmod(index, 9_999)
        city_index, street_index = divmod(index, len(pools.STREET_NAMES))
        canonical = _pick(self._rng, tuple(pools.STREET_SUFFIXES))
        suffix = canonical if self._rng.random() < 0.5 else pools.STREET_SUFFIXES[canonical]
        line = f"{house + 1} {pools.STREET_NAMES[street_index]} {suffix}"
        if self._rng.random() < 0.05:
            line = line.upper()
        return {
            "address_line": line,
            "city": pools.CITIES[city_index],
            "postal_code": f"00{city_index * 10 + street_index % 10:03d}",
        }


def _build_claimants(rng: np.random.Generator, count: int) -> list[dict]:
    rows = []
    for key in range(count):
        age = int(np.clip(round(rng.normal(46, 15)), 21, 90))
        birth_latest = _add_years(AS_OF_DATE, -age)
        birth = birth_latest - timedelta(days=int(rng.integers(365)))
        earliest = max(CUSTOMER_SINCE_EARLIEST, _add_years(birth, 18))
        rows.append({
            "claimant_key": key,
            "first_name": _pick(rng, pools.FIRST_NAMES),
            "last_name": _pick(rng, pools.LAST_NAMES),
            "date_of_birth": birth,
            "customer_since": _random_date(rng, earliest, CUSTOMER_SINCE_LATEST),
        })
    return rows


def _build_contacts(rng: np.random.Generator, claimants: list[dict], moves: list[int],
                    values: _UniqueValues) -> list[dict]:
    rows = []
    for claimant, move_count in zip(claimants, moves):
        since = claimant["customer_since"]
        local_part = f"{claimant['first_name']}.{claimant['last_name']}".lower()
        phone = values.phone()
        email = values.email(local_part)
        bank = values.bank_token() if rng.random() >= 0.15 else None

        window = (AS_OF_DATE - since).days - 30
        offsets = np.sort(rng.choice(window, size=move_count, replace=False)).tolist() if move_count else []
        starts = [since] + [since + timedelta(days=30 + offset) for offset in offsets]

        for position, start in enumerate(starts):
            if position > 0 and rng.random() < 0.3:
                phone = values.phone()
            is_last = position == len(starts) - 1
            rows.append({
                "claimant_key": claimant["claimant_key"],
                "effective_from": start,
                "effective_to": None if is_last else starts[position + 1] - timedelta(days=1),
                **values.address(),
                "phone": phone,
                "email": email,
                "bank_token": bank,
            })
    return rows


def _build_providers(rng: np.random.Generator, count: int, values: _UniqueValues) -> list[dict]:
    types = ("REPAIRER", "MEDICAL", "SERVICE")
    rows = []
    for key in range(count):
        provider_type = str(rng.choice(types, p=(0.45, 0.35, 0.20)))
        name = f"{_pick(rng, pools.PROVIDER_NAME_WORDS)} {_pick(rng, pools.PROVIDER_NAME_SUFFIXES[provider_type])}"
        active_from = _random_date(rng, PROVIDER_START_EARLIEST, PROVIDER_START_LATEST)
        closed = rng.random() < 0.05
        rows.append({
            "provider_key": key,
            "provider_name": name,
            "provider_type": provider_type,
            **values.address(),
            "phone": values.phone(),
            "email": values.email("billing"),
            "bank_token": values.bank_token(),
            "active_from": active_from,
            "active_to": _random_date(rng, PROVIDER_END_EARLIEST, AS_OF_DATE) if closed else None,
        })
    return rows


def _build_policies(rng: np.random.Generator, count: int) -> list[dict]:
    types = tuple(POLICY_TERMS)
    probabilities = [POLICY_TERMS[t][2] for t in types]
    rows = []
    for key in range(count):
        policy_type = str(rng.choice(types, p=probabilities))
        limits, deductibles, _ = POLICY_TERMS[policy_type]
        start = _random_date(rng, POLICY_START_EARLIEST, POLICY_START_LATEST)
        rows.append({
            "policy_key": key,
            "policy_type": policy_type,
            "effective_from": start,
            "effective_to": _add_years(start, 1) - timedelta(days=1),
            "coverage_limit_cents": int(rng.choice(limits)) * 100,
            "deductible_cents": int(rng.choice(deductibles)) * 100,
        })
    return rows


def _build_holders(rng: np.random.Generator, policies: list[dict], claimant_count: int) -> list[dict]:
    """Give every claimant one policy, then spread the remaining policies across claimants."""
    order = rng.permutation(len(policies)).tolist()
    holders = list(range(claimant_count))
    holders += rng.integers(claimant_count, size=len(policies) - claimant_count).tolist()
    rows = []
    for policy_index, claimant_key in zip(order, holders):
        policy = policies[policy_index]
        rows.append({
            "claimant_key": int(claimant_key),
            "policy_key": policy["policy_key"],
            "role": "POLICYHOLDER",
            "effective_from": policy["effective_from"],
            "effective_to": policy["effective_to"],
        })
    return rows


def _policy_event(key: int, seq: int, previous: str | None, status: str, at: str, role: str,
                  actor_id: str | None = None, reason: str | None = None) -> dict:
    return {
        "policy_key": key,
        "seq": seq,
        "from_status": previous,
        "to_status": status,
        "event_at": at,
        "actor_role": role,
        "actor_id": actor_id,
        "reason_code": reason,
    }


def _build_policy_events(rng: np.random.Generator, policies: list[dict]) -> list[dict]:
    """Every status change is its own row. Current status is derived from the last row."""
    rows = []
    for policy in policies:
        key, start, end = policy["policy_key"], policy["effective_from"], policy["effective_to"]
        last_day = min(end, AS_OF_DATE)
        events = [_policy_event(key, 1, None, "ACTIVE", _timestamp(rng, start), "SYSTEM")]
        status = "ACTIVE"
        draw = rng.random()
        change_day = _random_date(rng, start + timedelta(days=30), last_day)

        if draw < 0.06:
            by_customer = rng.random() < 0.7
            events.append(_policy_event(
                key, 2, status, "CANCELLED", _timestamp(rng, change_day),
                "CUSTOMER" if by_customer else "SYSTEM",
                reason="CUSTOMER_REQUEST" if by_customer else "NON_PAYMENT",
            ))
            status = "CANCELLED"
        elif draw < 0.12:
            events.append(_policy_event(key, 2, status, "LAPSED", _timestamp(rng, change_day), "SYSTEM",
                                        reason="NON_PAYMENT"))
            status = "LAPSED"
            if change_day < last_day and rng.random() < 0.4:
                latest = min(last_day, change_day + timedelta(days=45))
                back_on = _random_date(rng, change_day + timedelta(days=1), latest)
                events.append(_policy_event(key, 3, status, "ACTIVE", _timestamp(rng, back_on), "OPS_ANALYST",
                                            actor_id=_pick(rng, OPS_ANALYST_IDS), reason="REINSTATED"))
                status = "ACTIVE"

        expiry_day = end + timedelta(days=1)
        if status == "ACTIVE" and expiry_day <= AS_OF_DATE:
            events.append(_policy_event(key, len(events) + 1, status, "EXPIRED", _timestamp(rng, expiry_day),
                                        "SYSTEM", reason="TERM_ENDED"))
        rows.extend(events)
    return rows


def build_master(config: GeneratorConfig, rng: np.random.Generator) -> MasterTables:
    """Build master tables. Parents are always created before the rows that refer to them."""
    claimant_count = config.count("claimant")
    provider_count = config.count("provider")
    policy_count = config.count("policy")

    claimants = _build_claimants(rng, claimant_count)
    moves = rng.choice((0, 1, 2), size=claimant_count, p=(0.88, 0.10, 0.02)).tolist()
    values = _UniqueValues(rng, claimant_count + sum(moves) + provider_count)
    contacts = _build_contacts(rng, claimants, moves, values)
    providers = _build_providers(rng, provider_count, values)
    policies = _build_policies(rng, policy_count)
    holders = _build_holders(rng, policies, claimant_count)
    policy_events = _build_policy_events(rng, policies)

    claimant_rows = [{
        "claimant_key": row["claimant_key"],
        "full_name": f"{row['first_name']} {row['last_name']}",
        "date_of_birth": row["date_of_birth"],
        "customer_since": row["customer_since"],
    } for row in claimants]

    return MasterTables(
        claimant=pd.DataFrame(claimant_rows),
        claimant_contact=pd.DataFrame(contacts),
        provider=pd.DataFrame(providers),
        policy=pd.DataFrame(policies),
        claimant_policy=pd.DataFrame(holders),
        policy_events=pd.DataFrame(policy_events),
    )
