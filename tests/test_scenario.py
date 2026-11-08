"""Stress scenarios in the generator (docs/STRESS_PLAN.md section 4)."""
import re
from functools import lru_cache

import numpy as np
import pandas as pd
import pytest

from fraudnet.detect.normalise import address_key, bank_key, email_key, phone_key
from fraudnet.generate.config import GeneratorConfig
from fraudnet.generate.pipeline import generate_with_labels
from fraudnet.generate.scenario import (
    LEVELS, PLACEHOLDERS, PlantKnobs, Scenario, _cosmetic, _typo, _uncovered, reword, sharers,
)

SEED = 42  # not a stress seed: these tests never run the detector


@lru_cache(maxsize=None)
def world(name=None, level=None, scale=0.1):
    scenario = Scenario(name, level) if name else None
    return generate_with_labels(GeneratorConfig(seed=SEED, scale=scale, scenario=scenario))


def _same(a, b):
    return set(a[0]) == set(b[0]) and all(a[0][name].equals(b[0][name]) for name in a[0]) and a[1].equals(b[1])


def _ring_sizes(labels):
    rings = labels[(labels["label_kind"] == "FRAUD_RING") & (labels["entity_type"] == "CLAIMANT")]
    return rings.groupby("ring_id")["entity_id"].nunique()


@pytest.mark.parametrize("name", ["S1a", "S1b", "S1c", "S2", "S5a", "S5b", "S5c"])
def test_strength_zero_is_the_normal_world(name):
    assert _same(world(name, 0.0), world())


def test_unknown_scenarios_and_levels_are_refused():
    for name, level in (("S9", 0.5), ("S1a", 1.5), ("S3c", "x9")):
        with pytest.raises(ValueError):
            Scenario(name, level)
    assert set(LEVELS) == {"S0", "S1a", "S1b", "S1c", "S2", "S3a", "S3b", "S3c", "S4a", "S4b", "S4c", "S4d",
                           "S5a", "S5b", "S5c"}


def test_scenarios_are_deterministic():
    first = generate_with_labels(GeneratorConfig(seed=SEED, scale=0.1, scenario=Scenario("S1b", 0.5)))
    assert _same(first, world("S1b", 0.5))


def test_a_stronger_level_changes_a_superset_of_cells():
    base = world()[0]["claimant_contact"]
    def changed(level):
        contact = world("S1c", level)[0]["claimant_contact"]
        return {(row, column) for column in ("phone", "email", "bank_token", "address_line")
                for row in np.flatnonzero((contact[column] != base[column]) & base[column].notna())}
    weak, strong = changed(0.25), changed(0.75)
    assert weak and weak < strong


# The detector's v0.1 matching rules, kept here because S1b was defined against them (STRESS_PLAN.md).
V01_RULES = {"phone": lambda v: re.sub(r"\D", "", v), "email": lambda v: v.strip().lower(),
             "bank_token": lambda v: v.strip().upper(), "postal_code": lambda v: v.strip()}


def test_cosmetic_forms_keep_detector_keys_and_uncovered_forms_beat_the_v01_rules():
    rng = np.random.default_rng(1)
    samples = {"phone": "555-123-4567", "email": "ann.lee.000123@example.com", "bank_token": "ACCT-00012345",
               "postal_code": "00123"}
    for _ in range(50):
        assert phone_key(_cosmetic(rng, "phone", "555-123-4567")) == phone_key("555-123-4567")
        assert email_key(_cosmetic(rng, "email", "ann.lee.000123@example.com")) == email_key("ann.lee.000123@example.com")
        assert bank_key(_cosmetic(rng, "bank_token", "ACCT-00012345")) == bank_key("ACCT-00012345")
        assert (address_key(_cosmetic(rng, "address_line", "12 Oak St"), "Oakmere", "00123")
                == address_key("12 Oak Street", "Oakmere", "00123"))
        for field, value in samples.items():
            changed = _uncovered(rng, field, value)
            assert V01_RULES[field](changed) != V01_RULES[field](value)
    assert _uncovered(rng, "postal_code", "00123").startswith("00123-")


def test_a_typo_changes_exactly_one_character():
    rng = np.random.default_rng(2)
    for field, value in (("phone", "555-123-4567"), ("email", "ann.lee.000123@example.com"),
                         ("bank_token", "ACCT-00012345"), ("address_line", "12 Oak St")):
        for _ in range(30):
            typo = _typo(rng, field, value)
            assert len(typo) == len(value) and sum(a != b for a, b in zip(typo, value)) == 1
    assert _typo(rng, "address_line", "12 Oak St").endswith(" St")  # the suffix is left alone


def test_rewording_swaps_the_requested_number_of_words():
    text = "Another vehicle struck my car at the junction in the morning; the front bumper was damaged."
    rng = np.random.default_rng(3)
    assert reword(rng, text, 0) == text
    changed = reword(rng, text, 3)
    assert sum(a != b for a, b in zip(changed.split(" "), text.split(" "))) == 3


def test_camouflage_shares_values_with_fewer_members():
    keys = list(range(8))
    assert sharers(keys, PlantKnobs()) == keys and sharers(keys, PlantKnobs(), 4) == keys[:4]
    assert sharers(keys, PlantKnobs(share_fraction=0.4)) == keys[:4]
    assert sharers([1, 2, 3], PlantKnobs(share_fraction=0.4)) == [1, 2]  # never fewer than two


def test_camouflaged_rings_share_less():
    """In R-RING-06 every member normally holds the ring's bank account; camouflaged, at most 40% (min 2) do."""
    def largest_share(tables, labels):
        rings = labels[(labels["rule_id"] == "R-RING-06") & (labels["entity_type"] == "CLAIMANT")]
        contact = tables["claimant_contact"]
        result = []
        for _, ring in rings.groupby("ring_id"):
            members = contact[contact["claimant_id"].isin(ring["entity_id"])]
            result.append((len(ring), members.groupby("bank_token")["claimant_id"].nunique().max()))
        return result
    assert all(held == size for size, held in largest_share(*world(None, None, 1.0)))
    assert all(held <= max(2, -(-size * 4 // 10)) for size, held in largest_share(*world("S2", 1.0, 1.0)))


def test_ring_size_levels():
    assert set(_ring_sizes(world("S3a", "pairs", 1.0)[1])) == {2}
    sizes = _ring_sizes(world("S3b", "large", 1.0)[1])
    assert sizes.min() >= 15 and sizes.max() <= 25
    assert len(_ring_sizes(world("S3c", "x2", 1.0)[1])) == 2 * len(_ring_sizes(world(None, None, 1.0)[1]))


def test_no_fraud_world_has_no_rings_or_duplicate_invoices():
    labels = world("S0", "no fraud")[1]
    assert not (labels["is_fraud"] == 1).any() and not labels["rule_id"].isin(["EC-3"]).any()
    assert labels["rule_id"].isin(["EC-1", "B-HOUSE-01"]).any()


@pytest.mark.parametrize("name, rule", [("S4a", "B-ROOM-01"), ("S4b", "B-FAMILY-02"), ("S4c", "B-FLEET-01"),
                                        ("S4d", "B-AGENT-01")])
def test_unseen_innocent_groups_are_labelled_benign_with_reasons(name, rule):
    tables, labels = world(name, rule, 1.0)
    rows = labels[labels["rule_id"] == rule]
    assert len(rows) and (rows["is_fraud"] == 0).all() and (rows["label_kind"] == "BENIGN_LOOKALIKE").all()
    assert rows["reason"].str.len().min() > 20 and not rows["reason"].str.contains("{").any()
    groups = rows[rows["entity_type"] == "CLAIMANT"].groupby("group_id")["entity_id"].apply(set)
    contact = tables["claimant_contact"]
    if rule == "B-FLEET-01":
        assert all(contact[contact["claimant_id"].isin(group)]["bank_token"].nunique() == 1 for group in groups)
    if rule == "B-AGENT-01":
        claims = tables["claim"].merge(tables["incident"], on="incident_id")
        for group in groups:
            texts = claims[claims["claimant_id"].isin(group)].groupby("claimant_id")["narrative"].apply(set)
            assert len(texts) == len(group) and set.intersection(*texts)  # every customer has the shop's text


def test_register_gaps_drop_only_claimant_pair_rows():
    normal, gaps = world()[0]["relationship_edge"], world("S5a", 1.0)[0]["relationship_edge"]
    assert not gaps["edge_type"].isin(["SHARED_ADDRESS", "SHARED_PHONE", "SHARED_EMAIL", "SHARED_BANK"]).any()
    other = normal[~normal["edge_type"].str.startswith("SHARED_")]
    assert len(gaps) == len(other) + (gaps["edge_type"] == "SHARED_CONTACT_PROVIDER").sum()


def test_missing_banks_and_placeholder_narratives():
    contact = world("S5b", 1.0)[0]["claimant_contact"]
    assert contact["bank_token"].isna().all()
    narratives = world("S5c", 0.5)[0]["incident"]["narrative"]
    share = narratives.isin(PLACEHOLDERS).mean()
    assert 0.4 < share < 0.6 and world("S5c", 1.0)[0]["incident"]["narrative"].isin(PLACEHOLDERS).all()


def test_messy_identifiers_appear_only_in_claimant_contacts():
    tables = world("S1b", 1.0)[0]
    assert tables["claimant_contact"]["phone"].str.match(r"^(\+1 |001 )").all()
    assert tables["provider"].equals(world()[0]["provider"])
    assert pd.Series(tables["claimant_contact"]["postal_code"]).str.contains("-").all()
