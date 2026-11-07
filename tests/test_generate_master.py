"""Master data rules from docs/DATA_DICTIONARY.md sections 3, 4 and 6."""
import re

import pandas as pd
import pytest

from fraudnet.generate.config import AS_OF_DATE, GeneratorConfig
from fraudnet.generate.export import write_input
from fraudnet.generate.ids import ID_PATTERNS
from fraudnet.generate.pipeline import generate
from fraudnet.generate.pools import STREET_SUFFIXES

POLICY_TRANSITIONS = {
    (None, "ACTIVE"),
    ("ACTIVE", "LAPSED"),
    ("ACTIVE", "CANCELLED"),
    ("ACTIVE", "EXPIRED"),
    ("LAPSED", "ACTIVE"),
}
AS_OF = AS_OF_DATE.isoformat()


def _blank_to_none(value):
    return None if pd.isna(value) else value


@pytest.fixture(scope="module")
def tables():
    return generate(GeneratorConfig(scale=1.0))


@pytest.mark.parametrize("table, count", [("claimant", 2_000), ("provider", 500), ("policy", 2_600)])
def test_baseline_counts_are_exact(tables, table, count):
    assert len(tables[table]) == count


@pytest.mark.parametrize("table, column, entity", [
    ("claimant", "claimant_id", "claimant"),
    ("claimant_contact", "contact_id", "contact"),
    ("provider", "provider_id", "provider"),
    ("policy", "policy_id", "policy"),
    ("policy_events", "event_id", "policy_event"),
])
def test_primary_keys_are_unique_and_well_formed(tables, table, column, entity):
    values = tables[table][column]
    assert values.is_unique
    assert values.map(lambda v: bool(ID_PATTERNS[entity].match(v))).all()


def test_foreign_keys_resolve(tables):
    claimants = set(tables["claimant"]["claimant_id"])
    policies = set(tables["policy"]["policy_id"])
    assert set(tables["claimant_contact"]["claimant_id"]) == claimants
    assert set(tables["claimant_policy"]["claimant_id"]) == claimants
    assert set(tables["claimant_policy"]["policy_id"]) == policies
    assert set(tables["policy_events"]["policy_id"]) == policies


def test_every_policy_has_exactly_one_holder(tables):
    bridge = tables["claimant_policy"]
    assert not bridge.duplicated(["claimant_id", "policy_id"]).any()
    assert (bridge[bridge["role"] == "POLICYHOLDER"].groupby("policy_id").size() == 1).all()


def test_contact_periods_never_overlap_and_one_stays_open(tables):
    for _, rows in tables["claimant_contact"].groupby("claimant_id"):
        rows = rows.sort_values("effective_from")
        assert rows["effective_to"].isna().sum() == 1
        assert pd.isna(rows.iloc[-1]["effective_to"])
        closed_until = rows["effective_to"].iloc[:-1].tolist()
        next_starts = rows["effective_from"].iloc[1:].tolist()
        assert all(end < start for end, start in zip(closed_until, next_starts))


def test_baseline_contact_values_are_not_shared_between_people(tables):
    """A shared value must come from a documented planting rule, never by accident."""
    contact = tables["claimant_contact"]
    provider = tables["provider"]
    for field in ("phone", "email", "bank_token"):
        people = contact[["claimant_id", field]].dropna().drop_duplicates()
        assert people[field].is_unique, field
        assert not set(people[field]) & set(provider[field]), field
    assert provider["phone"].is_unique and provider["bank_token"].is_unique


def test_baseline_addresses_are_unique_after_normalising(tables):
    abbreviations = {short.lower(): full.lower() for full, short in STREET_SUFFIXES.items()}

    def normal(row):
        words = row["address_line"].lower().split()
        words[-1] = abbreviations.get(words[-1], words[-1])
        return " ".join(words) + "|" + row["city"]

    addresses = [normal(row) for _, row in tables["claimant_contact"].iterrows()]
    addresses += [normal(row) for _, row in tables["provider"].iterrows()]
    assert len(addresses) == len(set(addresses))


def test_contact_values_are_clearly_fictional(tables):
    for table in ("claimant_contact", "provider"):
        assert tables[table]["phone"].map(lambda v: bool(re.fullmatch(r"555-\d{3}-\d{4}", v))).all()
        assert tables[table]["email"].map(lambda v: v.rsplit("@", 1)[1] in
                                          {"example.com", "example.org", "example.net"}).all()
        assert tables[table]["bank_token"].dropna().map(lambda v: bool(re.fullmatch(r"ACCT-\d{8}", v))).all()


def test_claimant_dates_are_ordered(tables):
    claimant = tables["claimant"]
    assert (claimant["date_of_birth"] < claimant["customer_since"]).all()
    assert (claimant["customer_since"] <= AS_OF).all()
    years = claimant["date_of_birth"].str[:4].astype(int)
    assert (2026 - years).between(18, 96).all()


def test_policy_terms_are_valid(tables):
    policy = tables["policy"]
    assert policy["policy_type"].isin({"AUTO", "HOME", "HEALTH"}).all()
    assert (policy["effective_from"] < policy["effective_to"]).all()
    assert (policy["effective_from"] <= AS_OF).all()
    assert (policy["coverage_limit_cents"] > policy["deductible_cents"]).all()
    assert (policy["deductible_cents"] >= 0).all()


def test_policy_starts_after_holder_became_customer(tables):
    joined = tables["claimant_policy"].merge(tables["claimant"], on="claimant_id")
    assert (joined["customer_since"] <= joined["effective_from"]).all()


def test_policy_events_follow_lifecycle(tables):
    previous_time = {}
    for _, rows in tables["policy_events"].groupby("policy_id"):
        rows = rows.sort_values("seq")
        assert rows["seq"].tolist() == list(range(1, len(rows) + 1))
        last = None
        for _, event in rows.iterrows():
            assert (_blank_to_none(event["from_status"]), event["to_status"]) in POLICY_TRANSITIONS
            assert _blank_to_none(event["from_status"]) == last
            last = event["to_status"]
        assert rows["event_at"].is_monotonic_increasing
        previous_time[rows.iloc[0]["policy_id"]] = rows.iloc[-1]["event_at"]
    assert max(previous_time.values())[:10] <= AS_OF


def test_current_status_is_derived_from_latest_event(tables):
    latest = tables["policy_events"].sort_values(["policy_id", "seq"]).groupby("policy_id")["to_status"].last()
    assert tables["policy"].set_index("policy_id")["current_status"].equals(latest.reindex(tables["policy"]["policy_id"]))


def test_expired_only_after_term_end(tables):
    events = tables["policy_events"].merge(tables["policy"], on="policy_id")
    expired = events[events["to_status"] == "EXPIRED"]
    assert (expired["event_at"].str[:10] > expired["effective_to"]).all()
    assert not expired.empty


def test_data_varies_realistically(tables):
    policy = tables["policy"]
    assert policy["policy_type"].nunique() == 3
    assert policy["current_status"].nunique() >= 3
    assert tables["claimant_contact"].groupby("claimant_id").size().max() >= 2
    assert tables["provider"]["provider_type"].nunique() == 3


def test_input_has_no_label_columns(tables):
    forbidden = {"ground_truth", "is_fraud", "ring_id", "planted", "issue_type", "household_id"}
    for table in tables.values():
        assert not forbidden & set(table.columns)


def test_temporary_keys_do_not_reach_output(tables):
    for table in tables.values():
        assert not [column for column in table.columns if column.endswith("_key")]


def test_same_seed_gives_identical_files(tmp_path):
    first = write_input(generate(GeneratorConfig(scale=0.1)), tmp_path / "a")
    second = write_input(generate(GeneratorConfig(scale=0.1)), tmp_path / "b")
    assert first == second
    for item in first["files"]:
        assert (tmp_path / "a" / "input" / item["path"]).read_bytes() == \
               (tmp_path / "b" / "input" / item["path"]).read_bytes()
    assert (tmp_path / "a/input/input_manifest.json").read_bytes() == \
           (tmp_path / "b/input/input_manifest.json").read_bytes()


def test_different_seed_gives_different_data():
    first = generate(GeneratorConfig(seed=1, scale=0.1))["claimant"]
    second = generate(GeneratorConfig(seed=2, scale=0.1))["claimant"]
    assert not first.equals(second)


def test_files_use_lf_line_endings(tmp_path):
    write_input(generate(GeneratorConfig(scale=0.1)), tmp_path)
    assert b"\r" not in (tmp_path / "input/csv/claimant.csv").read_bytes()


@pytest.mark.parametrize("scale", [0.1, 2.0])
def test_other_scales_keep_counts_and_links(scale):
    config = GeneratorConfig(scale=scale)
    tables = generate(config)
    assert len(tables["claimant"]) == config.count("claimant")
    assert len(tables["provider"]) == config.count("provider")
    assert set(tables["claimant_policy"]["claimant_id"]) == set(tables["claimant"]["claimant_id"])
