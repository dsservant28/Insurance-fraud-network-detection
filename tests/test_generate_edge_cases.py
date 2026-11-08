"""Edge cases EC-1 to EC-5, the recorded relationship graph and exception checks.

Rules: docs/DATA_DICTIONARY.md sections 3.8, 5.3, 8.3 and 11.2. Expected links are recalculated
here from raw contact rows instead of reusing the generator's edge code.
"""
import json
import re
from itertools import combinations

import pandas as pd
import pytest

from fraudnet.generate.config import GeneratorConfig
from fraudnet.generate.pipeline import generate_with_labels
from fraudnet.generate.pools import STREET_SUFFIXES
from fraudnet.validate.exceptions import find_exceptions

ABBREVIATIONS = {short.lower(): full.lower() for full, short in STREET_SUFFIXES.items()}
PAIR_TYPES = {"phone": "SHARED_PHONE", "email": "SHARED_EMAIL", "bank_token": "SHARED_BANK", "address": "SHARED_ADDRESS"}


@pytest.fixture(scope="module")
def data():
    return generate_with_labels(GeneratorConfig(scale=1.0))


@pytest.fixture(scope="module")
def tables(data):
    return data[0]


@pytest.fixture(scope="module")
def labels(data):
    return data[1]


def _labelled(labels, rule, entity_type):
    return set(labels[(labels["rule_id"] == rule) & (labels["entity_type"] == entity_type)]["entity_id"])


def _address(row) -> str:
    words = row["address_line"].lower().split()
    words[-1] = ABBREVIATIONS.get(words[-1], words[-1])
    return f"{' '.join(words)}|{row['city'].lower()}|{row['postal_code']}"


def _overlap(a, b) -> bool:
    end_a = a["effective_to"] if not pd.isna(a["effective_to"]) else "9999"
    end_b = b["effective_to"] if not pd.isna(b["effective_to"]) else "9999"
    return max(a["effective_from"], b["effective_from"]) <= min(end_a, end_b)


@pytest.fixture(scope="module")
def raw_pairs(tables):
    """Every claimant pair sharing a value in overlapping periods, by edge type."""
    contact = tables["claimant_contact"].assign(address=lambda t: t.apply(_address, axis=1))
    found = {edge_type: set() for edge_type in PAIR_TYPES.values()}
    for field, edge_type in PAIR_TYPES.items():
        for _, rows in contact.dropna(subset=[field]).groupby(field):
            for a, b in combinations(rows.to_dict("records"), 2):
                if a["claimant_id"] != b["claimant_id"] and _overlap(a, b):
                    found[edge_type].add(tuple(sorted((a["claimant_id"], b["claimant_id"]))))
    return found


# ---- EC-1 orphan policy reference

def test_ec1_claims_name_a_well_formed_policy_that_does_not_exist(tables, labels):
    claims = tables["claim"][tables["claim"]["claim_id"].isin(_labelled(labels, "EC-1", "CLAIM"))]
    assert len(claims) == 5
    assert claims["policy_ref"].map(lambda value: bool(re.fullmatch(r"POL-\d{6}", value))).all()
    assert not set(claims["policy_ref"]) & set(tables["policy"]["policy_id"])
    assert claims["policy_id"].isna().all() and claims["days_policy_start_to_incident"].isna().all()
    assert (claims["approved_amount_cents"] == 0).all() and (claims["paid_amount_cents"] == 0).all()
    events = tables["claim_events"][tables["claim_events"]["claim_id"].isin(claims["claim_id"])]
    assert not set(events["to_status"]) & {"APPROVED", "PAID", "DENIED"}
    assert not tables["payment"]["claim_id"].isin(claims["claim_id"]).any()


def test_only_ec1_claims_lack_a_policy(tables, labels):
    assert set(tables["claim"][tables["claim"]["policy_id"].isna()]["claim_id"]) == _labelled(labels, "EC-1", "CLAIM")


# ---- EC-2 payment above the approved amount

def test_ec2_claims_are_overpaid_by_a_repeated_settled_payment(tables, labels):
    claim_ids, payment_ids = _labelled(labels, "EC-2", "CLAIM"), _labelled(labels, "EC-2", "PAYMENT")
    assert len(claim_ids) == len(payment_ids) == 10
    claims = tables["claim"].set_index("claim_id").loc[sorted(claim_ids)]
    assert (claims["paid_amount_cents"] > claims["approved_amount_cents"]).all()
    assert (claims["balance_cents"] < 0).all()
    payment = tables["payment"]
    duplicates = payment[payment["payment_id"].isin(payment_ids)]
    assert (duplicates["current_status"] == "SETTLED").all()
    for row in duplicates.itertuples(index=False):
        earlier = payment[(payment["invoice_id"] == row.invoice_id) & (payment["payment_id"] != row.payment_id)
                          & (payment["current_status"] == "SETTLED")]
        assert len(earlier) == 1
        assert earlier["amount_cents"].item() == row.amount_cents and earlier["payment_date"].item() < row.payment_date


def test_only_ec2_claims_are_paid_above_approval(tables, labels):
    claim = tables["claim"]
    assert set(claim[claim["paid_amount_cents"] > claim["approved_amount_cents"]]["claim_id"]) == \
        _labelled(labels, "EC-2", "CLAIM")


# ---- EC-3 duplicate invoice across claimants

def test_ec3_groups_repeat_one_invoice_across_claimants(tables, labels):
    invoice = tables["invoice"].merge(tables["claim"][["claim_id", "claimant_id"]], on="claim_id")
    groups = labels[(labels["rule_id"] == "EC-3") & (labels["entity_type"] == "INVOICE")].groupby("group_id")
    assert groups.ngroups == 5
    lines = tables["invoice_line"]
    for _, rows in groups:
        copies = invoice[invoice["invoice_id"].isin(rows["entity_id"])]
        assert len(copies) >= 2 and copies["claimant_id"].is_unique
        assert copies[["provider_id", "external_invoice_no", "invoice_date", "total_cents"]].nunique().max() == 1
        detail = [lines[lines["invoice_id"] == value][["service_code", "quantity", "unit_price_cents"]]
                  .reset_index(drop=True) for value in copies["invoice_id"]]
        assert all(table.equals(detail[0]) for table in detail)


# ---- EC-4 and EC-5 are rules from step 3a; here the recorded edges must leave EC-4 out

def test_ec4_links_exist_in_raw_data_but_not_in_recorded_edges(tables, labels, raw_pairs):
    edges = tables["relationship_edge"]
    recorded = set(zip(edges["source_node_id"], edges["target_node_id"]))
    hidden = labels[(labels["issue_type"] == "EC-4") & (labels["entity_type"] == "CLAIMANT")]
    assert hidden["ring_id"].nunique() == 4
    for _, ring in hidden.groupby("ring_id"):
        pairs = {tuple(sorted(pair)) for pair in combinations(ring["entity_id"], 2)}
        assert pairs <= raw_pairs["SHARED_BANK"] and pairs <= raw_pairs["SHARED_PHONE"]
        assert not pairs & recorded


def test_ec5_common_address_is_recorded_as_shared_address(tables, labels):
    edges = tables["relationship_edge"]
    shared = edges[edges["edge_type"] == "SHARED_ADDRESS"]
    pairs = set(zip(shared["source_node_id"], shared["target_node_id"]))
    sites = labels[(labels["issue_type"] == "EC-5") & (labels["entity_type"] == "CLAIMANT")]
    assert sites["group_id"].nunique() == 10
    for _, site in sites.groupby("group_id"):
        assert {tuple(sorted(pair)) for pair in combinations(site["entity_id"], 2)} <= pairs


# ---- graph_node and relationship_edge

def test_graph_has_one_node_per_entity(tables):
    nodes = tables["graph_node"]
    expected = (set(tables["claimant"]["claimant_id"]) | set(tables["policy"]["policy_id"])
                | set(tables["incident"]["incident_id"]) | set(tables["provider"]["provider_id"])
                | set(tables["payment"]["payment_id"]))
    assert nodes["node_id"].is_unique and set(nodes["node_id"]) == expected


@pytest.mark.parametrize("scale", [0.1, 1.0, 2.0])
def test_edge_count_meets_the_minimum(scale):
    tables, _ = generate_with_labels(GeneratorConfig(scale=scale))
    assert len(tables["relationship_edge"]) >= 8_000 * scale


def test_edges_are_unique_well_formed_and_point_at_nodes(tables):
    edges, nodes = tables["relationship_edge"], set(tables["graph_node"]["node_id"])
    assert edges["edge_id"].is_unique and edges["edge_id"].str.fullmatch(r"EDG-\d{6}").all()
    assert not edges.duplicated(["source_node_id", "target_node_id", "edge_type"]).any()
    assert edges["source_node_id"].isin(nodes).all() and edges["target_node_id"].isin(nodes).all()
    assert (edges["source_node_id"] != edges["target_node_id"]).all()
    pair_types = edges[edges["edge_type"].isin(PAIR_TYPES.values())]
    assert (pair_types["source_node_id"] < pair_types["target_node_id"]).all()
    ended = edges.dropna(subset=["valid_to"])
    assert (ended["valid_to"] >= ended["valid_from"]).all()
    assert set(edges["edge_type"]) == {"HOLDS_POLICY", "USED_PROVIDER", "INCIDENT_PARTY", "SHARED_ADDRESS",
                                       "SHARED_PHONE", "SHARED_EMAIL", "SHARED_BANK", "SHARED_CONTACT_PROVIDER",
                                       "PAID_TO_SHARED_ACCOUNT"}


def test_every_source_ref_names_a_real_row_and_field(tables):
    keys = {"claimant_contact": ["contact_id"], "claimant_policy": ["claimant_id", "policy_id"],
            "claim_provider": ["claim_id", "provider_id"], "claim": ["claim_id"], "payment": ["payment_id"]}
    known = {table: {"|".join(row) for row in tables[table][columns].itertuples(index=False)}
             for table, columns in keys.items()}
    for ref in tables["relationship_edge"]["source_ref"]:
        for part in ref.split(";"):
            table, rest = part.split(":", 1)
            row_id, field = rest.rsplit(".", 1)
            assert row_id in known[table], part
            assert field in tables[table].columns, part


def test_shared_value_edges_match_raw_data_except_ec4(tables, labels, raw_pairs):
    hidden = labels[(labels["issue_type"] == "EC-4") & (labels["entity_type"] == "CLAIMANT")]
    hidden_pairs = {tuple(sorted(pair)) for _, ring in hidden.groupby("ring_id")
                    for pair in combinations(ring["entity_id"], 2)}
    edges = tables["relationship_edge"]
    for edge_type, expected in raw_pairs.items():
        rows = edges[edges["edge_type"] == edge_type]
        assert set(zip(rows["source_node_id"], rows["target_node_id"])) == expected - hidden_pairs, edge_type


def test_past_tenants_get_no_shared_address_edge(tables, labels):
    edges = tables["relationship_edge"]
    shared = set(zip(edges["source_node_id"], edges["target_node_id"]))
    for _, rows in labels[(labels["rule_id"] == "B-MOVE-01") & (labels["entity_type"] == "CLAIMANT")].groupby("group_id"):
        assert tuple(sorted(rows["entity_id"])) not in shared


def test_structural_edges_follow_their_source_tables(tables):
    edges = tables["relationship_edge"]
    by_type = {name: set(zip(rows["source_node_id"], rows["target_node_id"])) for name, rows in edges.groupby("edge_type")}
    assert by_type["HOLDS_POLICY"] == set(zip(tables["claimant_policy"]["claimant_id"], tables["claimant_policy"]["policy_id"]))
    used = tables["claim_provider"].merge(tables["claim"], on="claim_id")
    assert by_type["USED_PROVIDER"] == set(zip(used["claimant_id"], used["provider_id"]))
    claim = tables["claim"]
    multi = claim[claim.groupby("incident_id")["claimant_id"].transform("nunique") > 1]
    assert by_type["INCIDENT_PARTY"] == set(zip(multi["claimant_id"], multi["incident_id"]))
    contact, provider = tables["claimant_contact"], tables["provider"]
    expected = set()
    for field in ("phone", "email", "bank_token"):
        matched = contact.dropna(subset=[field]).merge(provider[[field, "provider_id"]], on=field)
        expected |= set(zip(matched["claimant_id"], matched["provider_id"]))
    assert by_type["SHARED_CONTACT_PROVIDER"] == expected


def test_paid_to_shared_account_covers_claimant_payments_into_other_peoples_accounts(tables, labels):
    payment = tables["payment"]
    to_claimants = payment[payment["payee_type"] == "CLAIMANT"]
    owners = pd.concat([tables["claimant_contact"][["bank_token", "claimant_id"]].dropna()
                        .rename(columns={"claimant_id": "owner"}),
                        tables["provider"][["bank_token", "provider_id"]].rename(columns={"provider_id": "owner"})])
    matched = to_claimants.merge(owners.drop_duplicates(), left_on="payee_bank_token", right_on="bank_token")
    matched = matched[matched["owner"] != matched["payee_claimant_id"]]
    hidden = labels[(labels["issue_type"] == "EC-4") & (labels["entity_type"] == "CLAIMANT")]
    ring_of = dict(zip(hidden["entity_id"], hidden["ring_id"]))
    matched = matched[[ring_of.get(a) is None or ring_of.get(a) != ring_of.get(b)
                       for a, b in zip(matched["payee_claimant_id"], matched["owner"])]]
    edges = tables["relationship_edge"]
    rows = edges[edges["edge_type"] == "PAID_TO_SHARED_ACCOUNT"]
    assert set(zip(rows["source_node_id"], rows["target_node_id"])) == set(zip(matched["payment_id"], matched["owner"]))
    assert not rows.empty


# ---- exception checks, reconciled with labels in both directions

@pytest.fixture(scope="module")
def exceptions(tables):
    return find_exceptions(tables)


@pytest.mark.parametrize("exception_type, rule, entity_type", [
    ("ORPHAN_POLICY_REF", "EC-1", "CLAIM"), ("PAYMENT_OVER_APPROVED", "EC-2", "CLAIM"),
    ("DUPLICATE_INVOICE", "EC-3", "INVOICE"),
])
def test_exceptions_and_labels_match_both_ways(exceptions, labels, exception_type, rule, entity_type):
    found = exceptions[exceptions["exception_type"] == exception_type]
    assert set(found["entity_type"]) == {entity_type}
    assert set(found["entity_id"]) == _labelled(labels, rule, entity_type)  # nothing silent, nothing lost


def test_exception_rows_are_complete(exceptions):
    assert exceptions["exception_id"].is_unique and exceptions["exception_id"].str.fullmatch(r"EXC-\d{6}").all()
    assert exceptions.drop(columns="detail_json").notna().all().all()
    for detail in exceptions["detail_json"]:
        assert json.loads(detail)


def test_exceptions_need_only_input_tables(tables):
    """The check works on input tables alone and holds no label."""
    found = find_exceptions({name: tables[name] for name in ("claim", "policy", "payment", "invoice")})
    assert not {"is_fraud", "ring_id", "rule_id", "issue_type"} & set(found.columns)
    assert len(found) > 0


def test_exceptions_on_another_seed_still_match_labels():
    tables, labels = generate_with_labels(GeneratorConfig(seed=7, scale=0.5))
    found = find_exceptions(tables)
    expected = (_labelled(labels, "EC-1", "CLAIM") | _labelled(labels, "EC-2", "CLAIM")
                | _labelled(labels, "EC-3", "INVOICE"))
    assert set(found["entity_id"]) == expected
