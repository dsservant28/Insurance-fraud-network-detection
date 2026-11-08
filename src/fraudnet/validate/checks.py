"""Hard validation checks V-01 to V-12 from docs/DATA_DICTIONARY.md section 11.1.

Each check recalculates its rule from the input files on its own, without reusing generator code,
so a generator mistake shows up here. Any failure fails the run. Planted edge cases are expected:
they pass these checks and are reported separately as exceptions (exceptions.py).
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from fraudnet.generate.config import GeneratorConfig
from fraudnet.generate.ids import ID_PATTERNS

AS_OF = "2026-10-22"
WINDOW = ("2026-01-01", "2026-09-30")
MIN_EDGES_PER_SCALE = 8_000
MAX_EXAMPLES = 5

PRIMARY_KEYS = {
    "claimant": ["claimant_id"], "claimant_contact": ["contact_id"], "provider": ["provider_id"],
    "policy": ["policy_id"], "claimant_policy": ["claimant_id", "policy_id"], "policy_events": ["event_id"],
    "incident": ["incident_id"], "claim": ["claim_id"], "claim_events": ["event_id"],
    "claim_provider": ["claim_id", "provider_id", "service_role"], "invoice": ["invoice_id"],
    "invoice_line": ["invoice_id", "line_no"], "invoice_events": ["event_id"], "payment": ["payment_id"],
    "payment_events": ["event_id"], "graph_node": ["node_id"], "relationship_edge": ["edge_id"],
}
ID_FORMATS = {
    ("claimant", "claimant_id"): "claimant", ("claimant_contact", "contact_id"): "contact",
    ("provider", "provider_id"): "provider", ("policy", "policy_id"): "policy", ("incident", "incident_id"): "incident",
    ("claim", "claim_id"): "claim", ("claim", "policy_ref"): "policy", ("invoice", "invoice_id"): "invoice",
    ("payment", "payment_id"): "payment", ("relationship_edge", "edge_id"): "edge",
    ("policy_events", "event_id"): "policy_event", ("claim_events", "event_id"): "claim_event",
    ("invoice_events", "event_id"): "invoice_event", ("payment_events", "event_id"): "payment_event",
}
FOREIGN_KEYS = [  # (child table, child column, parent table, parent column, may be empty)
    ("claimant_contact", "claimant_id", "claimant", "claimant_id", False),
    ("claimant_policy", "claimant_id", "claimant", "claimant_id", False),
    ("claimant_policy", "policy_id", "policy", "policy_id", False),
    ("policy_events", "policy_id", "policy", "policy_id", False),
    ("claim", "incident_id", "incident", "incident_id", False),
    ("claim", "claimant_id", "claimant", "claimant_id", False),
    ("claim", "policy_id", "policy", "policy_id", True),
    ("claim_events", "claim_id", "claim", "claim_id", False),
    ("claim_provider", "claim_id", "claim", "claim_id", False),
    ("claim_provider", "provider_id", "provider", "provider_id", False),
    ("invoice", "claim_id", "claim", "claim_id", False),
    ("invoice", "provider_id", "provider", "provider_id", False),
    ("invoice_line", "invoice_id", "invoice", "invoice_id", False),
    ("invoice_events", "invoice_id", "invoice", "invoice_id", False),
    ("payment", "claim_id", "claim", "claim_id", False),
    ("payment", "invoice_id", "invoice", "invoice_id", False),
    ("payment", "payee_claimant_id", "claimant", "claimant_id", True),
    ("payment", "payee_provider_id", "provider", "provider_id", True),
    ("payment_events", "payment_id", "payment", "payment_id", False),
    ("relationship_edge", "source_node_id", "graph_node", "node_id", False),
    ("relationship_edge", "target_node_id", "graph_node", "node_id", False),
]
ROLES = {"CUSTOMER", "OPS_ANALYST", "RISK_REVIEWER", "SYS_ADMIN", "SYSTEM"}
LIFECYCLES = {  # events table: (parent table, parent column, start status, allowed transitions)
    "policy_events": ("policy", "policy_id", "ACTIVE",
                      {("ACTIVE", "LAPSED"), ("ACTIVE", "CANCELLED"), ("ACTIVE", "EXPIRED"), ("LAPSED", "ACTIVE")}),
    "claim_events": ("claim", "claim_id", "SUBMITTED",
                     {("SUBMITTED", "UNDER_REVIEW"), ("SUBMITTED", "WITHDRAWN"), ("UNDER_REVIEW", "APPROVED"),
                      ("UNDER_REVIEW", "DENIED"), ("UNDER_REVIEW", "WITHDRAWN"), ("APPROVED", "PAID"),
                      ("PAID", "CLOSED"), ("DENIED", "CLOSED"), ("WITHDRAWN", "CLOSED")}),
    "invoice_events": ("invoice", "invoice_id", "RECEIVED",
                       {("RECEIVED", "VERIFIED"), ("RECEIVED", "REJECTED"), ("VERIFIED", "APPROVED"),
                        ("VERIFIED", "REJECTED"), ("APPROVED", "PAID")}),
    "payment_events": ("payment", "payment_id", "INITIATED",
                       {("INITIATED", "SETTLED"), ("INITIATED", "FAILED"), ("SETTLED", "REVERSED")}),
}
ENUMS = {
    ("provider", "provider_type"): {"REPAIRER", "MEDICAL", "SERVICE"},
    ("policy", "policy_type"): {"AUTO", "HOME", "HEALTH"},
    ("policy", "current_status"): {"ACTIVE", "LAPSED", "CANCELLED", "EXPIRED"},
    ("claimant_policy", "role"): {"POLICYHOLDER", "NAMED_INSURED"},
    ("incident", "incident_type"): {"COLLISION", "THEFT", "INJURY", "WATER_DAMAGE", "FIRE", "ILLNESS"},
    ("claim", "current_status"): {"SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED", "WITHDRAWN", "PAID", "CLOSED"},
    ("claim_provider", "service_role"): {"REPAIR", "MEDICAL", "TOWING", "LEGAL"},
    ("invoice", "current_status"): {"RECEIVED", "VERIFIED", "APPROVED", "REJECTED", "PAID"},
    ("invoice_line", "is_covered"): {0, 1},
    ("payment", "payee_type"): {"CLAIMANT", "PROVIDER"},
    ("payment", "current_status"): {"INITIATED", "SETTLED", "FAILED", "REVERSED"},
    ("graph_node", "node_type"): {"CLAIMANT", "POLICY", "INCIDENT", "PROVIDER", "PAYMENT"},
    ("relationship_edge", "edge_type"): {"HOLDS_POLICY", "USED_PROVIDER", "INCIDENT_PARTY", "SHARED_ADDRESS",
                                         "SHARED_PHONE", "SHARED_EMAIL", "SHARED_BANK", "SHARED_CONTACT_PROVIDER",
                                         "PAID_TO_SHARED_ACCOUNT"},
}
for _events, (_, _, _, _moves) in LIFECYCLES.items():
    _statuses = {status for move in _moves for status in move}
    ENUMS[(_events, "from_status")] = _statuses
    ENUMS[(_events, "to_status")] = _statuses
    ENUMS[(_events, "actor_role")] = ROLES
INCIDENT_TYPES_BY_POLICY = {"AUTO": {"COLLISION", "THEFT", "INJURY"}, "HOME": {"WATER_DAMAGE", "FIRE", "THEFT"},
                            "HEALTH": {"ILLNESS", "INJURY"}}
DATE_COLUMNS = {"date_of_birth", "customer_since", "effective_from", "effective_to", "active_from", "active_to",
                "incident_date", "reported_date", "assigned_date", "invoice_date", "payment_date", "valid_from",
                "valid_to"}
STAFF_ROLES = {"OPS_ANALYST", "RISK_REVIEWER", "SYS_ADMIN"}
REASON_REQUIRED = {"DENIED", "FAILED", "REVERSED", "CLOSED", "REJECTED", "LAPSED", "CANCELLED"}


@dataclass
class CheckResult:
    check_id: str
    name: str
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures

    def as_dict(self) -> dict:
        return {"id": self.check_id, "name": self.name, "status": "PASS" if self.passed else "FAIL",
                "failure_count": len(self.failures), "examples": self.failures[:MAX_EXAMPLES]}


def _fail_rows(result: CheckResult, message: str, values) -> None:
    values = list(values)
    if values:
        result.failures += [f"{message}: {value}" for value in values]


def _key_text(frame: pd.DataFrame, columns: list[str]) -> list[str]:
    return sorted({"|".join(str(value) for value in row) for row in frame[columns].itertuples(index=False, name=None)})


# ---- V-01 to V-03

def v01_primary_keys(tables) -> CheckResult:
    result = CheckResult("V-01", "Primary-key uniqueness and ID formats")
    for table, columns in PRIMARY_KEYS.items():
        frame = tables[table]
        _fail_rows(result, f"{table} empty key", frame[frame[columns].isna().any(axis=1)].index[:MAX_EXAMPLES])
        duplicated = frame[frame.duplicated(columns, keep=False)]
        _fail_rows(result, f"{table} duplicate key", _key_text(duplicated, columns))
    for (table, column), entity in ID_FORMATS.items():
        pattern = ID_PATTERNS[entity]
        values = tables[table][column].dropna()
        _fail_rows(result, f"{table}.{column} bad format", values[~values.map(lambda v: bool(pattern.match(v)))])
    invoice = tables["invoice"]
    _fail_rows(result, "invoice ID does not contain its provider",
               invoice[invoice["invoice_id"].str[4:14] != invoice["provider_id"]]["invoice_id"])
    node = tables["graph_node"]
    prefixes = {"CLAIMANT": "CLT-", "POLICY": "POL-", "INCIDENT": "INC-", "PROVIDER": "PRV-", "PAYMENT": "PAY-"}
    wrong = [n for n, t in zip(node["node_id"], node["node_type"]) if not n.startswith(prefixes.get(t, "?"))]
    _fail_rows(result, "graph_node type does not match ID", wrong)
    return result


def v02_foreign_keys(tables) -> CheckResult:
    result = CheckResult("V-02", "Foreign-key integrity")
    for child, column, parent, parent_column, optional in FOREIGN_KEYS:
        values = tables[child][column]
        if not optional:
            _fail_rows(result, f"{child}.{column} empty", values[values.isna()].index[:MAX_EXAMPLES])
        known = set(tables[parent][parent_column])
        _fail_rows(result, f"{child}.{column} not in {parent}", sorted(set(values.dropna()) - known))
    claim = tables["claim"]
    policies = set(tables["policy"]["policy_id"])
    known_ref = claim["policy_ref"].isin(policies)
    _fail_rows(result, "claim.policy_id empty although policy_ref exists",
               claim[claim["policy_id"].isna() & known_ref]["claim_id"])
    _fail_rows(result, "claim.policy_id differs from policy_ref",
               claim[claim["policy_id"].notna() & (claim["policy_id"] != claim["policy_ref"])]["claim_id"])
    pairs = set(zip(tables["invoice"]["invoice_id"], tables["invoice"]["claim_id"]))
    payment = tables["payment"]
    _fail_rows(result, "payment invoice belongs to another claim",
               [p for p, i, c in zip(payment["payment_id"], payment["invoice_id"], payment["claim_id"]) if (i, c) not in pairs])
    payee_ok = (((payment["payee_type"] == "CLAIMANT") & payment["payee_claimant_id"].notna() & payment["payee_provider_id"].isna())
                | ((payment["payee_type"] == "PROVIDER") & payment["payee_provider_id"].notna() & payment["payee_claimant_id"].isna()))
    _fail_rows(result, "payment payee does not match payee_type", payment[~payee_ok]["payment_id"])
    claimant_holds = set(zip(tables["claimant_policy"]["claimant_id"], tables["claimant_policy"]["policy_id"]))
    with_policy = claim[claim["policy_id"].notna()]
    _fail_rows(result, "claimant is not on the claimed policy",
               [c for c, k, p in zip(with_policy["claim_id"], with_policy["claimant_id"], with_policy["policy_id"])
                if (k, p) not in claimant_holds])
    bridge = tables["claimant_policy"]
    holders = bridge[bridge["role"] == "POLICYHOLDER"].groupby("policy_id").size()
    _fail_rows(result, "policy without exactly one policyholder",
               sorted(set(tables["policy"]["policy_id"]) - set(holders[holders == 1].index)))
    pairs = set(zip(tables["claim_provider"]["claim_id"], tables["claim_provider"]["provider_id"]))
    invoice = tables["invoice"]
    _fail_rows(result, "invoice claim-provider pair missing from claim_provider",
               [i for i, c, p in zip(invoice["invoice_id"], invoice["claim_id"], invoice["provider_id"]) if (c, p) not in pairs])
    return result


def v03_enums(tables) -> CheckResult:
    result = CheckResult("V-03", "Allowed values")
    for (table, column), allowed in ENUMS.items():
        values = tables[table][column].dropna()
        _fail_rows(result, f"{table}.{column} not allowed", sorted(set(values) - allowed, key=str))
    return result


# ---- V-04 dates

def _bad_dates(values: pd.Series) -> list[str]:
    bad = []
    for value in values.dropna().unique():
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError
            date.fromisoformat(value)
        except ValueError:
            bad.append(value)
    return bad


def v04_dates(tables) -> CheckResult:
    result = CheckResult("V-04", "Date ordering")
    for table, frame in tables.items():
        for column in frame.columns:
            if column in DATE_COLUMNS:
                _fail_rows(result, f"{table}.{column} not a valid date", _bad_dates(frame[column]))
            if column == "event_at":
                bad = frame[~frame[column].str.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")]
                _fail_rows(result, f"{table}.event_at bad format", bad["event_id"])
                _fail_rows(result, f"{table} event after as-of date", frame[frame[column].str[:10] > AS_OF]["event_id"])

    claimant = tables["claimant"]
    birth = pd.to_datetime(claimant["date_of_birth"])
    age = (pd.Timestamp(AS_OF) - birth).dt.days / 365.25
    _fail_rows(result, "claimant age outside 18-95", claimant[(age < 18) | (age > 96)]["claimant_id"])
    since = pd.to_datetime(claimant["customer_since"])
    _fail_rows(result, "customer before age 18 or after as-of",
               claimant[(since < birth + pd.DateOffset(years=18)) | (claimant["customer_since"] > AS_OF)]["claimant_id"])

    contact = tables["claimant_contact"]
    _fail_rows(result, "contact period ends before it starts",
               contact[contact["effective_to"].notna() & (contact["effective_to"] < contact["effective_from"])]["contact_id"])
    for claimant_id, rows in contact.sort_values(["claimant_id", "effective_from"]).groupby("claimant_id"):
        if rows["effective_to"].isna().sum() != 1 or pd.notna(rows["effective_to"].iloc[-1]):
            result.failures.append(f"claimant does not have exactly one open, latest contact: {claimant_id}")
        ends, starts = rows["effective_to"].iloc[:-1].tolist(), rows["effective_from"].iloc[1:].tolist()
        if any(end >= start for end, start in zip(ends, starts)):
            result.failures.append(f"contact periods overlap: {claimant_id}")

    provider = tables["provider"]
    _fail_rows(result, "provider active dates out of order",
               provider[(provider["active_from"] > AS_OF)
                        | (provider["active_to"].notna() & (provider["active_to"] < provider["active_from"]))]["provider_id"])
    policy = tables["policy"]
    _fail_rows(result, "policy ends before it starts", policy[policy["effective_to"] <= policy["effective_from"]]["policy_id"])
    bridge = tables["claimant_policy"].merge(policy, on="policy_id", suffixes=("", "_policy"))
    _fail_rows(result, "claimant_policy period outside the policy",
               bridge[(bridge["effective_from"] < bridge["effective_from_policy"])
                      | (bridge["effective_to"] > bridge["effective_to_policy"])]["policy_id"])

    incident = tables["incident"]
    _fail_rows(result, "incident outside the incident window",
               incident[~incident["incident_date"].between(*WINDOW)]["incident_id"])
    claim = tables["claim"].merge(incident[["incident_id", "incident_date"]], on="incident_id")
    _fail_rows(result, "claim reported before the incident or after as-of",
               claim[(claim["reported_date"] < claim["incident_date"]) | (claim["reported_date"] > AS_OF)]["claim_id"])
    invoice = tables["invoice"].merge(claim[["claim_id", "incident_date"]], on="claim_id").merge(
        provider[["provider_id", "active_from", "active_to"]], on="provider_id")
    _fail_rows(result, "invoice before the incident or after as-of",
               invoice[(invoice["invoice_date"] < invoice["incident_date"]) | (invoice["invoice_date"] > AS_OF)]["invoice_id"])
    _fail_rows(result, "invoice while provider inactive",
               invoice[(invoice["invoice_date"] < invoice["active_from"])
                       | (invoice["active_to"].notna() & (invoice["invoice_date"] > invoice["active_to"]))]["invoice_id"])

    events = tables["claim_events"]
    approved = events[events["to_status"] == "APPROVED"].set_index("claim_id")["event_at"].str[:10]
    payment = tables["payment"].assign(approved_on=lambda t: t["claim_id"].map(approved))
    _fail_rows(result, "payment before claim approval or after as-of",
               payment[payment["approved_on"].isna() | (payment["payment_date"] < payment["approved_on"])
                       | (payment["payment_date"] > AS_OF)]["payment_id"])
    first = events[events["seq"] == 1].set_index("claim_id")["event_at"].str[:10]
    _fail_rows(result, "first claim event is not on the reported date",
               tables["claim"][tables["claim"]["claim_id"].map(first) != tables["claim"]["reported_date"]]["claim_id"])
    edge = tables["relationship_edge"]
    _fail_rows(result, "edge ends before it starts",
               edge[edge["valid_to"].notna() & (edge["valid_to"] < edge["valid_from"])]["edge_id"])
    return result


# ---- V-05 arithmetic

def v05_arithmetic(tables) -> CheckResult:
    result = CheckResult("V-05", "Arithmetic reconciliation")
    line = tables["invoice_line"]
    _fail_rows(result, "line amount is not quantity x unit price",
               line[line["line_amount_cents"] != line["quantity"] * line["unit_price_cents"]]["invoice_id"].unique())
    totals = line.groupby("invoice_id")["line_amount_cents"].sum()
    covered = line[line["is_covered"] == 1].groupby("invoice_id")["line_amount_cents"].sum()
    invoice = tables["invoice"].set_index("invoice_id")
    _fail_rows(result, "invoice total is not the sum of lines",
               invoice.index[invoice["total_cents"] != totals.reindex(invoice.index).fillna(0)])
    _fail_rows(result, "invoice covered amount is not the sum of covered lines",
               invoice.index[invoice["covered_cents"] != covered.reindex(invoice.index).fillna(0)])

    claim = tables["claim"].set_index("claim_id")
    claimed = tables["invoice"].groupby("claim_id")["total_cents"].sum().reindex(claim.index).fillna(0)
    _fail_rows(result, "claimed amount is not the sum of invoice totals", claim.index[claim["claimed_amount_cents"] != claimed])
    payment = tables["payment"]
    paid = payment[payment["current_status"] == "SETTLED"].groupby("claim_id")["amount_cents"].sum()
    _fail_rows(result, "paid amount is not settled payments",
               claim.index[claim["paid_amount_cents"] != paid.reindex(claim.index).fillna(0)])
    _fail_rows(result, "balance is not approved minus paid",
               claim.index[claim["balance_cents"] != claim["approved_amount_cents"] - claim["paid_amount_cents"]])

    events = tables["claim_events"]
    was_approved = set(events[events["to_status"] == "APPROVED"]["claim_id"])
    active = tables["invoice"][tables["invoice"]["current_status"] != "REJECTED"]
    active_covered = active.groupby("claim_id")["covered_cents"].sum()
    policy = tables["policy"].set_index("policy_id")
    incident = tables["incident"].set_index("incident_id")["incident_date"]
    for claim_id, row in claim.iterrows():
        if pd.isna(row["policy_id"]):
            expected = 0
            if pd.notna(row["days_policy_start_to_incident"]):
                result.failures.append(f"day gap set without a policy: {claim_id}")
        else:
            terms = policy.loc[row["policy_id"]]
            expected = (max(0, min(int(active_covered.get(claim_id, 0)), int(terms["coverage_limit_cents"]))
                            - int(terms["deductible_cents"])) if claim_id in was_approved else 0)
            gap = (date.fromisoformat(incident[row["incident_id"]]) - date.fromisoformat(terms["effective_from"])).days
            if row["days_policy_start_to_incident"] != gap:
                result.failures.append(f"days from policy start is wrong: {claim_id}")
        if row["approved_amount_cents"] != expected:
            result.failures.append(f"approved amount does not follow the formula: {claim_id}")
        report_gap = (date.fromisoformat(row["reported_date"]) - date.fromisoformat(incident[row["incident_id"]])).days
        if row["days_incident_to_report"] != report_gap:
            result.failures.append(f"days to report is wrong: {claim_id}")
    return result


# ---- V-06 lifecycles

def v06_lifecycles(tables) -> CheckResult:
    result = CheckResult("V-06", "Lifecycle transitions")
    for events_table, (parent, column, start, allowed) in LIFECYCLES.items():
        events = tables[events_table].sort_values([column, "seq"])
        _fail_rows(result, f"{parent} without events", sorted(set(tables[parent][column]) - set(events[column])))
        previous = events.groupby(column).shift(1)
        first = events["seq"] == 1
        position = events.groupby(column).cumcount() + 1
        _fail_rows(result, f"{events_table} seq has gaps", events[events["seq"] != position]["event_id"])
        _fail_rows(result, f"{events_table} does not start at {start}",
                   events[first & ((events["to_status"] != start) | events["from_status"].notna())]["event_id"])
        later = events[~first]
        _fail_rows(result, f"{events_table} from_status is not the previous status",
                   later[later["from_status"] != previous.loc[later.index, "to_status"]]["event_id"])
        moves = list(zip(later["from_status"], later["to_status"]))
        _fail_rows(result, f"{events_table} transition not allowed",
                   [e for e, move in zip(later["event_id"], moves) if move not in allowed])
        _fail_rows(result, f"{events_table} event earlier than the one before",
                   later[later["event_at"] < previous.loc[later.index, "event_at"]]["event_id"])
        latest = events.groupby(column)["to_status"].last()
        current = tables[parent].set_index(column)["current_status"]
        _fail_rows(result, f"{parent} current_status is not the latest event",
                   current.index[current != latest.reindex(current.index)])
        _fail_rows(result, f"{events_table} staff event without actor_id",
                   events[events["actor_role"].isin(STAFF_ROLES) & events["actor_id"].isna()]["event_id"])
        _fail_rows(result, f"{events_table} change without a reason",
                   events[events["to_status"].isin(REASON_REQUIRED) & events["reason_code"].isna()]["event_id"])
    return result


# ---- V-07 to V-12

def v07_duplicates(tables) -> CheckResult:
    result = CheckResult("V-07", "Duplicate checks")
    for table, columns in (("claimant_policy", ["claimant_id", "policy_id"]),
                           ("claim_provider", ["claim_id", "provider_id", "service_role"]),
                           ("relationship_edge", ["source_node_id", "target_node_id", "edge_type"]),
                           ("invoice", ["invoice_id"]), ("graph_node", ["node_id"])):
        frame = tables[table]
        _fail_rows(result, f"{table} repeated {'+'.join(columns)}", _key_text(frame[frame.duplicated(columns)], columns))
    edge = tables["relationship_edge"]
    pair = edge[edge["edge_type"].isin({"SHARED_ADDRESS", "SHARED_PHONE", "SHARED_EMAIL", "SHARED_BANK"})]
    _fail_rows(result, "claimant pair edge not stored smaller ID first",
               pair[pair["source_node_id"] >= pair["target_node_id"]]["edge_id"])
    _fail_rows(result, "edge links a node to itself", edge[edge["source_node_id"] == edge["target_node_id"]]["edge_id"])
    return result


def _canonical(rows) -> list[tuple]:
    return sorted(tuple("" if value is None or pd.isna(value) else str(value) for value in row) for row in rows)


def v08_cross_file(tables, input_dir: Path, manifest: dict) -> tuple[CheckResult, sqlite3.Connection]:
    """CSV, JSON and SQL hold identical rows, and every file matches its manifest checksum."""
    import hashlib

    result = CheckResult("V-08", "Cross-file consistency")
    for item in manifest["files"]:
        data = (input_dir / item["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            result.failures.append(f"file does not match its manifest checksum: {item['path']}")
    connection = sqlite3.connect(":memory:")
    connection.executescript((input_dir / "sql/schema.sql").read_text(encoding="utf-8"))
    connection.executescript((input_dir / "sql/seed.sql").read_text(encoding="utf-8"))
    for name, frame in tables.items():
        csv_rows = _canonical(frame.itertuples(index=False, name=None))
        records = json.loads((input_dir / "json" / f"{name}.json").read_text(encoding="utf-8"))
        json_rows = _canonical([record[column] for column in frame.columns] for record in records)
        sql_rows = _canonical(connection.execute(f"SELECT {', '.join(frame.columns)} FROM {name}"))
        if json_rows != csv_rows:
            result.failures.append(f"JSON rows differ from CSV: {name}")
        if sql_rows != csv_rows:
            result.failures.append(f"SQL rows differ from CSV: {name}")
    return result, connection


def v09_volume(tables, manifest: dict) -> CheckResult:
    result = CheckResult("V-09", "Volume")
    generator = manifest.get("generator")
    if not generator:
        result.failures.append("input manifest does not record the generator seed and scale")
        return result
    config = GeneratorConfig(seed=generator["seed"], scale=generator["scale"])
    for table in ("claim", "claimant", "provider"):
        if len(tables[table]) != config.count(table):
            result.failures.append(f"{table}: {len(tables[table])} rows, expected {config.count(table)}")
    minimum = round(MIN_EDGES_PER_SCALE * config.scale)
    if len(tables["relationship_edge"]) < minimum:
        result.failures.append(f"relationship_edge: {len(tables['relationship_edge'])} rows, at least {minimum} expected")
    return result


def coverage_counts(tables) -> dict[str, int]:
    """How many records of each required normal, boundary, failure and exception type exist."""
    claim, payment, invoice = tables["claim"], tables["payment"], tables["invoice"]
    events, lines = tables["claim_events"], tables["invoice_line"]
    joined = claim.merge(tables["incident"], on="incident_id").merge(tables["policy"], on="policy_id",
                                                                      suffixes=("", "_policy"))
    covered = invoice.groupby("claim_id")["covered_cents"].sum()
    joined = joined.assign(covered=joined["claim_id"].map(covered))
    return {
        "normal: paid then closed": int(((events["from_status"] == "PAID") & (events["to_status"] == "CLOSED")).sum()),
        "boundary: incident on first policy day": int((joined["incident_date"] == joined["effective_from"]).sum()),
        "boundary: incident on last policy day": int((joined["incident_date"] == joined["effective_to"]).sum()),
        "boundary: paid exactly the approved amount": int(((claim["approved_amount_cents"] > 0) & (claim["balance_cents"] == 0)).sum()),
        "boundary: loss equals deductible": int((joined["covered"] == joined["deductible_cents"]).sum()),
        "boundary: single-line invoice": int((lines.groupby("invoice_id").size() == 1).sum()),
        "boundary: reported on incident date": int((claim["days_incident_to_report"] == 0).sum()),
        "failure: failed payment": int((payment["current_status"] == "FAILED").sum()),
        "failure: reversed payment": int((payment["current_status"] == "REVERSED").sum()),
        "failure: rejected invoice": int((invoice["current_status"] == "REJECTED").sum()),
        "failure: withdrawn claim": int((events["to_status"] == "WITHDRAWN").sum()),
        "failure: denied claim": int((events["to_status"] == "DENIED").sum()),
        "failure: lapsed policy": int((tables["policy_events"]["to_status"] == "LAPSED").sum()),
        "open work: claim under review": int((claim["current_status"] == "UNDER_REVIEW").sum()),
        "exception: claim without a known policy": int(claim["policy_id"].isna().sum()),
        "exception: paid above approved": int((claim["paid_amount_cents"] > claim["approved_amount_cents"]).sum()),
        "exception: repeated provider invoice number": int(invoice["external_invoice_no"].duplicated().sum()),
    }


def v10_coverage(tables) -> CheckResult:
    result = CheckResult("V-10", "Coverage of normal, boundary, failure and exception cases")
    _fail_rows(result, "no records of type", [name for name, count in coverage_counts(tables).items() if count == 0])
    return result


def v11_joins(tables, connection: sqlite3.Connection) -> CheckResult:
    result = CheckResult("V-11", "Valid joins")
    connection.execute("PRAGMA foreign_keys = ON")
    broken = connection.execute("PRAGMA foreign_key_check").fetchall()
    _fail_rows(result, "SQL seed foreign key problem", broken[:MAX_EXAMPLES])
    claim = tables["claim"]
    joins = {
        "claim to incident and claimant": len(claim.merge(tables["incident"], on="incident_id")
                                              .merge(tables["claimant"], on="claimant_id")) == len(claim),
        "claim to policy loses only claims without a policy":
            len(claim.merge(tables["policy"], on="policy_id")) == int(claim["policy_id"].notna().sum()),
        "invoice to claim and provider": len(tables["invoice"].merge(claim[["claim_id"]], on="claim_id")
                                             .merge(tables["provider"][["provider_id"]], on="provider_id")) == len(tables["invoice"]),
        "invoice line to invoice": len(tables["invoice_line"].merge(tables["invoice"][["invoice_id"]], on="invoice_id"))
                                   == len(tables["invoice_line"]),
        "payment to invoice on the same claim": len(tables["payment"].merge(tables["invoice"][["invoice_id", "claim_id"]],
                                                                            on=["invoice_id", "claim_id"])) == len(tables["payment"]),
        "edge to both nodes": len(tables["relationship_edge"]
                                  .merge(tables["graph_node"], left_on="source_node_id", right_on="node_id")
                                  .merge(tables["graph_node"], left_on="target_node_id", right_on="node_id"))
                              == len(tables["relationship_edge"]),
    }
    _fail_rows(result, "join loses rows", [name for name, ok in joins.items() if not ok])
    return result


def v12_synthetic(tables) -> CheckResult:
    result = CheckResult("V-12", "Synthetic-only data")
    formats = {"phone": r"555-\d{3}-\d{4}", "email": r"[a-z.]+\.\d{6}@example\.(com|org|net)|billing\.\d{6}@example\.(com|org|net)",
               "bank_token": r"ACCT-\d{8}", "postal_code": r"\d{5}"}
    for table in ("claimant_contact", "provider"):
        for column, pattern in formats.items():
            values = tables[table][column].dropna()
            _fail_rows(result, f"{table}.{column} is not a fictional format", values[~values.str.fullmatch(pattern)])
    tokens = tables["payment"]["payee_bank_token"]
    _fail_rows(result, "payment bank token is not a fictional format", tokens[~tokens.str.fullmatch(r"ACCT-\d{8}")])
    vehicles = tables["incident"]["vehicle_ref"].dropna()
    _fail_rows(result, "vehicle reference is not a fictional format", vehicles[~vehicles.str.fullmatch(r"VEH-\d{6}")])
    return result


def run_checks(tables: dict[str, pd.DataFrame], input_dir: Path, manifest: dict) -> list[CheckResult]:
    missing = sorted(set(PRIMARY_KEYS) - set(tables))
    if missing:
        return [CheckResult("V-00", "All input tables present", [f"missing table: {name}" for name in missing])]
    cross_file, connection = v08_cross_file(tables, Path(input_dir), manifest)
    try:
        return [v01_primary_keys(tables), v02_foreign_keys(tables), v03_enums(tables), v04_dates(tables),
                v05_arithmetic(tables), v06_lifecycles(tables), v07_duplicates(tables), cross_file,
                v09_volume(tables, manifest), v10_coverage(tables), v11_joins(tables, connection), v12_synthetic(tables)]
    finally:
        connection.close()

