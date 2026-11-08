"""SQLite schema, in parent-before-child order. See docs/DATA_DICTIONARY.md.

Some rules are deliberately left to the validator, because the required edge cases must load:
- claim.policy_ref has no foreign key (EC-1 refers to a policy that does not exist).
- payments may exceed the approved amount (EC-2), so balance can be negative.
- external_invoice_no is not unique (EC-3).
- relationship_edge is a recorded register, so a link missing from it (EC-4) is not an error here.
"""
from __future__ import annotations

ACTOR_ROLES = "('CUSTOMER', 'OPS_ANALYST', 'RISK_REVIEWER', 'SYS_ADMIN', 'SYSTEM')"
_DIGITS_6 = "[0-9]" * 6
_DIGITS_8 = "[0-9]" * 8


def _events_table(table: str, event_prefix: str, parent_column: str, parent_table: str, statuses: str) -> str:
    return f"""CREATE TABLE {table} (
    event_id TEXT PRIMARY KEY CHECK (event_id GLOB '{event_prefix}-{_DIGITS_8}'),
    {parent_column} TEXT NOT NULL REFERENCES {parent_table} ({parent_column}),
    seq INTEGER NOT NULL CHECK (seq >= 1),
    from_status TEXT CHECK (from_status IN {statuses}),
    to_status TEXT NOT NULL CHECK (to_status IN {statuses}),
    event_at TEXT NOT NULL,
    actor_role TEXT NOT NULL CHECK (actor_role IN {ACTOR_ROLES}),
    actor_id TEXT,
    reason_code TEXT,
    UNIQUE ({parent_column}, seq),
    CHECK ((seq = 1) = (from_status IS NULL))
) STRICT;"""


POLICY_STATUSES = "('ACTIVE', 'LAPSED', 'CANCELLED', 'EXPIRED')"
CLAIM_STATUSES = "('SUBMITTED', 'UNDER_REVIEW', 'APPROVED', 'DENIED', 'WITHDRAWN', 'PAID', 'CLOSED')"
INVOICE_STATUSES = "('RECEIVED', 'VERIFIED', 'APPROVED', 'REJECTED', 'PAID')"
PAYMENT_STATUSES = "('INITIATED', 'SETTLED', 'FAILED', 'REVERSED')"
CLAIMANT_PAIR_EDGE_TYPES = "('SHARED_ADDRESS', 'SHARED_PHONE', 'SHARED_EMAIL', 'SHARED_BANK')"
EDGE_TYPES = ("('HOLDS_POLICY', 'USED_PROVIDER', 'INCIDENT_PARTY', 'SHARED_ADDRESS', 'SHARED_PHONE', 'SHARED_EMAIL', "
              "'SHARED_BANK', 'SHARED_CONTACT_PROVIDER', 'PAID_TO_SHARED_ACCOUNT')")

TABLES = {
    "claimant": f"""CREATE TABLE claimant (
    claimant_id TEXT PRIMARY KEY CHECK (claimant_id GLOB 'CLT-{_DIGITS_6}'),
    full_name TEXT NOT NULL CHECK (full_name <> ''),
    date_of_birth TEXT NOT NULL,
    customer_since TEXT NOT NULL,
    CHECK (date_of_birth < customer_since)
) STRICT;""",
    "claimant_contact": f"""CREATE TABLE claimant_contact (
    contact_id TEXT PRIMARY KEY CHECK (contact_id GLOB 'CON-{_DIGITS_6}'),
    claimant_id TEXT NOT NULL REFERENCES claimant (claimant_id),
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    address_line TEXT NOT NULL,
    city TEXT NOT NULL,
    postal_code TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT NOT NULL,
    bank_token TEXT,
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
) STRICT;""",
    "provider": f"""CREATE TABLE provider (
    provider_id TEXT PRIMARY KEY CHECK (provider_id GLOB 'PRV-{_DIGITS_6}'),
    provider_name TEXT NOT NULL,
    provider_type TEXT NOT NULL CHECK (provider_type IN ('REPAIRER', 'MEDICAL', 'SERVICE')),
    address_line TEXT NOT NULL,
    city TEXT NOT NULL,
    postal_code TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT NOT NULL,
    bank_token TEXT NOT NULL,
    active_from TEXT NOT NULL,
    active_to TEXT,
    CHECK (active_to IS NULL OR active_to >= active_from)
) STRICT;""",
    "policy": f"""CREATE TABLE policy (
    policy_id TEXT PRIMARY KEY CHECK (policy_id GLOB 'POL-{_DIGITS_6}'),
    policy_type TEXT NOT NULL CHECK (policy_type IN ('AUTO', 'HOME', 'HEALTH')),
    effective_from TEXT NOT NULL,
    effective_to TEXT NOT NULL,
    coverage_limit_cents INTEGER NOT NULL CHECK (coverage_limit_cents > 0),
    deductible_cents INTEGER NOT NULL CHECK (deductible_cents >= 0),
    current_status TEXT NOT NULL CHECK (current_status IN {POLICY_STATUSES}),
    CHECK (effective_from < effective_to),
    CHECK (coverage_limit_cents > deductible_cents)
) STRICT;""",
    "claimant_policy": """CREATE TABLE claimant_policy (
    claimant_id TEXT NOT NULL REFERENCES claimant (claimant_id),
    policy_id TEXT NOT NULL REFERENCES policy (policy_id),
    role TEXT NOT NULL CHECK (role IN ('POLICYHOLDER', 'NAMED_INSURED')),
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    PRIMARY KEY (claimant_id, policy_id)
) STRICT;""",
    "policy_events": _events_table("policy_events", "PEV", "policy_id", "policy", POLICY_STATUSES),
    "incident": f"""CREATE TABLE incident (
    incident_id TEXT PRIMARY KEY CHECK (incident_id GLOB 'INC-2026-{_DIGITS_6}'),
    incident_type TEXT NOT NULL CHECK (incident_type IN
        ('COLLISION', 'THEFT', 'INJURY', 'WATER_DAMAGE', 'FIRE', 'ILLNESS')),
    incident_date TEXT NOT NULL,
    city TEXT NOT NULL,
    postal_code TEXT NOT NULL,
    narrative TEXT NOT NULL CHECK (narrative <> ''),
    vehicle_ref TEXT
) STRICT;""",
    "claim": f"""CREATE TABLE claim (
    claim_id TEXT PRIMARY KEY CHECK (claim_id GLOB 'CLM-2026-{_DIGITS_6}'),
    incident_id TEXT NOT NULL REFERENCES incident (incident_id),
    claimant_id TEXT NOT NULL REFERENCES claimant (claimant_id),
    policy_ref TEXT NOT NULL,
    policy_id TEXT REFERENCES policy (policy_id),
    reported_date TEXT NOT NULL,
    claimed_amount_cents INTEGER NOT NULL CHECK (claimed_amount_cents >= 0),
    approved_amount_cents INTEGER NOT NULL CHECK (approved_amount_cents >= 0),
    paid_amount_cents INTEGER NOT NULL CHECK (paid_amount_cents >= 0),
    balance_cents INTEGER NOT NULL,
    days_incident_to_report INTEGER NOT NULL CHECK (days_incident_to_report >= 0),
    days_policy_start_to_incident INTEGER,
    current_status TEXT NOT NULL CHECK (current_status IN {CLAIM_STATUSES}),
    CHECK (policy_id IS NULL OR policy_id = policy_ref),
    CHECK (balance_cents = approved_amount_cents - paid_amount_cents)
) STRICT;""",
    "claim_events": _events_table("claim_events", "CEV", "claim_id", "claim", CLAIM_STATUSES),
    "claim_provider": """CREATE TABLE claim_provider (
    claim_id TEXT NOT NULL REFERENCES claim (claim_id),
    provider_id TEXT NOT NULL REFERENCES provider (provider_id),
    service_role TEXT NOT NULL CHECK (service_role IN ('REPAIR', 'MEDICAL', 'TOWING', 'LEGAL')),
    assigned_date TEXT NOT NULL,
    PRIMARY KEY (claim_id, provider_id, service_role)
) STRICT;""",
    "invoice": f"""CREATE TABLE invoice (
    invoice_id TEXT PRIMARY KEY CHECK (invoice_id GLOB 'INV-PRV-{_DIGITS_6}-{_DIGITS_6}'),
    provider_id TEXT NOT NULL REFERENCES provider (provider_id),
    claim_id TEXT NOT NULL REFERENCES claim (claim_id),
    external_invoice_no TEXT NOT NULL,
    invoice_date TEXT NOT NULL,
    total_cents INTEGER NOT NULL CHECK (total_cents > 0),
    covered_cents INTEGER NOT NULL CHECK (covered_cents >= 0),
    current_status TEXT NOT NULL CHECK (current_status IN {INVOICE_STATUSES}),
    UNIQUE (invoice_id, claim_id),
    CHECK (substr(invoice_id, 5, 10) = provider_id),
    CHECK (covered_cents <= total_cents)
) STRICT;""",
    "invoice_line": """CREATE TABLE invoice_line (
    invoice_id TEXT NOT NULL REFERENCES invoice (invoice_id),
    line_no INTEGER NOT NULL CHECK (line_no >= 1),
    service_code TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity >= 1),
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents > 0),
    line_amount_cents INTEGER NOT NULL,
    is_covered INTEGER NOT NULL CHECK (is_covered IN (0, 1)),
    PRIMARY KEY (invoice_id, line_no),
    CHECK (line_amount_cents = quantity * unit_price_cents)
) STRICT;""",
    "invoice_events": _events_table("invoice_events", "IEV", "invoice_id", "invoice", INVOICE_STATUSES),
    "payment": f"""CREATE TABLE payment (
    payment_id TEXT PRIMARY KEY CHECK (payment_id GLOB 'PAY-2026-{_DIGITS_6}'),
    claim_id TEXT NOT NULL,
    invoice_id TEXT NOT NULL,
    payee_type TEXT NOT NULL CHECK (payee_type IN ('CLAIMANT', 'PROVIDER')),
    payee_claimant_id TEXT REFERENCES claimant (claimant_id),
    payee_provider_id TEXT REFERENCES provider (provider_id),
    payee_bank_token TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    payment_date TEXT NOT NULL,
    current_status TEXT NOT NULL CHECK (current_status IN {PAYMENT_STATUSES}),
    FOREIGN KEY (invoice_id, claim_id) REFERENCES invoice (invoice_id, claim_id),
    CHECK ((payee_type = 'CLAIMANT' AND payee_claimant_id IS NOT NULL AND payee_provider_id IS NULL)
        OR (payee_type = 'PROVIDER' AND payee_provider_id IS NOT NULL AND payee_claimant_id IS NULL))
) STRICT;""",
    "payment_events": _events_table("payment_events", "YEV", "payment_id", "payment", PAYMENT_STATUSES),
    # One node per real entity, so edge endpoints have a true foreign key. Node IDs are the entity IDs.
    "graph_node": """CREATE TABLE graph_node (
    node_id TEXT PRIMARY KEY,
    node_type TEXT NOT NULL CHECK (node_type IN ('CLAIMANT', 'POLICY', 'INCIDENT', 'PROVIDER', 'PAYMENT')),
    CHECK ((node_type = 'CLAIMANT' AND node_id GLOB 'CLT-*') OR (node_type = 'POLICY' AND node_id GLOB 'POL-*')
        OR (node_type = 'INCIDENT' AND node_id GLOB 'INC-*') OR (node_type = 'PROVIDER' AND node_id GLOB 'PRV-*')
        OR (node_type = 'PAYMENT' AND node_id GLOB 'PAY-*'))
) STRICT;""",
    "relationship_edge": f"""CREATE TABLE relationship_edge (
    edge_id TEXT PRIMARY KEY CHECK (edge_id GLOB 'EDG-{_DIGITS_6}'),
    source_node_id TEXT NOT NULL REFERENCES graph_node (node_id),
    target_node_id TEXT NOT NULL REFERENCES graph_node (node_id),
    edge_type TEXT NOT NULL CHECK (edge_type IN {EDGE_TYPES}),
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    source_ref TEXT NOT NULL CHECK (source_ref GLOB '*:*.*'),
    UNIQUE (source_node_id, target_node_id, edge_type),
    CHECK (source_node_id <> target_node_id),
    CHECK (valid_to IS NULL OR valid_to >= valid_from),
    CHECK (edge_type NOT IN {CLAIMANT_PAIR_EDGE_TYPES} OR source_node_id < target_node_id)
) STRICT;""",
}

EVENT_TABLES = tuple(name for name in TABLES if name.endswith("_events"))


def _append_only_triggers(table: str) -> str:
    return "\n".join(
        f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table}\n"
        f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;"
        for action in ("UPDATE", "DELETE")
    )


def schema_sql() -> str:
    parts = ["-- Fraud-network input data schema. Synthetic data only.", "PRAGMA foreign_keys = ON;"]
    parts += TABLES.values()
    parts += [_append_only_triggers(table) for table in EVENT_TABLES]
    return "\n\n".join(parts) + "\n"
