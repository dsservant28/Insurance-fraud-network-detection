"""Planted patterns and hidden labels, from docs/DATA_DICTIONARY.md sections 8 and 10.

Each pattern is checked from the exported tables, so a rule that only exists in a label fails here.
"""
import difflib
import json
from pathlib import Path

import pandas as pd
import pytest

from fraudnet.generate.config import GeneratorConfig
from fraudnet.generate.export import write_input
from fraudnet.generate.ground_truth import write_hidden
from fraudnet.generate.ids import ID_PATTERNS
from fraudnet.generate.pipeline import generate_with_labels
from fraudnet.generate.pools import STREET_SUFFIXES

RING_RULES = [f"R-RING-0{n}" for n in range(1, 7)]
BENIGN_TARGETS = {"B-HOUSE-01": 150, "B-REPEAT-01": 200, "B-ADDR-01": 10, "B-PROV-01": 10, "B-EVENT-01": 3, "B-MOVE-01": 20}
DICTIONARY = Path(__file__).parent.parent / "docs/DATA_DICTIONARY.md"
ABBREVIATIONS = {short.lower(): full.lower() for full, short in STREET_SUFFIXES.items()}


@pytest.fixture(scope="module")
def data():
    return generate_with_labels(GeneratorConfig(scale=1.0))


@pytest.fixture(scope="module")
def tables(data):
    return data[0]


@pytest.fixture(scope="module")
def labels(data):
    return data[1]


def _normal_address(row) -> str:
    words = row["address_line"].lower().split()
    words[-1] = ABBREVIATIONS.get(words[-1], words[-1])
    return f"{' '.join(words)}|{row['city']}"


def _groups(labels, rule, entity_type="CLAIMANT"):
    rows = labels[(labels["rule_id"] == rule) & (labels["entity_type"] == entity_type)]
    column = "ring_id" if rule.startswith("R-") else "group_id"
    return {name: rows_["entity_id"].tolist() for name, rows_ in rows.groupby(column)}


def _open_contacts(tables, members):
    contact = tables["claimant_contact"]
    return contact[contact["claimant_id"].isin(members) & contact["effective_to"].isna()]


def _claims_of(labels, tables, rule, name):
    column = "ring_id" if rule.startswith("R-") else "group_id"
    ids = labels[(labels[column] == name) & (labels["entity_type"] == "CLAIM")]["entity_id"]
    claim = tables["claim"]
    return claim[claim["claim_id"].isin(ids)].merge(tables["incident"], on="incident_id")


def _surname(tables, members):
    names = tables["claimant"].set_index("claimant_id").loc[members, "full_name"]
    return names.str.rsplit(" ", n=1).str[1]


def _shared_fields(contacts, members_count):
    return [field for field in ("phone", "email", "bank_token")
            if contacts[field].notna().all() and contacts[field].nunique() == 1 and len(contacts) == members_count]


# ---- counts

@pytest.mark.parametrize("scale, claims, claimants, providers, rings", [
    (0.1, 500, 200, 50, 1), (1.0, 5_000, 2_000, 500, 4), (2.0, 10_000, 4_000, 1_000, 8),
])
def test_volumes_stay_exact_with_planted_rows_included(scale, claims, claimants, providers, rings):
    tables, labels = generate_with_labels(GeneratorConfig(scale=scale))
    assert (len(tables["claim"]), len(tables["claimant"]), len(tables["provider"])) == (claims, claimants, providers)
    for rule in RING_RULES:
        assert len(_groups(labels, rule)) == rings, rule


def test_benign_groups_reach_their_targets(labels):
    for rule, target in BENIGN_TARGETS.items():
        rows = labels[labels["rule_id"] == rule]
        assert rows["group_id"].nunique() == target, rule


@pytest.mark.parametrize("seed", [1, 7, 99])
def test_other_seeds_plant_everything(seed):
    _, labels = generate_with_labels(GeneratorConfig(seed=seed, scale=1.0))
    assert labels["ring_id"].nunique() == 24
    assert set(labels["rule_id"]) == set(RING_RULES) | set(BENIGN_TARGETS)


def test_too_small_a_scale_fails_with_a_clear_message():
    with pytest.raises(ValueError, match="scale"):
        generate_with_labels(GeneratorConfig(scale=0.01))


def test_rings_have_three_to_eight_members(labels):
    for rule in RING_RULES:
        for members in _groups(labels, rule).values():
            assert 3 <= len(members) <= 8


def test_no_claimant_belongs_to_two_groups(labels):
    people = labels[labels["entity_type"] == "CLAIMANT"]
    assert people["entity_id"].is_unique


# ---- fraud rings

def test_r_ring_01_unrelated_claimants_share_contact_values(tables, labels):
    for members in _groups(labels, "R-RING-01").values():
        contacts = _open_contacts(tables, members)
        assert _shared_fields(contacts, len(members))
        assert _surname(tables, members).is_unique
        assert contacts.apply(_normal_address, axis=1).is_unique


def test_r_ring_02_narratives_are_nearly_identical_across_locations(tables, labels):
    bridge = tables["claim_provider"]
    for name in _groups(labels, "R-RING-02"):
        claims = _claims_of(labels, tables, "R-RING-02", name)
        texts = claims["narrative"].tolist()
        assert all(difflib.SequenceMatcher(None, texts[0], text).ratio() > 0.9 for text in texts)
        assert claims["city"].nunique() > 1 and claims["incident_id"].is_unique
        linked = bridge[bridge["claim_id"].isin(claims["claim_id"])]
        assert linked["provider_id"].value_counts().iloc[0] >= claims["claimant_id"].nunique()


def test_r_ring_03_claims_come_soon_after_start_in_a_tight_burst(tables, labels):
    invoice = tables["invoice"]
    for name in _groups(labels, "R-RING-03"):
        claims = _claims_of(labels, tables, "R-RING-03", name)
        assert claims["days_policy_start_to_incident"].between(0, 10).all()
        assert (claims["days_incident_to_report"] <= 1).all()
        days = pd.to_datetime(claims["incident_date"])
        assert (days.max() - days.min()).days <= 45
        billed = invoice[invoice["claim_id"].isin(claims["claim_id"])].merge(claims, on="claim_id")
        gaps = pd.to_datetime(billed["invoice_date"]) - pd.to_datetime(billed["reported_date"])
        assert (gaps.dt.days.groupby(billed["invoice_id"]).first() <= 30).all()
        assert billed["provider_id"].value_counts().iloc[0] >= claims["claimant_id"].nunique()


def test_r_ring_04_claimants_use_the_providers_bank_with_inflated_invoices(tables, labels):
    invoice = tables["invoice"].merge(tables["claim"], on="claim_id").merge(tables["incident"], on="incident_id")
    medians = invoice.groupby("incident_type")["total_cents"].median()
    providers = tables["provider"].set_index("provider_id")
    rings = _groups(labels, "R-RING-04")
    for name, members in rings.items():
        ring_provider = labels[(labels["ring_id"] == name) & (labels["entity_type"] == "PROVIDER")]["entity_id"].item()
        contacts = _open_contacts(tables, members)
        assert (contacts["bank_token"] == providers.loc[ring_provider, "bank_token"]).all()
        claims = _claims_of(labels, tables, "R-RING-04", name)
        assert claims["claimant_id"].value_counts().min() >= 1
        billed = invoice[invoice["claim_id"].isin(claims["claim_id"]) & (invoice["provider_id"] == ring_provider)]
        assert len(billed) >= len(members)
        assert billed["total_cents"].median() > 1.5 * medians[billed["incident_type"].iloc[0]]


def test_r_ring_05_several_claimants_share_one_incident_and_few_providers(tables, labels):
    bridge = tables["claim_provider"]
    for name, members in _groups(labels, "R-RING-05").items():
        claims = _claims_of(labels, tables, "R-RING-05", name)
        assert claims["incident_id"].nunique() == 1
        assert set(claims["claimant_id"]) == set(members)
        linked = bridge[bridge["claim_id"].isin(claims["claim_id"])]
        top_two = set(linked["provider_id"].value_counts().index[:2])
        assert linked[linked["provider_id"].isin(top_two)]["claim_id"].nunique() == len(members)
        contacts = _open_contacts(tables, members)
        assert contacts["phone"].duplicated().any() or contacts["bank_token"].dropna().duplicated().any()


def test_r_ring_06_shared_raw_values_exist_and_rows_are_edge_case_four(tables, labels):
    respelled = 0
    for members in _groups(labels, "R-RING-06").values():
        contacts = _open_contacts(tables, members)
        assert {"phone", "bank_token"} <= set(_shared_fields(contacts, len(members)))
        addresses = contacts.apply(_normal_address, axis=1)
        assert addresses.duplicated().any()
        shared = contacts[addresses.duplicated(keep=False)]
        respelled += shared["address_line"].nunique() > 1
    assert respelled >= 1
    assert set(labels[labels["rule_id"] == "R-RING-06"]["issue_type"]) == {"EC-4"}


def test_fraud_rows_are_a_small_share_of_claims(tables, labels):
    fraud = labels[(labels["is_fraud"] == 1) & (labels["entity_type"] == "CLAIM")]
    assert 0.01 < len(fraud) / len(tables["claim"]) < 0.10


# ---- benign look-alikes

def test_b_house_01_families_share_surname_and_address(tables, labels):
    bridge = tables["claimant_policy"]
    joint = shared_phone = 0
    for members in _groups(labels, "B-HOUSE-01").values():
        assert _surname(tables, members).nunique() == 1
        contacts = _open_contacts(tables, members)
        assert contacts.apply(_normal_address, axis=1).nunique() == 1
        shared_phone += contacts["phone"].nunique() == 1
        joint += bridge[bridge["claimant_id"].isin(members) & (bridge["role"] == "NAMED_INSURED")].shape[0] > 0
    assert joint > 30 and shared_phone > 30


def test_named_insured_can_claim_on_the_joint_policy(tables):
    bridge = tables["claimant_policy"]
    named = bridge[bridge["role"] == "NAMED_INSURED"]
    assert (bridge[bridge["role"] == "POLICYHOLDER"].groupby("policy_id").size() == 1).all()
    pairs = set(zip(named["claimant_id"], named["policy_id"]))
    assert any(pair in pairs for pair in zip(tables["claim"]["claimant_id"], tables["claim"]["policy_id"]))


def test_b_repeat_01_claims_are_spaced_out_and_varied(tables, labels):
    invoice = tables["invoice"]
    claims_per_person = tables["claim"]["claimant_id"].value_counts()
    all_types, all_counts = set(), []
    for name, members in _groups(labels, "B-REPEAT-01").items():
        claims = _claims_of(labels, tables, "B-REPEAT-01", name)
        days = pd.to_datetime(claims["incident_date"]).sort_values()
        assert len(claims) >= 3
        assert claims_per_person[members[0]] == len(claims)  # no extra baseline claims
        assert (days.diff().dropna().dt.days >= 45).all()
        all_types |= set(claims["incident_type"])
        all_counts.append(invoice[invoice["claim_id"].isin(claims["claim_id"])]["provider_id"].nunique())
    assert len(all_types) >= 5
    assert sum(all_counts) / len(all_counts) >= 2  # usually different providers across a claimant's claims


def test_b_addr_01_residents_are_unrelated_apart_from_the_address(tables, labels):
    for members in _groups(labels, "B-ADDR-01").values():
        assert len(members) >= 8
        contacts = _open_contacts(tables, members)
        assert contacts.apply(_normal_address, axis=1).nunique() == 1
        assert _surname(tables, members).is_unique
        for field in ("phone", "email", "bank_token"):
            assert not contacts[field].dropna().duplicated().any(), field
    assert set(labels[labels["rule_id"] == "B-ADDR-01"]["issue_type"]) == {"EC-5"}


def test_b_prov_01_popular_providers_serve_many_customers_with_no_contact_links(tables, labels):
    invoice = tables["invoice"].merge(tables["claim"][["claim_id", "claimant_id"]], on="claim_id")
    median = invoice.groupby("provider_id").size().median()
    contact = tables["claimant_contact"]
    providers = tables["provider"].set_index("provider_id")
    for provider_id in labels[labels["rule_id"] == "B-PROV-01"]["entity_id"]:
        rows = invoice[invoice["provider_id"] == provider_id]
        assert rows["claimant_id"].nunique() >= 30
        assert len(rows) > 5 * median
        assert providers.loc[provider_id, "bank_token"] not in set(contact["bank_token"].dropna())


def test_b_event_01_storm_claims_are_similar_with_no_contact_links(tables, labels):
    policy_type = tables["policy"].set_index("policy_id")["policy_type"]
    for name, members in _groups(labels, "B-EVENT-01").items():
        claims = _claims_of(labels, tables, "B-EVENT-01", name)
        assert claims["city"].nunique() == 1 and (claims["incident_type"] == "WATER_DAMAGE").all()
        assert set(policy_type[claims["policy_id"]]) == {"HOME"}
        days = pd.to_datetime(claims["incident_date"])
        assert (days.max() - days.min()).days <= 2
        texts = claims["narrative"].tolist()
        ratios = [difflib.SequenceMatcher(None, texts[0], text).ratio() for text in texts[1:]]
        assert sum(ratios) / len(ratios) > 0.6
        contacts = _open_contacts(tables, members)
        for field in ("phone", "email", "bank_token"):
            assert not contacts[field].dropna().duplicated().any(), field


def test_b_move_01_tenants_lived_at_one_address_in_separate_periods(tables, labels):
    contact = tables["claimant_contact"]
    for members in _groups(labels, "B-MOVE-01").values():
        rows = contact[contact["claimant_id"].isin(members)]
        same = rows[rows.apply(_normal_address, axis=1).duplicated(keep=False)].sort_values("effective_from")
        assert same["claimant_id"].nunique() == 2 and len(same) == 2
        assert same.iloc[0]["effective_to"] < same.iloc[1]["effective_from"]


# ---- every link in the data must trace back to a rule

def _group_of(labels):
    people = labels[labels["entity_type"] == "CLAIMANT"]
    return dict(zip(people["entity_id"], people["ring_id"].fillna(people["group_id"])))


@pytest.mark.parametrize("field", ["phone", "email", "bank_token"])
def test_every_shared_contact_value_comes_from_one_labelled_group(tables, labels, field):
    group_of = _group_of(labels)
    people = tables["claimant_contact"][["claimant_id", field]].dropna().drop_duplicates()
    shared = people[people[field].duplicated(keep=False)]
    assert not shared.empty
    for _, rows in shared.groupby(field):
        assert len({group_of.get(claimant) for claimant in rows["claimant_id"]} - {None}) == 1
        assert all(claimant in group_of for claimant in rows["claimant_id"])


def test_every_shared_address_comes_from_one_labelled_group(tables, labels):
    group_of = _group_of(labels)
    contact = tables["claimant_contact"].assign(address=lambda t: t.apply(_normal_address, axis=1))
    people = contact[["claimant_id", "address"]].drop_duplicates()
    for _, rows in people[people["address"].duplicated(keep=False)].groupby("address"):
        groups = [group_of.get(claimant) for claimant in rows["claimant_id"]]
        assert None not in groups and len(set(groups)) == 1


def test_only_collusion_rings_share_a_bank_with_a_provider(tables, labels):
    allowed = set(labels[(labels["rule_id"] == "R-RING-04") & (labels["entity_type"] == "CLAIMANT")]["entity_id"])
    contact = tables["claimant_contact"]
    linked = contact[contact["bank_token"].isin(set(tables["provider"]["bank_token"]))]
    assert set(linked["claimant_id"]) == allowed


# ---- labels

def test_every_label_is_complete_and_from_a_documented_rule(labels):
    text = DICTIONARY.read_text(encoding="utf-8")
    assert labels["label_id"].is_unique
    assert labels["label_id"].map(lambda value: bool(ID_PATTERNS["label"].match(value))).all()
    assert all(rule in text for rule in labels["rule_id"].unique())
    assert (labels["reason"].str.len() > 0).all()
    fraud = labels["rule_id"].str.startswith("R-")
    assert (labels["is_fraud"] == fraud.astype(int)).all()
    assert (labels.loc[fraud, "expected_decision"] == "INVESTIGATE").all()
    assert (labels.loc[~fraud, "expected_decision"] == "CLEAR").all()
    assert labels.loc[fraud, "ring_id"].notna().all() and labels.loc[~fraud, "group_id"].notna().all()


def test_labels_refer_to_rows_that_exist_and_reasons_name_them(tables, labels):
    sources = {"CLAIMANT": ("claimant", "claimant_id"), "PROVIDER": ("provider", "provider_id"), "CLAIM": ("claim", "claim_id")}
    for entity_type, (table, column) in sources.items():
        rows = labels[labels["entity_type"] == entity_type]
        assert set(rows["entity_id"]) <= set(tables[table][column]), entity_type
    people = labels[labels["entity_type"].isin({"CLAIMANT", "PROVIDER"})]
    assert all(entity in reason for entity, reason in zip(people["entity_id"], people["reason"]))
    assert "{" not in "".join(labels["reason"])


# ---- no leakage

def test_input_tables_have_no_label_or_internal_columns(tables):
    forbidden = {"ground_truth", "is_fraud", "ring_id", "group_id", "planted", "issue_type", "household_id", "rule_id"}
    for name, table in tables.items():
        assert not forbidden & set(table.columns), name
        assert not [column for column in table.columns if column.startswith("plan_")], name


def test_fraud_rows_are_spread_across_ids_and_row_order(tables, labels):
    fraud_claims = set(labels[(labels["is_fraud"] == 1) & (labels["entity_type"] == "CLAIM")]["entity_id"])
    position = tables["claim"]["claim_id"].isin(fraud_claims).to_numpy().nonzero()[0] / len(tables["claim"])
    assert 0.35 < position.mean() < 0.65
    assert position.min() < 0.2 and position.max() > 0.8
    fraud_people = set(labels[(labels["is_fraud"] == 1) & (labels["entity_type"] == "CLAIMANT")]["entity_id"])
    position = tables["claimant"]["claimant_id"].isin(fraud_people).to_numpy().nonzero()[0] / len(tables["claimant"])
    assert 0.35 < position.mean() < 0.65


def test_fraud_rows_use_ordinary_values(tables, labels):
    """Planted rows must come from the same value sources, so format alone gives nothing away."""
    fraud_people = set(labels[(labels["is_fraud"] == 1) & (labels["entity_type"] == "CLAIMANT")]["entity_id"])
    contact = tables["claimant_contact"]
    planted, normal = contact[contact["claimant_id"].isin(fraud_people)], contact[~contact["claimant_id"].isin(fraud_people)]
    domain = lambda rows: set(rows["email"].str.rsplit("@", n=1).str[1])
    assert domain(planted) <= domain(normal)
    surnames = tables["claimant"]["full_name"].str.rsplit(" ", n=1).str[1]
    is_fraud = tables["claimant"]["claimant_id"].isin(fraud_people)
    assert set(surnames[is_fraud]) <= set(surnames[~is_fraud])
    fraud_claims = set(labels[(labels["is_fraud"] == 1) & (labels["entity_type"] == "CLAIM")]["entity_id"])
    joined = tables["claim"].merge(tables["incident"], on="incident_id")
    is_planted = joined["claim_id"].isin(fraud_claims)
    assert joined.loc[is_planted, "narrative"].str.contains("It happened close to").all()
    assert set(joined.loc[is_planted, "city"]) <= set(joined.loc[~is_planted, "city"])


def test_hidden_files_are_separate_and_input_never_mentions_them(data, tmp_path):
    tables, labels = data
    write_input(tables, tmp_path)
    write_hidden(labels, tmp_path)
    assert {path.name for path in (tmp_path / "hidden").iterdir()} == {
        "ground_truth.csv", "ground_truth.json", "hidden_manifest.json"}
    manifest = (tmp_path / "input/input_manifest.json").read_text(encoding="utf-8")
    assert "ground_truth" not in manifest and "hidden" not in manifest
    for path in (tmp_path / "input").rglob("*"):
        if path.is_file():
            assert path.parent.name != "hidden"
    schema_and_header = (tmp_path / "input/sql/schema.sql").read_text(encoding="utf-8").lower()
    assert "ring_id" not in schema_and_header and "is_fraud" not in schema_and_header
    records = json.loads((tmp_path / "hidden/ground_truth.json").read_text(encoding="utf-8"))
    assert len(records) == len(labels)
    assert pd.read_csv(tmp_path / "hidden/ground_truth.csv").shape[0] == len(labels)


def test_same_seed_gives_identical_hidden_files(tmp_path):
    for folder in ("a", "b"):
        write_hidden(generate_with_labels(GeneratorConfig(scale=0.1))[1], tmp_path / folder)
    for name in ("ground_truth.csv", "ground_truth.json", "hidden_manifest.json"):
        assert (tmp_path / "a/hidden" / name).read_bytes() == (tmp_path / "b/hidden" / name).read_bytes()


def test_different_seed_plants_different_groups():
    first = generate_with_labels(GeneratorConfig(seed=1, scale=0.1))[1]
    second = generate_with_labels(GeneratorConfig(seed=2, scale=0.1))[1]
    assert set(first["entity_id"]) != set(second["entity_id"])
