"""Rebuilt links and claim facts (ARCHITECTURE.md sections 2 and 3.1-3.2).

Small hand-built cases prove each rule; a generated dataset proves the rules on realistic data.
Tests may read the hidden labels to check results. The detector code itself never does.
"""
import copy
import json

import pandas as pd
import pytest

from fraudnet.detect.config import load_config
from fraudnet.detect.facts import claim_facts, invoice_facts
from fraudnet.detect.links import rebuild_links
from fraudnet.detect.normalise import NarrativeSimilarity, address_key, narrative_words
from fraudnet.generate.__main__ import run as generate_into
from fraudnet.inputs import load_input

SETTINGS, _ = load_config()
STORY = "Another vehicle struck my car at the roundabout in the evening; the side mirror broke. " \
        "It happened close to Juniper at about {}."


def _contact(number, claimant, address="1 Oak St", start="2020-01-01", end=None, phone=None, email=None,
             bank=None, city="Ashcombe", postal="00010"):
    return {"contact_id": f"CON-{number:06d}", "claimant_id": claimant, "effective_from": start, "effective_to": end,
            "address_line": address, "city": city, "postal_code": postal,
            "phone": phone or f"555-100-{number:04d}", "email": email or f"person{number}@example.com",
            "bank_token": bank or f"ACCT-{number:08d}"}


def _world(names, contacts, claims=(), providers=("PRV-000001",), edges=()):
    """Input tables holding just the columns the detector reads. `claims` are dicts with short keys."""
    incidents, claim_rows, used, invoices = [], [], [], []
    for number, item in enumerate(claims, start=1):
        incident = item.get("incident", f"INC-2026-{number:06d}")
        if incident not in {row["incident_id"] for row in incidents}:
            incidents.append({"incident_id": incident, "incident_type": item.get("type", "COLLISION"),
                              "incident_date": item.get("day", "2026-03-01"), "city": item.get("city", "Ashcombe"),
                              "narrative": item.get("narrative", f"Unique words number{number} happened.")})
        claim_id = f"CLM-2026-{number:06d}"
        claim_rows.append({"claim_id": claim_id, "incident_id": incident, "claimant_id": item["claimant"],
                           "policy_id": "POL-000001", "reported_date": item.get("day", "2026-03-01"),
                           "claimed_amount_cents": 1000, "days_incident_to_report": 0,
                           "days_policy_start_to_incident": item.get("since_start", 200)})
        provider = item.get("provider", providers[0])
        used.append({"claim_id": claim_id, "provider_id": provider})
        invoices.append({"invoice_id": f"INV-{provider}-{number:06d}", "provider_id": provider, "claim_id": claim_id,
                         "external_invoice_no": item.get("invoice_no", f"EXT-{number:07d}"),
                         "invoice_date": item.get("day", "2026-03-01"), "total_cents": item.get("total", 1000)})
    claim = pd.DataFrame(claim_rows, columns=["claim_id", "incident_id", "claimant_id", "policy_id", "reported_date",
                                              "claimed_amount_cents", "days_incident_to_report",
                                              "days_policy_start_to_incident"])
    claim["days_policy_start_to_incident"] = claim["days_policy_start_to_incident"].astype("Int64")
    return {
        "claimant": pd.DataFrame({"claimant_id": list(names), "full_name": list(names.values())}),
        "claimant_contact": pd.DataFrame(contacts),
        "provider": pd.DataFrame([{"provider_id": pid, "provider_type": "REPAIRER", "phone": f"555-900-{n:04d}",
                                   "email": f"shop{n}@example.org", "bank_token": f"ACCT-9{n:07d}",
                                   "active_from": "2010-01-01", "active_to": None}
                                  for n, pid in enumerate(providers, start=1)]),
        "claim": claim,
        "incident": pd.DataFrame(incidents, columns=["incident_id", "incident_type", "incident_date", "city",
                                                     "narrative"]),
        "claim_provider": pd.DataFrame(used, columns=["claim_id", "provider_id"]),
        "invoice": pd.DataFrame(invoices, columns=["invoice_id", "provider_id", "claim_id", "external_invoice_no",
                                                   "invoice_date", "total_cents"]),
        "relationship_edge": pd.DataFrame(list(edges), columns=["source_node_id", "target_node_id", "edge_type"]),
    }


def _links(tables, settings=SETTINGS, **changes):
    settings = copy.deepcopy(settings)
    for path, value in changes.items():
        section, name = path.split("__")
        settings[section][name] = value
    return rebuild_links(tables, settings).links


def _of(links, edge_type):
    return links[links["edge_type"] == edge_type]


# ---- normalisation

def test_address_spellings_give_one_key():
    assert address_key("12 Oak St", "Ashcombe", "00010") == address_key("12 OAK STREET", "ashcombe ", "00010")
    assert address_key("12 Oak St", "Ashcombe", "00010") != address_key("12 Oak St", "Bellhaven", "00010")
    assert address_key("12 Oak Ct", "Ashcombe", "00010") != address_key("12 Oak St", "Ashcombe", "00010")


def test_narrative_words_ignore_the_clock_time():
    assert narrative_words(STORY.format("08:05")) == narrative_words(STORY.format("21:40"))


def test_rare_words_count_for_more_than_common_ones():
    texts = [f"the car was hit near {street}" for street in ("Oak", "Elm", "Ash", "Fir")] * 5
    similarity = NarrativeSimilarity(texts)
    a, b = narrative_words("the car was hit near Oak"), narrative_words("the car was hit near Elm")
    c = narrative_words("a bike was stolen near Oak")
    assert similarity.similarity(a, a) == 1.0
    assert similarity.similarity(a, b) < 0.5  # Only the common words match.
    assert similarity.similarity(a, c) > 0.0


# ---- contact links

def test_shared_bank_between_strangers_stands_at_full_strength():
    tables = _world({"CLT-000001": "Ann Lee", "CLT-000002": "Bo Diaz"},
                    [_contact(1, "CLT-000001", bank="ACCT-11111111"),
                     _contact(2, "CLT-000002", address="9 Elm Rd", bank="ACCT-11111111")])
    bank = _of(_links(tables), "SHARED_BANK").iloc[0]
    assert (bank.source_node_id, bank.target_node_id, bank.family) == ("CLT-000001", "CLT-000002", "IDENTITY")
    assert pd.isna(bank.explanation_code) and bank.explanation_factor == 1.0
    assert bank.strength == round(SETTINGS["links"]["caps"]["SHARED_BANK"] * bank.rarity, 4)
    assert bank.in_recorded_edges == 0
    refs = json.loads(bank.source_refs_json)
    assert refs == ["claimant_contact:CON-000001.bank_token", "claimant_contact:CON-000002.bank_token"]


def test_household_explains_a_shared_phone():
    tables = _world({"CLT-000001": "Ann Lee", "CLT-000002": "Max Lee"},
                    [_contact(1, "CLT-000001", phone="555-111-2222"),
                     _contact(2, "CLT-000002", address="1 OAK STREET", phone="555-111-2222")])
    links = _links(tables)
    phone, address = _of(links, "SHARED_PHONE").iloc[0], _of(links, "SHARED_ADDRESS").iloc[0]
    assert phone.explanation_code == "HOUSEHOLD" and address.explanation_code == "HOUSEHOLD"
    factor = SETTINGS["explanations"]["household_factor"]
    assert phone.strength == round(SETTINGS["links"]["caps"]["SHARED_PHONE"] * phone.rarity * factor, 4)


def test_past_tenants_are_not_linked():
    tables = _world({"CLT-000001": "Ann Lee", "CLT-000002": "Bo Diaz"},
                    [_contact(1, "CLT-000001", end="2021-06-30"), _contact(2, "CLT-000002", start="2021-07-01")])
    assert _links(tables).empty


def test_a_busy_building_explains_a_shared_address():
    names = {f"CLT-{n:06d}": f"Person Name{n}" for n in range(1, 7)}
    tables = _world(names, [_contact(n, f"CLT-{n:06d}") for n in range(1, 7)])
    address = _of(_links(tables), "SHARED_ADDRESS")
    assert len(address) == 15 and set(address["explanation_code"]) == {"BUILDING"}
    small = _world(dict(list(names.items())[:2]), [_contact(n, f"CLT-{n:06d}") for n in range(1, 3)])
    assert _of(_links(small), "SHARED_ADDRESS")["explanation_code"].isna().all()


def test_claimant_holding_a_provider_account_is_linked_to_the_provider():
    tables = _world({"CLT-000001": "Ann Lee"}, [_contact(1, "CLT-000001", bank="ACCT-90000001")])
    link = _of(_links(tables), "SHARED_CONTACT_PROVIDER").iloc[0]
    assert (link.source_node_id, link.target_node_id) == ("CLT-000001", "PRV-000001")


def test_links_found_in_the_recorded_register_are_marked():
    contacts = [_contact(1, "CLT-000001", bank="ACCT-11111111"),
                _contact(2, "CLT-000002", address="9 Elm Rd", bank="ACCT-11111111")]
    tables = _world({"CLT-000001": "Ann Lee", "CLT-000002": "Bo Diaz"}, contacts,
                    edges=[("CLT-000001", "CLT-000002", "SHARED_BANK")])
    assert _of(_links(tables), "SHARED_BANK").iloc[0].in_recorded_edges == 1


# ---- claim links

def _people(count):
    names = {f"CLT-{n:06d}": f"Person Name{n}" for n in range(1, count + 1)}
    contacts = [_contact(n, f"CLT-{n:06d}", address=f"{n} Elm Rd") for n in range(1, count + 1)]
    return names, contacts


def test_same_incident_needs_three_claimants():
    names, contacts = _people(3)
    two = _world(names, contacts, [{"claimant": f"CLT-{n:06d}", "incident": "INC-2026-000009"} for n in (1, 2)])
    assert _of(_links(two), "SAME_INCIDENT").empty
    three = _world(names, contacts, [{"claimant": f"CLT-{n:06d}", "incident": "INC-2026-000009"} for n in (1, 2, 3)])
    assert len(_of(_links(three), "SAME_INCIDENT")) == 3


def test_duplicate_invoice_links_different_claimants_only():
    names, contacts = _people(2)
    same_bill = {"invoice_no": "EXT-0000001", "total": 5000, "day": "2026-02-02"}
    tables = _world(names, contacts, [{"claimant": "CLT-000001", **same_bill}, {"claimant": "CLT-000002", **same_bill}])
    link = _of(_links(tables), "DUPLICATE_INVOICE").iloc[0]
    assert json.loads(link.detail_json)["total_cents"] == 5000 and link.family == "BILLING"
    one_person = _world(names, contacts, [{"claimant": "CLT-000001", **same_bill}] * 2)
    assert _of(_links(one_person), "DUPLICATE_INVOICE").empty


def test_similar_narratives_link_only_through_a_shared_provider():
    names, contacts = _people(2)
    claims = [{"claimant": "CLT-000001", "narrative": STORY.format("08:05"), "city": "Ashcombe", "day": "2026-02-01"},
              {"claimant": "CLT-000002", "narrative": STORY.format("08:15"), "city": "Bellhaven", "day": "2026-04-01"}]
    others = [{"claimant": "CLT-000001", "narrative": f"Unrelated text {word}.", "day": "2026-05-01"}
              for word in ("alpha", "beta", "gamma", "delta")]
    shared = _of(_links(_world(names, contacts, claims + others)), "SIMILAR_NARRATIVE")
    assert len(shared) == 1 and pd.isna(shared.iloc[0].explanation_code)
    apart = [dict(claims[0], provider="PRV-000001"), dict(claims[1], provider="PRV-000002")]
    tables = _world(names, contacts, apart + others, providers=("PRV-000001", "PRV-000002"))
    assert _of(_links(tables), "SIMILAR_NARRATIVE").empty


def test_same_city_and_week_explains_similar_narratives():
    names, contacts = _people(2)
    claims = [{"claimant": "CLT-000001", "narrative": STORY.format("08:05"), "day": "2026-02-01"},
              {"claimant": "CLT-000002", "narrative": STORY.format("08:15"), "day": "2026-02-03"}]
    others = [{"claimant": "CLT-000001", "narrative": f"Unrelated text {word}.", "day": "2026-05-01"}
              for word in ("alpha", "beta", "gamma", "delta")]
    link = _of(_links(_world(names, contacts, claims + others)), "SIMILAR_NARRATIVE").iloc[0]
    assert link.explanation_code == "COMMON_EVENT"


def test_early_claims_link_within_the_window_at_one_provider():
    names, contacts = _people(3)
    claims = [{"claimant": "CLT-000001", "since_start": 3, "day": "2026-02-01"},
              {"claimant": "CLT-000002", "since_start": 7, "day": "2026-03-01"},
              {"claimant": "CLT-000003", "since_start": 2, "day": "2026-06-01"}]
    timing = _of(_links(_world(names, contacts, claims)), "EARLY_CLAIM_PAIR")
    assert list(zip(timing.source_node_id, timing.target_node_id)) == [("CLT-000001", "CLT-000002")]


def test_busy_provider_explains_provider_based_links():
    names, contacts = _people(3)
    claims = [{"claimant": "CLT-000001", "since_start": 3, "provider": "PRV-000001"},
              {"claimant": "CLT-000002", "since_start": 7, "provider": "PRV-000001"},
              {"claimant": "CLT-000003", "provider": "PRV-000002"}]
    tables = _world(names, contacts, claims, providers=("PRV-000001", "PRV-000002"))
    link = _of(_links(tables, explanations__busy_provider_percentile=0.0), "EARLY_CLAIM_PAIR").iloc[0]
    assert link.explanation_code == "BUSY_PROVIDER"


def test_rarity_scales_strength_between_the_floor_and_the_cap():
    names = {f"CLT-{n:06d}": f"Person Name{n}" for n in range(1, 5)}
    contacts = [_contact(n, f"CLT-{n:06d}", address=f"{n} Elm Rd", bank="ACCT-11111111") for n in range(1, 5)]
    links = _of(_links(_world(names, contacts)), "SHARED_BANK")
    assert set(links["rarity"]) == {SETTINGS["rarity"]["floor"]}  # Every claimant has it: not rare at all.
    names.update({f"CLT-{n:06d}": f"Person Name{n}" for n in range(5, 201)})
    contacts += [_contact(n, f"CLT-{n:06d}", address=f"{n} Elm Rd") for n in range(5, 201)]
    links = _of(_links(_world(names, contacts)), "SHARED_BANK")
    assert set(links["rarity"]) == {1.0}  # 4 of 200 claimants (2%) is rarer than the reference.


# ---- claim facts

def test_claim_and_invoice_facts():
    names, contacts = _people(4)
    claims = [{"claimant": f"CLT-{n:06d}", "total": total, "since_start": gap}
              for n, total, gap in ((1, 1000, 3), (2, 1000, 200), (3, 1000, 200), (4, 3000, 200))]
    tables = _world(names, contacts, claims)
    facts = claim_facts(tables, SETTINGS)
    assert facts["early_claim"].tolist() == [True, False, False, False]
    invoices = invoice_facts(tables, SETTINGS)
    assert invoices["peer_median_cents"].unique().tolist() == [1000.0]
    assert invoices["inflated"].tolist() == [False, False, False, True]


# ---- generated data

@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    folder = tmp_path_factory.mktemp("detect")
    generate_into(20261022, 0.1, folder)
    tables, _ = load_input(folder / "input")
    labels = pd.read_csv(folder / "hidden/ground_truth.csv", dtype=str)
    claimants = labels[labels["entity_type"] == "CLAIMANT"]
    groups = dict(zip(claimants["entity_id"], claimants["ring_id"].fillna(claimants["group_id"])))
    rules = dict(zip(claimants["entity_id"], claimants["rule_id"]))
    return tables, rebuild_links(tables, SETTINGS).links, groups, rules


def test_every_recorded_shared_edge_is_rebuilt(generated):
    tables, links, _, _ = generated
    edges = tables["relationship_edge"]
    shared = edges[edges["edge_type"].isin(["SHARED_ADDRESS", "SHARED_PHONE", "SHARED_EMAIL", "SHARED_BANK",
                                            "SHARED_CONTACT_PROVIDER"])]
    rebuilt = set(zip(links["source_node_id"], links["target_node_id"], links["edge_type"]))
    assert set(zip(shared["source_node_id"], shared["target_node_id"], shared["edge_type"])) <= rebuilt


def test_hidden_ring_links_are_recovered_as_unrecorded(generated):
    _, links, groups, rules = generated
    hidden = links[links["source_node_id"].map(rules).eq("R-RING-06") & links["edge_type"].eq("SHARED_BANK")]
    members = {node for node, rule in rules.items() if rule == "R-RING-06"}
    ring_count = len({groups[node] for node in members})
    assert len(hidden) >= ring_count and set(hidden["in_recorded_edges"]) == {0}
    assert all(groups[a] == groups[b] for a, b in zip(hidden["source_node_id"], hidden["target_node_id"]))


def test_unexplained_identity_links_stay_inside_one_ring(generated):
    _, links, groups, rules = generated
    identity = links[(links["family"] == "IDENTITY") & links["explanation_code"].isna()
                     & links["target_node_id"].str.startswith("CLT-")]
    assert len(identity) > 0
    for a, b in zip(identity["source_node_id"], identity["target_node_id"]):
        assert groups.get(a) is not None and groups[a] == groups.get(b) and rules[a].startswith("R-RING")


def test_household_and_building_explanations_land_on_look_alikes(generated):
    _, links, _, rules = generated
    explained = links[links["explanation_code"].isin(["HOUSEHOLD", "BUILDING"])]
    assert len(explained) > 0
    expected = {"HOUSEHOLD": "B-HOUSE-01", "BUILDING": "B-ADDR-01"}
    for code, a in zip(explained["explanation_code"], explained["source_node_id"]):
        assert rules.get(a) == expected[code]


def test_past_tenants_get_no_address_link(generated):
    _, links, groups, rules = generated
    movers = {node for node, rule in rules.items() if rule == "B-MOVE-01"}
    pairs = set(zip(links["source_node_id"], links["target_node_id"]))
    assert not any(a in movers and groups.get(a) == groups.get(b) for a, b in pairs)


def test_rebuilding_is_deterministic(generated):
    tables, links, _, _ = generated
    pd.testing.assert_frame_equal(rebuild_links(tables, SETTINGS).links, links)
