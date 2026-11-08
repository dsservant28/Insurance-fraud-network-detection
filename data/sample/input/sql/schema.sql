-- Fraud-network input data schema. Synthetic data only.

PRAGMA foreign_keys = ON;

CREATE TABLE claimant (
    claimant_id TEXT PRIMARY KEY CHECK (claimant_id GLOB 'CLT-[0-9][0-9][0-9][0-9][0-9][0-9]'),
    full_name TEXT NOT NULL CHECK (full_name <> ''),
    date_of_birth TEXT NOT NULL,
    customer_since TEXT NOT NULL,
    CHECK (date_of_birth < customer_since)
) STRICT;

CREATE TABLE claimant_contact (
    contact_id TEXT PRIMARY KEY CHECK (contact_id GLOB 'CON-[0-9][0-9][0-9][0-9][0-9][0-9]'),
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
) STRICT;

CREATE TABLE provider (
    provider_id TEXT PRIMARY KEY CHECK (provider_id GLOB 'PRV-[0-9][0-9][0-9][0-9][0-9][0-9]'),
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
) STRICT;

CREATE TABLE policy (
    policy_id TEXT PRIMARY KEY CHECK (policy_id GLOB 'POL-[0-9][0-9][0-9][0-9][0-9][0-9]'),
    policy_type TEXT NOT NULL CHECK (policy_type IN ('AUTO', 'HOME', 'HEALTH')),
    effective_from TEXT NOT NULL,
    effective_to TEXT NOT NULL,
    coverage_limit_cents INTEGER NOT NULL CHECK (coverage_limit_cents > 0),
    deductible_cents INTEGER NOT NULL CHECK (deductible_cents >= 0),
    current_status TEXT NOT NULL CHECK (current_status IN ('ACTIVE', 'LAPSED', 'CANCELLED', 'EXPIRED')),
    CHECK (effective_from < effective_to),
    CHECK (coverage_limit_cents > deductible_cents)
) STRICT;

CREATE TABLE claimant_policy (
    claimant_id TEXT NOT NULL REFERENCES claimant (claimant_id),
    policy_id TEXT NOT NULL REFERENCES policy (policy_id),
    role TEXT NOT NULL CHECK (role IN ('POLICYHOLDER', 'NAMED_INSURED')),
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    PRIMARY KEY (claimant_id, policy_id)
) STRICT;

CREATE TABLE policy_events (
    event_id TEXT PRIMARY KEY CHECK (event_id GLOB 'PEV-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'),
    policy_id TEXT NOT NULL REFERENCES policy (policy_id),
    seq INTEGER NOT NULL CHECK (seq >= 1),
    from_status TEXT CHECK (from_status IN ('ACTIVE', 'LAPSED', 'CANCELLED', 'EXPIRED')),
    to_status TEXT NOT NULL CHECK (to_status IN ('ACTIVE', 'LAPSED', 'CANCELLED', 'EXPIRED')),
    event_at TEXT NOT NULL,
    actor_role TEXT NOT NULL CHECK (actor_role IN ('CUSTOMER', 'OPS_ANALYST', 'RISK_REVIEWER', 'SYS_ADMIN', 'SYSTEM')),
    actor_id TEXT,
    reason_code TEXT,
    UNIQUE (policy_id, seq),
    CHECK ((seq = 1) = (from_status IS NULL))
) STRICT;

CREATE TABLE incident (
    incident_id TEXT PRIMARY KEY CHECK (incident_id GLOB 'INC-2026-[0-9][0-9][0-9][0-9][0-9][0-9]'),
    incident_type TEXT NOT NULL CHECK (incident_type IN
        ('COLLISION', 'THEFT', 'INJURY', 'WATER_DAMAGE', 'FIRE', 'ILLNESS')),
    incident_date TEXT NOT NULL,
    city TEXT NOT NULL,
    postal_code TEXT NOT NULL,
    narrative TEXT NOT NULL CHECK (narrative <> ''),
    vehicle_ref TEXT
) STRICT;

CREATE TABLE claim (
    claim_id TEXT PRIMARY KEY CHECK (claim_id GLOB 'CLM-2026-[0-9][0-9][0-9][0-9][0-9][0-9]'),
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
    current_status TEXT NOT NULL CHECK (current_status IN ('SUBMITTED', 'UNDER_REVIEW', 'APPROVED', 'DENIED', 'WITHDRAWN', 'PAID', 'CLOSED')),
    CHECK (policy_id IS NULL OR policy_id = policy_ref),
    CHECK (balance_cents = approved_amount_cents - paid_amount_cents)
) STRICT;

CREATE TABLE claim_events (
    event_id TEXT PRIMARY KEY CHECK (event_id GLOB 'CEV-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'),
    claim_id TEXT NOT NULL REFERENCES claim (claim_id),
    seq INTEGER NOT NULL CHECK (seq >= 1),
    from_status TEXT CHECK (from_status IN ('SUBMITTED', 'UNDER_REVIEW', 'APPROVED', 'DENIED', 'WITHDRAWN', 'PAID', 'CLOSED')),
    to_status TEXT NOT NULL CHECK (to_status IN ('SUBMITTED', 'UNDER_REVIEW', 'APPROVED', 'DENIED', 'WITHDRAWN', 'PAID', 'CLOSED')),
    event_at TEXT NOT NULL,
    actor_role TEXT NOT NULL CHECK (actor_role IN ('CUSTOMER', 'OPS_ANALYST', 'RISK_REVIEWER', 'SYS_ADMIN', 'SYSTEM')),
    actor_id TEXT,
    reason_code TEXT,
    UNIQUE (claim_id, seq),
    CHECK ((seq = 1) = (from_status IS NULL))
) STRICT;

CREATE TABLE claim_provider (
    claim_id TEXT NOT NULL REFERENCES claim (claim_id),
    provider_id TEXT NOT NULL REFERENCES provider (provider_id),
    service_role TEXT NOT NULL CHECK (service_role IN ('REPAIR', 'MEDICAL', 'TOWING', 'LEGAL')),
    assigned_date TEXT NOT NULL,
    PRIMARY KEY (claim_id, provider_id, service_role)
) STRICT;

CREATE TABLE invoice (
    invoice_id TEXT PRIMARY KEY CHECK (invoice_id GLOB 'INV-PRV-[0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]'),
    provider_id TEXT NOT NULL REFERENCES provider (provider_id),
    claim_id TEXT NOT NULL REFERENCES claim (claim_id),
    external_invoice_no TEXT NOT NULL,
    invoice_date TEXT NOT NULL,
    total_cents INTEGER NOT NULL CHECK (total_cents > 0),
    covered_cents INTEGER NOT NULL CHECK (covered_cents >= 0),
    current_status TEXT NOT NULL CHECK (current_status IN ('RECEIVED', 'VERIFIED', 'APPROVED', 'REJECTED', 'PAID')),
    UNIQUE (invoice_id, claim_id),
    CHECK (substr(invoice_id, 5, 10) = provider_id),
    CHECK (covered_cents <= total_cents)
) STRICT;

CREATE TABLE invoice_line (
    invoice_id TEXT NOT NULL REFERENCES invoice (invoice_id),
    line_no INTEGER NOT NULL CHECK (line_no >= 1),
    service_code TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity >= 1),
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents > 0),
    line_amount_cents INTEGER NOT NULL,
    is_covered INTEGER NOT NULL CHECK (is_covered IN (0, 1)),
    PRIMARY KEY (invoice_id, line_no),
    CHECK (line_amount_cents = quantity * unit_price_cents)
) STRICT;

CREATE TABLE invoice_events (
    event_id TEXT PRIMARY KEY CHECK (event_id GLOB 'IEV-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'),
    invoice_id TEXT NOT NULL REFERENCES invoice (invoice_id),
    seq INTEGER NOT NULL CHECK (seq >= 1),
    from_status TEXT CHECK (from_status IN ('RECEIVED', 'VERIFIED', 'APPROVED', 'REJECTED', 'PAID')),
    to_status TEXT NOT NULL CHECK (to_status IN ('RECEIVED', 'VERIFIED', 'APPROVED', 'REJECTED', 'PAID')),
    event_at TEXT NOT NULL,
    actor_role TEXT NOT NULL CHECK (actor_role IN ('CUSTOMER', 'OPS_ANALYST', 'RISK_REVIEWER', 'SYS_ADMIN', 'SYSTEM')),
    actor_id TEXT,
    reason_code TEXT,
    UNIQUE (invoice_id, seq),
    CHECK ((seq = 1) = (from_status IS NULL))
) STRICT;

CREATE TABLE payment (
    payment_id TEXT PRIMARY KEY CHECK (payment_id GLOB 'PAY-2026-[0-9][0-9][0-9][0-9][0-9][0-9]'),
    claim_id TEXT NOT NULL,
    invoice_id TEXT NOT NULL,
    payee_type TEXT NOT NULL CHECK (payee_type IN ('CLAIMANT', 'PROVIDER')),
    payee_claimant_id TEXT REFERENCES claimant (claimant_id),
    payee_provider_id TEXT REFERENCES provider (provider_id),
    payee_bank_token TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    payment_date TEXT NOT NULL,
    current_status TEXT NOT NULL CHECK (current_status IN ('INITIATED', 'SETTLED', 'FAILED', 'REVERSED')),
    FOREIGN KEY (invoice_id, claim_id) REFERENCES invoice (invoice_id, claim_id),
    CHECK ((payee_type = 'CLAIMANT' AND payee_claimant_id IS NOT NULL AND payee_provider_id IS NULL)
        OR (payee_type = 'PROVIDER' AND payee_provider_id IS NOT NULL AND payee_claimant_id IS NULL))
) STRICT;

CREATE TABLE payment_events (
    event_id TEXT PRIMARY KEY CHECK (event_id GLOB 'YEV-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'),
    payment_id TEXT NOT NULL REFERENCES payment (payment_id),
    seq INTEGER NOT NULL CHECK (seq >= 1),
    from_status TEXT CHECK (from_status IN ('INITIATED', 'SETTLED', 'FAILED', 'REVERSED')),
    to_status TEXT NOT NULL CHECK (to_status IN ('INITIATED', 'SETTLED', 'FAILED', 'REVERSED')),
    event_at TEXT NOT NULL,
    actor_role TEXT NOT NULL CHECK (actor_role IN ('CUSTOMER', 'OPS_ANALYST', 'RISK_REVIEWER', 'SYS_ADMIN', 'SYSTEM')),
    actor_id TEXT,
    reason_code TEXT,
    UNIQUE (payment_id, seq),
    CHECK ((seq = 1) = (from_status IS NULL))
) STRICT;

CREATE TABLE graph_node (
    node_id TEXT PRIMARY KEY,
    node_type TEXT NOT NULL CHECK (node_type IN ('CLAIMANT', 'POLICY', 'INCIDENT', 'PROVIDER', 'PAYMENT')),
    CHECK ((node_type = 'CLAIMANT' AND node_id GLOB 'CLT-*') OR (node_type = 'POLICY' AND node_id GLOB 'POL-*')
        OR (node_type = 'INCIDENT' AND node_id GLOB 'INC-*') OR (node_type = 'PROVIDER' AND node_id GLOB 'PRV-*')
        OR (node_type = 'PAYMENT' AND node_id GLOB 'PAY-*'))
) STRICT;

CREATE TABLE relationship_edge (
    edge_id TEXT PRIMARY KEY CHECK (edge_id GLOB 'EDG-[0-9][0-9][0-9][0-9][0-9][0-9]'),
    source_node_id TEXT NOT NULL REFERENCES graph_node (node_id),
    target_node_id TEXT NOT NULL REFERENCES graph_node (node_id),
    edge_type TEXT NOT NULL CHECK (edge_type IN ('HOLDS_POLICY', 'USED_PROVIDER', 'INCIDENT_PARTY', 'SHARED_ADDRESS', 'SHARED_PHONE', 'SHARED_EMAIL', 'SHARED_BANK', 'SHARED_CONTACT_PROVIDER', 'PAID_TO_SHARED_ACCOUNT')),
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    source_ref TEXT NOT NULL CHECK (source_ref GLOB '*:*.*'),
    UNIQUE (source_node_id, target_node_id, edge_type),
    CHECK (source_node_id <> target_node_id),
    CHECK (valid_to IS NULL OR valid_to >= valid_from),
    CHECK (edge_type NOT IN ('SHARED_ADDRESS', 'SHARED_PHONE', 'SHARED_EMAIL', 'SHARED_BANK') OR source_node_id < target_node_id)
) STRICT;

CREATE TRIGGER policy_events_no_update BEFORE UPDATE ON policy_events
BEGIN SELECT RAISE(ABORT, 'policy_events is append-only'); END;
CREATE TRIGGER policy_events_no_delete BEFORE DELETE ON policy_events
BEGIN SELECT RAISE(ABORT, 'policy_events is append-only'); END;

CREATE TRIGGER claim_events_no_update BEFORE UPDATE ON claim_events
BEGIN SELECT RAISE(ABORT, 'claim_events is append-only'); END;
CREATE TRIGGER claim_events_no_delete BEFORE DELETE ON claim_events
BEGIN SELECT RAISE(ABORT, 'claim_events is append-only'); END;

CREATE TRIGGER invoice_events_no_update BEFORE UPDATE ON invoice_events
BEGIN SELECT RAISE(ABORT, 'invoice_events is append-only'); END;
CREATE TRIGGER invoice_events_no_delete BEFORE DELETE ON invoice_events
BEGIN SELECT RAISE(ABORT, 'invoice_events is append-only'); END;

CREATE TRIGGER payment_events_no_update BEFORE UPDATE ON payment_events
BEGIN SELECT RAISE(ABORT, 'payment_events is append-only'); END;
CREATE TRIGGER payment_events_no_delete BEFORE DELETE ON payment_events
BEGIN SELECT RAISE(ABORT, 'payment_events is append-only'); END;
