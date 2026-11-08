"""Transaction rules from docs/DATA_DICTIONARY.md sections 3, 5, 6 and 7.

Every derived value is recalculated here from source rows, independently of the generator.
"""
import pandas as pd
import pytest

from fraudnet.generate.config import AS_OF_DATE, GeneratorConfig
from fraudnet.generate.ids import ID_PATTERNS
from fraudnet.generate.lifecycle import allocate
from fraudnet.generate.pipeline import generate, generate_with_labels
from fraudnet.generate.transactions import INCIDENT_TYPES_BY_POLICY

AS_OF = AS_OF_DATE.isoformat()
TRANSITIONS = {
    "claim_events": {
        (None, "SUBMITTED"), ("SUBMITTED", "UNDER_REVIEW"), ("SUBMITTED", "WITHDRAWN"),
        ("UNDER_REVIEW", "APPROVED"), ("UNDER_REVIEW", "DENIED"), ("UNDER_REVIEW", "WITHDRAWN"),
        ("APPROVED", "PAID"), ("PAID", "CLOSED"), ("DENIED", "CLOSED"), ("WITHDRAWN", "CLOSED"),
    },
    "invoice_events": {
        (None, "RECEIVED"), ("RECEIVED", "VERIFIED"), ("RECEIVED", "REJECTED"), ("VERIFIED", "APPROVED"),
        ("VERIFIED", "REJECTED"), ("APPROVED", "PAID"),
    },
    "payment_events": {
        (None, "INITIATED"), ("INITIATED", "SETTLED"), ("INITIATED", "FAILED"), ("SETTLED", "REVERSED"),
    },
}
PARENTS = {"claim_events": ("claim_id", "claim"), "invoice_events": ("invoice_id", "invoice"),
           "payment_events": ("payment_id", "payment")}


@pytest.fixture(scope="module")
def data():
    return generate_with_labels(GeneratorConfig(scale=1.0))


@pytest.fixture(scope="module")
def tables(data):
    return data[0]


@pytest.fixture(scope="module")
def edge_case_claims(data):
    """Claims planted as EC-1 to EC-3. They break baseline rules on purpose; test_generate_edge_cases.py covers them."""
    labels = data[1]
    return set(labels[labels["rule_id"].isin({"EC-1", "EC-2", "EC-3"}) & (labels["entity_type"] == "CLAIM")]["entity_id"])


@pytest.fixture(scope="module")
def normal_claims(tables, edge_case_claims):
    return tables["claim"][~tables["claim"]["claim_id"].isin(edge_case_claims)]


@pytest.fixture(scope="module")
def claim_view(tables):
    """Claims joined to their incident and policy."""
    return tables["claim"].merge(tables["incident"], on="incident_id", validate="m:1").merge(
        tables["policy"], on="policy_id", validate="m:1", suffixes=("", "_policy"))


def _none(value):
    return None if pd.isna(value) else value


def test_claim_count_is_exact_and_incidents_are_fewer(tables):
    assert len(tables["claim"]) == 5_000
    assert 4_000 < len(tables["incident"]) < 5_000


@pytest.mark.parametrize("table, column, entity", [
    ("incident", "incident_id", "incident"), ("claim", "claim_id", "claim"), ("invoice", "invoice_id", "invoice"),
    ("payment", "payment_id", "payment"), ("claim_events", "event_id", "claim_event"),
    ("invoice_events", "event_id", "invoice_event"), ("payment_events", "event_id", "payment_event"),
])
def test_primary_keys_are_unique_and_well_formed(tables, table, column, entity):
    values = tables[table][column]
    assert values.is_unique
    assert values.map(lambda v: bool(ID_PATTERNS[entity].match(v))).all()


def test_foreign_keys_resolve(tables):
    claims = set(tables["claim"]["claim_id"])
    invoices = set(tables["invoice"]["invoice_id"])
    providers = set(tables["provider"]["provider_id"])
    claimants = set(tables["claimant"]["claimant_id"])
    assert set(tables["claim"]["incident_id"]) == set(tables["incident"]["incident_id"])
    assert set(tables["claim"]["claimant_id"]) <= claimants
    assert set(tables["claim"]["policy_id"].dropna()) <= set(tables["policy"]["policy_id"])
    assert set(tables["invoice"]["claim_id"]) <= claims
    assert set(tables["invoice"]["provider_id"]) <= providers
    assert set(tables["invoice_line"]["invoice_id"]) == invoices
    assert set(tables["payment"]["invoice_id"]) <= invoices
    assert set(tables["claim_provider"]["claim_id"]) <= claims
    assert set(tables["claim_provider"]["provider_id"]) <= providers


def test_claimant_holds_the_policy_they_claim_on(tables, normal_claims):
    pairs = set(zip(tables["claimant_policy"]["claimant_id"], tables["claimant_policy"]["policy_id"]))
    assert all(pair in pairs for pair in zip(normal_claims["claimant_id"], normal_claims["policy_id"]))


def test_policy_ref_matches_policy_id_outside_edge_cases(normal_claims):
    assert (normal_claims["policy_ref"] == normal_claims["policy_id"]).all()


def test_invoice_id_contains_its_provider_and_counts_per_provider_by_date(tables):
    invoice = tables["invoice"]
    assert (invoice["invoice_id"].str[4:14] == invoice["provider_id"]).all()
    for _, rows in invoice.groupby("provider_id"):
        rows = rows.sort_values("invoice_id")
        assert rows["invoice_id"].str[-6:].astype(int).tolist() == list(range(1, len(rows) + 1))
        assert rows["invoice_date"].is_monotonic_increasing


def test_every_invoice_provider_pair_is_in_the_bridge(tables):
    bridge = tables["claim_provider"]
    assert not bridge.duplicated(["claim_id", "provider_id", "service_role"]).any()
    pairs = set(zip(bridge["claim_id"], bridge["provider_id"]))
    assert all(pair in pairs for pair in zip(tables["invoice"]["claim_id"], tables["invoice"]["provider_id"]))


def test_line_invoice_and_claim_totals_reconcile(tables):
    line = tables["invoice_line"]
    assert (line["line_amount_cents"] == line["quantity"] * line["unit_price_cents"]).all()

    totals = line.groupby("invoice_id")["line_amount_cents"].sum()
    covered = line[line["is_covered"] == 1].groupby("invoice_id")["line_amount_cents"].sum()
    invoice = tables["invoice"].set_index("invoice_id")
    assert (invoice["total_cents"] == totals.reindex(invoice.index)).all()
    assert (invoice["covered_cents"] == covered.reindex(invoice.index).fillna(0)).all()

    claimed = tables["invoice"].groupby("claim_id")["total_cents"].sum()
    claim = tables["claim"].set_index("claim_id")
    assert (claim["claimed_amount_cents"] == claimed.reindex(claim.index).fillna(0)).all()


def test_approved_amount_follows_the_formula(tables, claim_view):
    approved_ids = set(tables["claim_events"].query("to_status == 'APPROVED'")["claim_id"])
    eligible = tables["invoice"][tables["invoice"]["current_status"] != "REJECTED"]
    covered = eligible.groupby("claim_id")["covered_cents"].sum()
    for row in claim_view.to_dict("records"):
        if row["claim_id"] in approved_ids:
            expected = max(0, min(int(covered.get(row["claim_id"], 0)), row["coverage_limit_cents"])
                           - row["deductible_cents"])
        else:
            expected = 0
        assert row["approved_amount_cents"] == expected, row["claim_id"]


def test_paid_and_balance_follow_the_formula(tables):
    settled = tables["payment"][tables["payment"]["current_status"] == "SETTLED"]
    paid = settled.groupby("claim_id")["amount_cents"].sum()
    claim = tables["claim"].set_index("claim_id")
    assert (claim["paid_amount_cents"] == paid.reindex(claim.index).fillna(0)).all()
    assert (claim["balance_cents"] == claim["approved_amount_cents"] - claim["paid_amount_cents"]).all()


def test_never_pays_more_than_approved_outside_edge_cases(normal_claims):
    assert (normal_claims["balance_cents"] >= 0).all()


def test_paid_claims_are_paid_exactly(normal_claims):
    finished = normal_claims[normal_claims["current_status"].isin({"PAID"})]
    assert not finished.empty
    assert (finished["balance_cents"] == 0).all()


def test_day_gaps_are_derived(claim_view):
    report = pd.to_datetime(claim_view["reported_date"])
    incident = pd.to_datetime(claim_view["incident_date"])
    start = pd.to_datetime(claim_view["effective_from"])
    assert (claim_view["days_incident_to_report"] == (report - incident).dt.days).all()
    assert (claim_view["days_policy_start_to_incident"] == (incident - start).dt.days).all()


def test_dates_are_ordered(tables, claim_view):
    assert claim_view["incident_date"].between("2026-01-01", "2026-09-30").all()
    assert (claim_view["reported_date"] >= claim_view["incident_date"]).all()
    assert (claim_view["reported_date"] <= AS_OF).all()

    invoice = tables["invoice"].merge(claim_view[["claim_id", "incident_date", "reported_date"]], on="claim_id")
    assert (invoice["invoice_date"] >= invoice["incident_date"]).all()
    assert (invoice["invoice_date"] <= AS_OF).all()

    approved = tables["claim_events"].query("to_status == 'APPROVED'")[["claim_id", "event_at"]]
    payment = tables["payment"].merge(approved, on="claim_id")
    assert len(payment) == len(tables["payment"])
    assert (payment["payment_date"] > payment["event_at"].str[:10]).all()
    assert (tables["payment"]["payment_date"] <= AS_OF).all()


def test_providers_are_active_on_invoice_date(tables):
    joined = tables["invoice"].merge(tables["provider"], on="provider_id")
    assert (joined["invoice_date"] >= joined["active_from"]).all()
    closed = joined[joined["active_to"].notna()]
    assert (closed["invoice_date"] <= closed["active_to"]).all()


def test_payment_belongs_to_the_invoice_claim_and_has_one_payee(tables):
    joined = tables["payment"].merge(tables["invoice"], on="invoice_id", suffixes=("", "_invoice"))
    assert (joined["claim_id"] == joined["claim_id_invoice"]).all()
    payment = tables["payment"]
    assert (payment["payee_claimant_id"].notna() ^ payment["payee_provider_id"].notna()).all()
    assert ((payment["payee_type"] == "CLAIMANT") == payment["payee_claimant_id"].notna()).all()
    assert (payment["amount_cents"] > 0).all()


def test_payee_bank_token_belongs_to_the_payee(tables):
    payment = tables["payment"]
    provider_bank = tables["provider"].set_index("provider_id")["bank_token"]
    to_provider = payment[payment["payee_type"] == "PROVIDER"]
    assert (to_provider["payee_bank_token"].values ==
            provider_bank.reindex(to_provider["payee_provider_id"]).values).all()
    contacts = set(zip(tables["claimant_contact"]["claimant_id"], tables["claimant_contact"]["bank_token"]))
    to_claimant = payment[payment["payee_type"] == "CLAIMANT"]
    assert all(pair in contacts for pair in zip(to_claimant["payee_claimant_id"], to_claimant["payee_bank_token"]))


@pytest.mark.parametrize("events_name", list(TRANSITIONS))
def test_events_follow_lifecycle_and_status_is_latest(tables, events_name):
    parent_column, parent_table = PARENTS[events_name]
    events = tables[events_name]
    assert set(events[parent_column]) == set(tables[parent_table][parent_column])
    allowed = TRANSITIONS[events_name]
    for _, rows in events.sort_values([parent_column, "seq"]).groupby(parent_column):
        assert rows["seq"].tolist() == list(range(1, len(rows) + 1))
        assert rows["event_at"].is_monotonic_increasing
        last = None
        for from_status, to_status in zip(rows["from_status"], rows["to_status"]):
            assert (_none(from_status), to_status) in allowed
            assert _none(from_status) == last
            last = to_status
    assert (events["event_at"].str[:10] <= AS_OF).all()
    latest = events.sort_values([parent_column, "seq"]).groupby(parent_column)["to_status"].last()
    table = tables[parent_table].set_index(parent_column)
    assert (table["current_status"] == latest.reindex(table.index)).all()


@pytest.mark.parametrize("events_name, statuses", [
    ("claim_events", {"DENIED", "WITHDRAWN", "CLOSED"}),
    ("invoice_events", {"REJECTED"}),
    ("payment_events", {"FAILED", "REVERSED"}),
])
def test_negative_outcomes_always_have_a_reason(tables, events_name, statuses):
    events = tables[events_name]
    assert events[events["to_status"].isin(statuses)]["reason_code"].notna().all()


@pytest.mark.parametrize("events_name", list(TRANSITIONS))
def test_staff_events_name_the_staff_member(tables, events_name):
    events = tables[events_name]
    assert events[events["actor_role"] == "OPS_ANALYST"]["actor_id"].notna().all()


def test_type_mismatch_is_denied(tables, claim_view):
    denied = tables["claim_events"].query("to_status == 'DENIED'").set_index("claim_id")["reason_code"]
    decided = set(tables["claim_events"].query("to_status in ['APPROVED', 'DENIED']")["claim_id"])
    for row in claim_view.to_dict("records"):
        if row["claim_id"] in decided and row["incident_type"] not in INCIDENT_TYPES_BY_POLICY[row["policy_type"]][0]:
            assert denied.get(row["claim_id"]) == "TYPE_NOT_COVERED"


def test_incident_outside_policy_is_never_approved(tables, claim_view):
    approved = set(tables["claim_events"].query("to_status == 'APPROVED'")["claim_id"])
    outside = claim_view[(claim_view["incident_date"] < claim_view["effective_from"]) |
                         (claim_view["incident_date"] > claim_view["effective_to"])]
    assert not outside.empty
    assert not approved & set(outside["claim_id"])


def test_failed_payment_row_stays_and_retry_is_a_new_row(tables):
    failed = tables["payment"][tables["payment"]["current_status"] == "FAILED"]
    assert not failed.empty
    later = tables["payment"][tables["payment"]["invoice_id"].isin(failed["invoice_id"])]
    assert len(later) > len(failed)


def test_coverage_of_normal_boundary_and_failure_cases(tables, claim_view):
    reasons = set(tables["claim_events"]["reason_code"].dropna())
    assert {"TYPE_NOT_COVERED", "OUTSIDE_COVERAGE", "POLICY_NOT_ACTIVE", "INSUFFICIENT_EVIDENCE",
            "BELOW_DEDUCTIBLE", "CUSTOMER_REQUEST", "SETTLED"} <= reasons
    assert {"UNDER_REVIEW", "APPROVED", "PAID", "DENIED", "CLOSED"} <= set(tables["claim"]["current_status"])
    assert {"FAILED", "REVERSED", "SETTLED"} <= set(tables["payment"]["current_status"])
    assert {"REJECTED", "PAID"} <= set(tables["invoice"]["current_status"])

    assert (claim_view["incident_date"] == claim_view["effective_from"]).any()
    assert (claim_view["incident_date"] == claim_view["effective_to"]).any()
    assert (claim_view["reported_date"] == claim_view["incident_date"]).any()
    assert (tables["invoice_line"].groupby("invoice_id").size() == 1).any()

    covered = tables["invoice"].groupby("claim_id")["covered_cents"].sum().rename("covered")
    joined = claim_view.merge(covered, on="claim_id")
    assert (joined["covered"] == joined["deductible_cents"]).any()
    approved = joined[joined["approved_amount_cents"] > 0]
    assert (approved["covered"] > approved["coverage_limit_cents"]).any()


def test_data_varies_realistically(tables):
    per_claimant = tables["claim"].groupby("claimant_id").size()
    assert len(per_claimant) < len(tables["claimant"])  # some claimants have no claims
    assert per_claimant.median() >= 1 and per_claimant.max() >= 5
    per_provider = tables["invoice"].groupby("provider_id").size()
    assert per_provider.max() > 5 * per_provider.median()  # some providers are much busier
    assert tables["invoice"]["total_cents"].quantile(0.95) > 3 * tables["invoice"]["total_cents"].median()
    assert tables["incident"]["incident_type"].nunique() == 6


def test_claims_per_claimant_have_a_believable_long_tail(tables):
    """A heavy ordinary claimant would look like a suspect before any look-alike is planted."""
    per_claimant = tables["claim"].groupby("claimant_id").size()
    assert per_claimant.max() <= 8
    assert (per_claimant <= 3).mean() > 0.5  # many have 1-3
    assert (per_claimant >= 6).mean() < 0.12  # only a few have many; exact volumes put the floor near 10%
    assert (per_claimant == 8).sum() < (per_claimant == 7).sum()  # the limit must not cause a pile-up
    assert 0 < 1 - len(per_claimant) / len(tables["claimant"]) < 0.30  # some have none


def test_reversed_payment_leaves_invoice_approved_and_claim_unpaid(tables):
    payment = tables["payment"]
    reversed_rows = payment[payment["current_status"] == "REVERSED"]
    assert len(reversed_rows)
    invoice_status = tables["invoice"].set_index("invoice_id")["current_status"]
    assert set(invoice_status[reversed_rows["invoice_id"]]) == {"APPROVED"}
    events = tables["claim_events"]
    reached_paid = set(events[events["to_status"] == "PAID"]["claim_id"])
    assert not reached_paid & set(reversed_rows["claim_id"])


def test_unrelated_narratives_rarely_match_by_chance(tables):
    narrative = tables["incident"]["narrative"]
    assert narrative.nunique() / len(narrative) > 0.95


def test_incident_months_have_no_artificial_spikes(tables):
    months = tables["incident"]["incident_date"].str[:7].value_counts()
    assert len(months) == 9
    assert months.max() / months.min() < 1.8


def test_baseline_claims_are_not_concentrated_right_after_policy_start(claim_view):
    """Sudden early claims must stay rare enough to be a useful signal once rings are planted."""
    in_force = claim_view[claim_view["days_policy_start_to_incident"] >= 0]
    assert (in_force["days_policy_start_to_incident"] <= 30).mean() < 0.15


@pytest.mark.parametrize("seed, scale", [(1, 1.0), (7, 0.1), (9, 0.25)])
def test_other_seeds_and_scales_reconcile(seed, scale):
    config = GeneratorConfig(seed=seed, scale=scale)
    result, labels = generate_with_labels(config)
    assert len(result["claim"]) == config.count("claim")
    claim = result["claim"]
    assert (claim["balance_cents"] == claim["approved_amount_cents"] - claim["paid_amount_cents"]).all()
    overpaid = set(labels[(labels["rule_id"] == "EC-2") & (labels["entity_type"] == "CLAIM")]["entity_id"])
    assert set(claim[claim["balance_cents"] < 0]["claim_id"]) == overpaid
    assert set(result["invoice"]["claim_id"]) <= set(claim["claim_id"])


def test_some_incidents_have_several_claimants(tables):
    assert (tables["claim"].groupby("incident_id")["claimant_id"].nunique() > 1).any()


def test_external_invoice_numbers_do_not_repeat_outside_edge_cases(tables, edge_case_claims):
    invoice = tables["invoice"]
    assert invoice[~invoice["claim_id"].isin(edge_case_claims)]["external_invoice_no"].is_unique


def test_claim_numbers_follow_report_dates(tables):
    assert tables["claim"].sort_values("claim_id")["reported_date"].is_monotonic_increasing


def test_no_internal_planning_or_key_columns_are_exported(tables):
    for table in tables.values():
        assert not [c for c in table.columns if c.startswith("plan_") or c.endswith("_key") or c.startswith("_")]


def test_allocate_keeps_every_cent():
    assert allocate(1_001, [1, 1, 1]) == [333, 333, 335]
    assert sum(allocate(99_999, [7, 13, 29])) == 99_999
    assert allocate(500, [10]) == [500]
