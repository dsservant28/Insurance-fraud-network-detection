# Data dictionary and data plan

**Status:** plan decisions approved by the owner (see section 15). Part A is complete: the generator (sections 3-8, 10), the validator and reproducibility check (11) and all exports (12). The detector and later stages are not built yet, so sections 9 and 13 are still design targets. Actual counts are in `reports/source_manifest.json`.

**Conventions**

| Item | Rule |
|---|---|
| Req | `R` = required, `O` = optional |
| Unique | `PK` = primary key, `U` = unique, `No` = not unique |
| Money | Integer cents (`*_cents`), so totals reconcile exactly and files stay byte-identical |
| Dates | `DATE` = `YYYY-MM-DD`; `DATETIME` = `YYYY-MM-DDTHH:MM:SSZ` in UTC |
| Derived | Computed from source rows and never randomly generated. The validator recomputes every derived value |
| Fixed as-of date | `2026-10-22`. The generator never reads the system clock |

---

## 1. How the data flows

```text
GENERATOR (seed + scale)
  ├─> input/    Data the system can see: CSV, JSON and SQL seed
  ├─> hidden/   ground_truth.csv and ground_truth.json
  └─> reports/  Source manifest and generation summary

VALIDATOR reads input/          -> validation summary and data_exception rows
DETECTOR reads input/ only      -> detected edges, networks, indicators and evidence
EVALUATOR reads output + hidden -> precision, recall, FP/FN rates, ranking quality
INVESTIGATION reads output      -> investigations with append-only events
```

**Terms used below**

| Term | Meaning |
|---|---|
| Claimant | The person asking the insurer to pay |
| Policy | The insurance contract: what is covered, for how long and up to what limit |
| Incident | The real-world event, such as a collision |
| Claim | A request for payment for an incident under a policy |
| Provider | A repairer, medical provider or other service business |
| Coverage limit | The most the policy will pay |
| Deductible | The part of a loss the customer pays first |
| Fraud ring | A group of connected people or providers acting together |
| Benign look-alike | An innocent pattern that resembles fraud, such as a family at one address |

---

## 2. Volume

The brief's section is titled "Suggested Volume" and Step 4 calls it the baseline. **We will match the stated numbers wherever we can.** More rows would not improve detection. Quality comes from varied fraud patterns and strong look-alikes. A reviewer can also check exact counts at a glance.

| Entity | Scale 1.0 | Rule |
|---|---|---|
| Claim | **5,000** | Exact, including planted and edge-case claims |
| Claimant | **2,000** | Exact, including ring members and look-alikes |
| Provider | **500** | Exact |
| RelationshipEdge | **At least 8,000** | Minimum. Edges are derived from source rows, so padding or randomly trimming to an exact total would break the derived-values rule |
| Policy | About 2,600 | Not stated in the brief |
| Incident | About 4,700 | Lower than claims because some incidents have several claims |
| Invoice / invoice line | About 6,400 / 19,000 | Not stated in the brief; measured on the baseline run |
| Payment | About 4,800 | Not stated in the brief; measured on the baseline run |

**Scale:** a single `--scale` value drives the same generator. Base counts use `round(base × scale)`, and planted patterns use `max(minimum, round(base × scale))`, so small datasets can still be evaluated.

| Scale | Purpose | Claims | Claimants | Providers | Edges |
|---|---|---:|---:|---:|---:|
| 0.1 | Starter and fast tests | 500 | 200 | 50 | At least 800 |
| 1.0 | Full baseline | 5,000 | 2,000 | 500 | At least 8,000 |
| 2.0 | Larger run to show that scale works | 10,000 | 4,000 | 1,000 | At least 16,000 |

**Realistic variation**

| Field | Planned distribution |
|---|---|
| Claims per claimant | Long tail: many with 1-3, some with none, a few with more. Baseline maximum is 8 (D-017) |
| Provider popularity | Skewed, with a few genuinely busy providers |
| Invoice amounts | Log-normal, varying by incident type |
| Incident dates | Vary by season and day of week across 2026-01-01 to 2026-09-30 |
| Narratives | Templates with varied details, shared by normal and planted records |

---

## 3. Core entity tables

### 3.1 Claimant (master)
Contact details are effective-dated in `claimant_contact`. There is deliberately **no `household_id`**, because the detector must work out relationships from raw attributes.

| Field | Type | Req | Allowed values / format | Units | Unique | Validation |
|---|---|---|---|---|---|---|
| `claimant_id` | TEXT | R | `CLT-000001` | - | PK | Matches format; immutable |
| `full_name` | TEXT | R | Fictional name from built-in lists | - | No | Not empty |
| `date_of_birth` | DATE | R | Valid date | - | No | Age 18-95 at the as-of date |
| `customer_since` | DATE | R | Valid date | - | No | After date of birth + 18 years; not after as-of date |

### 3.2 Provider (master)

| Field | Type | Req | Allowed values / format | Units | Unique | Validation |
|---|---|---|---|---|---|---|
| `provider_id` | TEXT | R | `PRV-000001` | - | PK | Matches format; immutable |
| `provider_name` | TEXT | R | Fictional business name | - | No | Not empty |
| `provider_type` | TEXT | R | `REPAIRER`, `MEDICAL`, `SERVICE` | - | No | Allowed value |
| `address_line`, `city`, `postal_code` | TEXT | R | Fictional address | - | No | Not empty |
| `phone` | TEXT | R | Fictional `555-XXX-XXXX` | - | No | Matches format |
| `email` | TEXT | R | `@example.com`, `.org` or `.net` | - | No | Reserved domain only |
| `bank_token` | TEXT | R | `ACCT-XXXXXXXX`, not a real account | - | No | Matches format |
| `active_from` | DATE | R | Valid date | - | No | Not after as-of date |
| `active_to` | DATE | O | Valid date | - | No | Empty, or not before `active_from` |

### 3.3 Policy (master)

| Field | Type | Req | Allowed values / format | Units | Unique | Validation |
|---|---|---|---|---|---|---|
| `policy_id` | TEXT | R | `POL-000001` | - | PK | Matches format; immutable |
| `policy_type` | TEXT | R | `AUTO`, `HOME`, `HEALTH` | - | No | Allowed value |
| `effective_from` | DATE | R | Valid date | - | No | Before `effective_to` |
| `effective_to` | DATE | R | Valid date | - | No | After `effective_from` |
| `coverage_limit_cents` | INTEGER | R | Above 0 | Cents | No | Greater than deductible |
| `deductible_cents` | INTEGER | R | 0 or above | Cents | No | Lower than coverage limit |
| `current_status` | TEXT | R | See section 6 | - | No | **Derived:** latest `policy_events` status |

### 3.4 Incident (master)
The brief lists Claim as master data too. Claim depends on Policy and Incident, so it is created immediately after them and before all transaction records.

| Field | Type | Req | Allowed values / format | Units | Unique | Validation |
|---|---|---|---|---|---|---|
| `incident_id` | TEXT | R | `INC-2026-000001` | - | PK | Matches format; immutable |
| `incident_type` | TEXT | R | `COLLISION`, `THEFT`, `INJURY`, `WATER_DAMAGE`, `FIRE`, `ILLNESS` | - | No | Allowed value |
| `incident_date` | DATE | R | 2026-01-01 to 2026-09-30 | - | No | In range |
| `city`, `postal_code` | TEXT | R | Fictional location | - | No | Not empty |
| `narrative` | TEXT | R | Free text | - | No | Not empty |
| `vehicle_ref` | TEXT | O | `VEH-XXXXXX`, fictional | - | No | Vehicle incidents only |

### 3.5 Claim

| Field | Type | Req | Allowed values / format | Units | Unique | Validation |
|---|---|---|---|---|---|---|
| `claim_id` | TEXT | R | `CLM-2026-000001` | - | PK | Matches format; immutable |
| `incident_id` | TEXT | R | FK `incident` | - | No | Parent exists |
| `claimant_id` | TEXT | R | FK `claimant` | - | No | Parent exists |
| `policy_ref` | TEXT | R | The policy ID as submitted | - | No | Matches format; existence not forced (EC-1) |
| `policy_id` | TEXT | O | FK `policy` | - | No | **Derived:** `policy_ref` if the policy exists, otherwise empty |
| `reported_date` | DATE | R | Valid date | - | No | On or after `incident_date`; not after as-of date |
| `claimed_amount_cents` | INTEGER | R | 0 or above | Cents | No | **Derived:** sum of invoice totals |
| `approved_amount_cents` | INTEGER | R | 0 or above | Cents | No | **Derived:** see section 7 |
| `paid_amount_cents` | INTEGER | R | 0 or above | Cents | No | **Derived:** net settled payments |
| `balance_cents` | INTEGER | R | Negative only for EC-2 | Cents | No | **Derived:** approved - paid |
| `days_incident_to_report` | INTEGER | R | 0 or above | Days | No | **Derived** |
| `days_policy_start_to_incident` | INTEGER | O | Whole number | Days | No | **Derived;** empty if `policy_id` is empty |
| `current_status` | TEXT | R | See section 6 | - | No | **Derived:** latest `claim_events` status |

### 3.6 Invoice

| Field | Type | Req | Allowed values / format | Units | Unique | Validation |
|---|---|---|---|---|---|---|
| `invoice_id` | TEXT | R | `INV-PRV-000001-000001` | - | PK | Provider part matches `provider_id`; counter runs per provider |
| `provider_id` | TEXT | R | FK `provider` | - | No | Parent exists |
| `claim_id` | TEXT | R | FK `claim` | - | No | Parent exists |
| `external_invoice_no` | TEXT | R | Number printed by the provider | - | No | Repeats across claimants are reported (EC-3) |
| `invoice_date` | DATE | R | Valid date | - | No | On or after `incident_date`; provider active |
| `total_cents` | INTEGER | R | Above 0 | Cents | No | **Derived:** sum of line amounts |
| `covered_cents` | INTEGER | R | 0 to total | Cents | No | **Derived:** sum of covered line amounts |
| `current_status` | TEXT | R | See section 6 | - | No | **Derived:** latest `invoice_events` status |

`invoice_id` is always unique. A duplicate invoice in EC-3 is two different rows with the same provider, external number, date and amount.

### 3.7 Payment

| Field | Type | Req | Allowed values / format | Units | Unique | Validation |
|---|---|---|---|---|---|---|
| `payment_id` | TEXT | R | `PAY-2026-000001` | - | PK | Matches format; immutable |
| `claim_id` | TEXT | R | FK `claim` | - | No | Parent exists |
| `invoice_id` | TEXT | R | FK `invoice` | - | No | Invoice belongs to this claim |
| `payee_type` | TEXT | R | `CLAIMANT`, `PROVIDER` | - | No | Allowed value |
| `payee_claimant_id` | TEXT | O | FK `claimant` | - | No | Required only when payee is a claimant |
| `payee_provider_id` | TEXT | O | FK `provider` | - | No | Required only when payee is a provider |
| `payee_bank_token` | TEXT | R | `ACCT-XXXXXXXX` | - | No | Matches format |
| `amount_cents` | INTEGER | R | Above 0 | Cents | No | **Derived:** from the approved amount; EC-2 uses a documented rule |
| `payment_date` | DATE | R | Valid date | - | No | On or after approval date; not after as-of date |
| `current_status` | TEXT | R | See section 6 | - | No | **Derived:** latest `payment_events` status |

### 3.8 RelationshipEdge (input)
This is the recorded link register. It is true but deliberately incomplete for EC-4. The detector builds its own edges from raw attributes in `detected_edge`.

| Field | Type | Req | Allowed values / format | Units | Unique | Validation |
|---|---|---|---|---|---|---|
| `edge_id` | TEXT | R | `EDG-000001` | - | PK | Matches format |
| `source_node_id` | TEXT | R | FK `graph_node` | - | No | Node exists |
| `target_node_id` | TEXT | R | FK `graph_node` | - | No | Node exists; differs from source |
| `edge_type` | TEXT | R | See section 5 | - | No | Allowed value |
| `valid_from` | DATE | R | Valid date | - | No | **Derived** from source rows |
| `valid_to` | DATE | O | Valid date | - | No | **Derived;** empty if still valid |
| `source_ref` | TEXT | R | `table:row_id.field` | - | No | The referenced row and value exist |

`(source_node_id, target_node_id, edge_type)` is unique. For same-type links such as claimant to claimant, the smaller ID is always the source.

### 3.9 FraudIndicator (detector output)

| Field | Type | Req | Allowed values / format | Units | Unique | Validation |
|---|---|---|---|---|---|---|
| `indicator_id` | TEXT | R | `FIN-000001` | - | PK | Matches format |
| `run_id` | TEXT | R | FK `detector_run` | - | No | Parent exists |
| `network_id` | TEXT | O | FK `network` | - | No | Empty for standalone anomalies |
| `subject_node_id` | TEXT | O | FK `graph_node` | - | No | Empty when the subject has no valid node |
| `indicator_code` | TEXT | R | See section 9 | - | No | Allowed value |
| `severity` | TEXT | R | `LOW`, `MEDIUM`, `HIGH` | - | No | **Derived** from the indicator rule |
| `score_contribution` | REAL | R | 0 to 1, rounded to 4 places | Score | No | **Derived** from the indicator rule |
| `explanation` | TEXT | R | Plain-language sentence | - | No | Mentions at least one concrete ID |
| `evidence_json` | TEXT | R | JSON of IDs, fields and values | - | No | Not empty; every referenced ID exists |

### 3.10 Investigation (workflow)

| Field | Type | Req | Allowed values / format | Units | Unique | Validation |
|---|---|---|---|---|---|---|
| `investigation_id` | TEXT | R | `INVG-2026-000001` | - | PK | Matches format; immutable |
| `trigger_type` | TEXT | R | `NETWORK_SCORE`, `DATA_EXCEPTION` | - | No | Allowed value |
| `network_id` | TEXT | O | FK `network` | - | No | Required for `NETWORK_SCORE` |
| `exception_id` | TEXT | O | FK `data_exception` | - | No | Required for `DATA_EXCEPTION` |
| `priority` | TEXT | R | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` | - | No | **Derived** from score or exception type |
| `opened_at` | DATETIME | R | UTC | - | No | Matches first event |
| `current_status` | TEXT | R | See section 6 | - | No | **Derived:** latest `investigation_events` status |

---

## 4. Supporting tables

### 4.1 Other input tables

| Table | Key | Fields | Rules |
|---|---|---|---|
| `claimant_contact` | `contact_id` `CON-000001` | `claimant_id` FK, `effective_from`, `effective_to` (O), `address_line`, `city`, `postal_code`, `phone`, `email`, `bank_token` (O) | Periods for a claimant never overlap, and exactly one is open |
| `claimant_policy` (bridge) | `claimant_id` + `policy_id` | `role` (`POLICYHOLDER`, `NAMED_INSURED`), `effective_from`, `effective_to` (O) | Each policy has exactly one policyholder |
| `claim_provider` (bridge) | `claim_id` + `provider_id` + `service_role` | `service_role` (`REPAIR`, `MEDICAL`, `TOWING`, `LEGAL`), `assigned_date` | Every invoice's claim and provider pair appears here |
| `invoice_line` | `invoice_id` + `line_no` | `service_code`, `quantity`, `unit_price_cents`, `line_amount_cents`, `is_covered` | `line_amount_cents` is **derived:** quantity x unit price |
| `graph_node` | `node_id` | `node_type` (`CLAIMANT`, `POLICY`, `INCIDENT`, `PROVIDER`, `PAYMENT`) | **Derived:** one row per real entity. It gives edge endpoints a true FK |

### 4.2 Event tables (append-only)
`policy_events`, `claim_events`, `invoice_events`, `payment_events` and `investigation_events` share this structure:

| Field | Type | Req | Allowed values / format | Validation |
|---|---|---|---|---|
| `event_id` | TEXT | R | `PEV-`, `CEV-`, `IEV-`, `YEV-` or `VEV-` + 8 digits | Primary key |
| Parent ID | TEXT | R | FK to the parent table | Parent exists |
| `seq` | INTEGER | R | 1, 2, 3... | Unique per parent, with no gaps |
| `from_status` | TEXT | O | Lifecycle status | Empty only for `seq` 1; equals the previous `to_status` |
| `to_status` | TEXT | R | Lifecycle status | The transition is allowed by section 6 |
| `event_at` | DATETIME | R | UTC | Never earlier than the previous event |
| `actor_role` | TEXT | R | `CUSTOMER`, `OPS_ANALYST`, `RISK_REVIEWER`, `SYS_ADMIN`, `SYSTEM` | Allowed value |
| `actor_id` | TEXT | O | Synthetic user ID | Required for non-system staff roles |
| `reason_code` | TEXT | O | Controlled list by table | Required for denial, failure, reversal and closure |
| `note` | TEXT | O | Free text | Investigation events only |

SQLite triggers block `UPDATE` and `DELETE` on all event tables.

**Actors**

| Brief's actor | Role in data | Example actions |
|---|---|---|
| Customer/account holder | `CUSTOMER` | Submits a claim or withdraws it |
| Operations analyst | `OPS_ANALYST` | Reviews claims, invoices and exceptions |
| Risk/compliance reviewer | `RISK_REVIEWER` | Handles escalations and confirms or clears networks |
| System administrator | `SYS_ADMIN` | Runs data loads and maintains the system |

### 4.3 Validator and detector output tables

| Table | Key | Fields | Purpose |
|---|---|---|---|
| `data_exception` | `exception_id` `EXC-000001` | `exception_type`, `severity`, `entity_type`, `entity_id`, `field_name`, `observed_value`, `expected_rule`, `detail_json` | Facts found by checks, with no fraud label |
| `detector_run` | `run_id` | `input_manifest_sha256`, `config_sha256`, `code_version` | Traceability for every result |
| `detected_edge` | `run_id` + `source_node_id` + `target_node_id` + `edge_type` + `matched_value` | `normalized_value`, `source_refs_json`, `valid_from`, `valid_to`, `in_recorded_edges` | Links rebuilt from raw attributes |
| `network` | `network_id` `NET-000001` | `run_id`, `score`, `rank`, `member_count`, `summary` | Scored and ranked groups; score and rank are derived |
| `network_member` (bridge) | `network_id` + `node_id` | `member_role`, `member_score` | Network members |
| `investigation_subject` (bridge) | `investigation_id` + `node_id` | `subject_role` | People and entities under investigation |

---

## 5. Relationships

### 5.1 Keys and cardinality

| Parent | Child | Foreign key | Cardinality | Optional? |
|---|---|---|---|---|
| Claimant | ClaimantContact | `claimant_id` | 1:N, effective-dated | Every claimant has at least one |
| Claimant and Policy | ClaimantPolicy | Both IDs | N:M bridge, effective-dated | Every policy has at least one claimant |
| Incident | Claim | `incident_id` | 1:N | Every incident has at least one claim |
| Claimant | Claim | `claimant_id` | 1:N | A claimant may have none |
| Policy | Claim | `policy_id` | 1:N | Empty only for EC-1 |
| Claim and Provider | ClaimProvider | Both IDs | N:M bridge | A claim may have none |
| Claim | Invoice | `claim_id` | 1:N | A claim may have none |
| Provider | Invoice | `provider_id` | 1:N | A provider may have none |
| Invoice | InvoiceLine | `invoice_id` | 1:N | Every invoice has at least one |
| Invoice | Payment | `invoice_id` | 1:N | An invoice may have none |
| Claim | Payment | `claim_id` | 1:N | A claim may have none |
| Claimant or Provider | Payment payee | Payee FK | 1:N | Exactly one payee is set |
| GraphNode | RelationshipEdge | Source and target | N:M through edges | A node may have no edges |
| Network | NetworkMember | `network_id` | N:M bridge with nodes | Every network has at least two members |
| Network | FraudIndicator | `network_id` | 1:N | Empty for standalone anomalies |
| Network | Investigation | `network_id` | 1:N | Empty for exception-led cases |
| DataException | Investigation | `exception_id` | 1:N | Empty for network-led cases |
| Investigation | InvestigationSubject | `investigation_id` | N:M bridge with nodes | At least one subject |
| Parent entity | `*_events` | Parent ID | 1:N | Every lifecycle row has at least one |

An incident connects to many claimants through its claims, so it doesn't need another bridge table.

### 5.2 Effective dates

| Table | Fields | Meaning |
|---|---|---|
| `policy` | `effective_from`, `effective_to` | Coverage period |
| `claimant_policy` | `effective_from`, `effective_to` | When a person was on the policy |
| `claimant_contact` | `effective_from`, `effective_to` | When contact details applied, separating a past tenant from a current flatmate |
| `provider` | `active_from`, `active_to` | When the provider operated |
| `relationship_edge`, `detected_edge` | `valid_from`, `valid_to` | When a link applied |

### 5.3 Edge types

| `edge_type` | Connects | Built from | Estimated edges at scale 1.0 |
|---|---|---|---:|
| `HOLDS_POLICY` | Claimant to policy | `claimant_policy` | 2,600 |
| `USED_PROVIDER` | Claimant to provider | Claims and `claim_provider` | 4,500 |
| `INCIDENT_PARTY` | Claimant to incident | Incidents with two or more claims | 500 |
| `SHARED_ADDRESS` | Claimant to claimant | Matching normalised address in overlapping periods | Part of about 1,000 shared links |
| `SHARED_PHONE`, `SHARED_EMAIL`, `SHARED_BANK` | Claimant to claimant | Matching contact values | Part of about 1,000 shared links |
| `SHARED_CONTACT_PROVIDER` | Claimant to provider | Matching phone, email or bank value | Small |
| `PAID_TO_SHARED_ACCOUNT` | Payment to claimant or provider | A payment to a claimant landed in an account another claimant or a provider also holds. A provider paid into its own registered account is not flagged | Small |

Node IDs are the entity IDs themselves, such as `CLT-000001`. The default run gives 12,560 edges: `USED_PROVIDER` 6,164, `HOLDS_POLICY` 2,790, `SHARED_ADDRESS` 2,408, `INCIDENT_PARTY` 562, `SHARED_PHONE` 326, `PAID_TO_SHARED_ACCOUNT` 127, `SHARED_BANK` 109, `SHARED_EMAIL` 48 and `SHARED_CONTACT_PROVIDER` 26. Tests require at least 8,000 x scale. Claimant-to-claimant links need overlapping contact periods, so past tenants (`B-MOVE-01`) get no edge.

---

## 6. Lifecycle states

Any transition not listed is a validation failure.

| Entity | Start | Allowed transitions |
|---|---|---|
| Policy | `ACTIVE` | `ACTIVE` to `LAPSED`, `CANCELLED` or `EXPIRED`; `LAPSED` to `ACTIVE` |
| Claim | `SUBMITTED` | `SUBMITTED` to `UNDER_REVIEW` or `WITHDRAWN`; `UNDER_REVIEW` to `APPROVED`, `DENIED` or `WITHDRAWN`; `APPROVED` to `PAID`; `PAID`, `DENIED` or `WITHDRAWN` to `CLOSED` |
| Invoice | `RECEIVED` | `RECEIVED` to `VERIFIED` or `REJECTED`; `VERIFIED` to `APPROVED` or `REJECTED`; `APPROVED` to `PAID` |
| Payment | `INITIATED` | `INITIATED` to `SETTLED` or `FAILED`; `SETTLED` to `REVERSED` |
| Investigation | `OPEN` | `OPEN` to `IN_REVIEW`; `IN_REVIEW` to `ESCALATED`, `CLOSED_CONFIRMED` or `CLOSED_CLEARED`; `ESCALATED` to `CLOSED_CONFIRMED` or `CLOSED_CLEARED`; either closed state to `IN_REVIEW` when reopened |

Current status columns are a convenience copy of the latest event. The event table remains the record of what happened.

---

## 7. Derived values

| Value | Formula |
|---|---|
| Invoice line amount | `quantity x unit_price_cents` |
| Invoice total | Sum of its line amounts |
| Invoice covered amount | Sum of line amounts where `is_covered = 1` |
| Claim amount | Sum of invoice totals on the claim |
| Approved amount | `max(0, min(sum of covered amounts on non-rejected invoices, coverage limit) - deductible)` when the claim has an `APPROVED` event; otherwise 0 |
| Paid amount | Settled payments minus reversed payments. Failed and initiated payments count as 0 |
| Balance | Approved amount - paid amount |
| Payment amounts | Split the approved amount across invoices in proportion to covered amount. The last invoice takes the rounding remainder |
| Day gaps | Date differences from source dates |
| Statuses | Latest event per parent |
| Edges and nodes | Rules in section 5.3 |
| Network, indicator and investigation scores | Detector rules in section 9 |

**Conditional rules**

| Condition | Outcome |
|---|---|
| Incident date is outside policy dates | Claim is denied with `reason_code = OUTSIDE_COVERAGE` |
| `policy_ref` doesn't resolve | `policy_id` is empty, the claim can't be approved or paid, and an exception is recorded |
| Incident type doesn't fit policy type | Claim is denied with `reason_code = TYPE_NOT_COVERED` |
| All invoice lines are uncovered, or the covered amount on invoices not already rejected doesn't exceed the deductible | Approved amount is 0 and the claim is denied with `reason_code = BELOW_DEDUCTIBLE` |
| Policy was lapsed or cancelled on the incident date | Claim is denied with `reason_code = POLICY_NOT_ACTIVE` |
| Payment fails | A retry may be a new payment row, and the failed row stays |
| Settled payment is reversed | Paid amount falls, the balance reopens, and the claim and invoice both stay `APPROVED` |

---

## 8. Planted patterns and edge cases

**Order of generation:**
1. Create claimants, contacts, providers, policies and incidents.
2. Create baseline claims, invoices, lines, payments and events.
3. Inject benign look-alikes, fraud rings and edge cases.
4. Calculate all derived values and edges.
5. Assign final IDs.
6. Write input files and, separately, ground truth.

Planted rows are never added on top of the requested counts. They use part of each count. Changes to master data, such as shared contacts and joint policies, are applied before step 2, so baseline claims always use the final parents (D-019). Planted claims are added after the baseline claims and pass through the same invoice and lifecycle code.

### 8.1 Fraud rings

Each ring has 3-8 claimants. There are 4 rings per pattern at scale 1.0, making **24 rings**, and at least 1 per pattern at smaller scales.

| Rule | Pattern | Planting rule | Main evidence |
|---|---|---|---|
| `R-RING-01` | Shared contact details | Unrelated claimants share phones, emails or bank tokens | Matching values across claimants with different surnames and addresses |
| `R-RING-02` | Repeated narratives | Nearly identical narratives across separate incidents and locations | High text similarity plus a shared provider |
| `R-RING-03` | Unusual timing | Incidents soon after policy start, with reports and invoices in a tight burst | Short day gaps across connected claimants |
| `R-RING-04` | Provider collusion | Claimants concentrate on one provider with inflated invoices and linked accounts | Provider concentration, high amounts, matching bank token |
| `R-RING-05` | Staged incident | Several claimants on one incident, using the same small set of providers | Shared incident, providers and contact links |
| `R-RING-06` | Hidden link | Real links exist in raw attributes, but their edges are left out (EC-4) | Links found by the detector and absent from `relationship_edge` |

### 8.2 Benign look-alikes

| Rule | Pattern | Scale 1.0 target | False conclusion it prevents |
|---|---|---:|---|
| `B-HOUSE-01` | Shared households: family surname, address, sometimes phone and joint policy | 150 households | "Shared contact details always mean fraud" |
| `B-REPEAT-01` | Genuine repeat claims, at least 45 days apart with varied incidents and providers. These claimants have no other claims | 200 claimants | "Repeat claimants are suspicious" |
| `B-ADDR-01` | Common addresses: apartment block, care home or shared housing (EC-5) | 10 sites | "A shared address proves a link" |
| `B-PROV-01` | Popular providers with many unrelated customers | 10 providers | "A busy provider is suspicious" |
| `B-EVENT-01` | Storm or flood: similar narratives and a burst of claims with no contact links | 3 events | "Similar text and timing prove a ring" |
| `B-MOVE-01` | Past tenants at the same address in non-overlapping periods | 20 addresses | "Same address means connected now" |

### 8.3 Required edge cases

| ID | Brief's edge case | How it appears in input | Scale 1.0 count | Validator result | Expected decision |
|---|---|---|---:|---|---|
| EC-1 | Claim links to nonexistent policy | `policy_ref` is well-formed but no policy exists; `policy_id` is empty | 5 claims | `ORPHAN_POLICY_REF` exception | Route to an exception investigation; do not pay |
| EC-2 | Payment exceeds approved amount | Settled payments are greater than approved, so balance is negative | 10 claims | `PAYMENT_OVER_APPROVED` exception | Review payment and escalate |
| EC-3 | Duplicate invoice across claimants | Same provider, external number, date and amount on claims from different claimants | 5 groups | `DUPLICATE_INVOICE` exception | Investigate |
| EC-4 | Planted relationship not represented in edges | Raw shared value exists, but the matching edge is deliberately missing | All 4 `R-RING-06` rings | Not a validator failure; absent edge is only provable by the detector and evaluator | Detector must recover it and mark `in_recorded_edges = 0` |
| EC-5 | Benign common address treated as proof | Many unrelated residents at one address with no other links | 10 sites | Valid data | Clear; must not rank as suspicious on address alone |

**How each edge case is planted and labelled** (D-020)

| ID | Planting rule | Lifecycle result | Labels (`rule_id` / `is_fraud` / `expected_decision`) |
|---|---|---|---|
| EC-1 | A claim names `POL-` plus a number above the highest real policy number | Stays `UNDER_REVIEW`: invoices are checked but no decision or payment is possible | `EC-1` / 0 / `ROUTE_EXCEPTION`, on the claimant and claim |
| EC-2 | After a claim is fully paid, the last settled payment is repeated 1-5 days later and also settles | Paid amount exceeds approved, so the balance is negative | `EC-2` / 0 / `REVIEW_PAYMENT`, on the claim and duplicate payment |
| EC-3 | One provider invoice (number, date, lines and total) is copied onto claims of 2-3 different claimants | Each copy goes through normal checks, so the same bill can be paid more than once | `EC-3` / 1 / `INVESTIGATE`, on the claimants, claims and invoices |
| EC-4 | Shared bank, phone and address values exist in contact rows, but those edges are left out | Normal | Labelled on the `R-RING-06` rings with `issue_type = EC-4` |
| EC-5 | Unrelated residents share one building address | Normal | Labelled on the `B-ADDR-01` groups with `issue_type = EC-5` |

**Boundary and failure records in normal data**

| Type | Examples |
|---|---|
| Normal | Claim moves from submission through approval, payment and closure |
| Boundary | Incident on the first or last policy day; payment exactly equals approved; loss exactly equals deductible; single-line invoice; claim reported on the incident date |
| Failure | Failed payment followed by retry; reversed payment; rejected invoice; withdrawn claim; lapsed policy |
| Exception | EC-1 to EC-5 |
| Open work | Claims still under review at the as-of date |

---

## 9. Detector indicators and scoring inputs

Exact weights and thresholds belong in the detector design step. These rules are already fixed by this plan:

| `indicator_code` | Evidence required | Rule |
|---|---|---|
| `SHARED_BANK`, `SHARED_PHONE`, `SHARED_EMAIL` | Both IDs, matched value, source rows, overlapping dates | Lower weight when household signs are present |
| `SHARED_ADDRESS` | Both IDs, address, overlapping dates | **Low weight, and never enough to flag on its own** |
| `REPEATED_NARRATIVE` | Incident IDs, text similarity, compared text | Lower weight without contact or provider links |
| `EARLY_CLAIM`, `CLAIM_BURST` | Claim IDs, dates, calculated gaps | Timing alone can't flag a network |
| `PROVIDER_CONCENTRATION` | Provider ID, claim counts, baseline | Compared with the provider's overall volume |
| `INFLATED_AMOUNT` | Claim or invoice IDs, amount, comparison group | Compared with similar incidents |
| `PAYMENT_OVER_APPROVED` | Claim and payment IDs, approved and paid amounts | Standalone anomaly |
| `DUPLICATE_INVOICE` | Invoice IDs, claimants, provider, external number, amount | Standalone or part of a network |
| `ORPHAN_POLICY_REF` | Claim ID and submitted `policy_ref` | Standalone exception |
| `UNRECORDED_LINK` | Rebuilt link and its absence from `relationship_edge` | Raises investigation priority only when supported by another signal |

The detector treats `relationship_edge` as a possibly incomplete hint. It rebuilds links from raw values after normalising formats, so `12 Oak St` and `12 Oak Street` match.

---

## 10. Hidden labels and keeping them hidden

### 10.1 Ground truth file
Written to `data/output/hidden/ground_truth.csv` and `.json`. There is one row per labelled entity.

| Field | Type | Req | Allowed values / format | Validation |
|---|---|---|---|---|
| `label_id` | TEXT | R | `GT-000001` | Primary key |
| `label_kind` | TEXT | R | `FRAUD_RING`, `BENIGN_LOOKALIKE`, `EDGE_CASE` | Allowed value |
| `rule_id` | TEXT | R | A rule from section 8 | Documented rule required |
| `ring_id` | TEXT | O | `RING-001` | Required for fraud rings |
| `group_id` | TEXT | O | `GRP-0001` | Required for look-alike and edge-case groups |
| `issue_type` | TEXT | O | `EC-1` to `EC-5` | Required for edge cases |
| `is_fraud` | INTEGER | R | 0 or 1 | From the rule, never drawn at random |
| `entity_type` | TEXT | R | `CLAIMANT`, `PROVIDER`, `CLAIM`, `INVOICE`, `PAYMENT` | Allowed value |
| `entity_id` | TEXT | R | ID in input data. An EC-1 label is on the claim, and its reason gives the missing policy number | Exists |
| `expected_decision` | TEXT | R | `INVESTIGATE`, `CLEAR`, `ROUTE_EXCEPTION`, `REVIEW_PAYMENT` | Allowed value |
| `reason` | TEXT | R | Plain-language reason with concrete IDs or values | Not empty |

### 10.2 Ways labels could leak, and the protection for each

| Leak route | Protection | Test |
|---|---|---|
| Label columns in input | Forbidden names exist only in `hidden/` | Scan all input headers and SQL for forbidden names |
| Detector code reads labels | `policy_check.py` blocks label names and hidden-folder paths in `detect/` | Hook and policy tests |
| Detector opens the hidden folder | Detector accepts one input folder and reads only the files listed in its `input_manifest.json` | Run it with `hidden/` removed; output must be byte-identical |
| IDs reveal planted rows | Final IDs are assigned after injection. Dated entities follow date order, and others use a seeded shuffle | Fraud rows must be spread across the ID range |
| Row order reveals planted rows | Files are sorted by final ID | Same test |
| Special values reveal planted rows | Ring and normal records use the same name, address, narrative and amount sources | No single raw field may nearly separate fraud from normal |
| Manifest reveals labels | `input/` has its own manifest; label checksums stay in `hidden/` | Scan the input manifest |
| SQL seed reveals labels | Seed contains input tables only | Scan the seed |
| Exceptions reveal labels | `data_exception` is computed from data and holds no label | It works when `hidden/` is absent |
| Analyst UI reveals labels | Case screens read detector output only; evaluation has its own screen | Case-screen code must not name the hidden files |
| Tuning on labels overfits | Set thresholds using the default seed, then report results on separate unseen seeds too | Evaluation report shows both |

The sample in `data/sample/` is protected the same way: the detector is pointed at its `input/` folder only. The removed-folder test will be added with the detector.

---

## 11. Validation

Run with `python -m fraudnet.validate --data data/output --reproducibility`. Exit code 1 means a hard check failed. Each check recalculates its rule from the input files on its own (`src/fraudnet/validate/checks.py`), and tests break each rule deliberately to prove the check catches it.

### 11.1 Hard checks: any failure fails the run

| ID | Brief's check | Rule |
|---|---|---|
| V-01 | Primary-key uniqueness | Every primary key is unique, and every ID matches its format |
| V-02 | Foreign-key integrity | Every FK exists; the empty `policy_id` is allowed only with a matching `policy_ref` exception |
| V-03 | Allowed enums | Every controlled field uses allowed values |
| V-04 | Date ordering | Dates follow sections 3, 6 and 7 |
| V-05 | Arithmetic reconciliation | Every value in section 7 recomputes exactly |
| V-06 | Lifecycle transitions | Every event sequence follows section 6, and current status matches its latest event |
| V-07 | Duplicate checks | No repeated bridge rows or edge keys, and every `invoice_id` is unique |
| V-08 | Cross-file consistency | Referenced IDs match exactly across CSV, JSON and SQL |
| V-09 | Volume | Claim, claimant and provider counts are exact, and edges meet the minimum |
| V-10 | Coverage | Normal, boundary, failure and exception cases are all present |
| V-11 | Valid joins | All documented joins run with no unexpected row loss, and the SQL seed loads with foreign keys on |
| V-12 | Synthetic-only data | Contact values use the fictional formats and reserved domains |

### 11.2 Exception checks: reported, without failing the run
`ORPHAN_POLICY_REF`, `PAYMENT_OVER_APPROVED` and `DUPLICATE_INVOICE` create `data_exception` rows. They are built in `src/fraudnet/validate/exceptions.py` and need input tables only. A `DUPLICATE_INVOICE` row is written for every invoice in a group with the same provider, external number, date and total across two or more claimants.

The validator doesn't read ground truth. The evaluator reconciles the two in both directions:
- **No silent corruption:** every exception has a label.
- **No lost labels:** every labelled exception was found.

### 11.3 Reproducibility
The same command runs twice into two folders, and row counts and SHA-256 checksums must match for every exported file. A different seed must produce different data. Files are made byte-stable using UTF-8, LF line endings, fixed column order, sorted rows, sorted JSON keys and no run timestamps. The claim applies to the pinned library versions in `requirements.txt`.

---

## 12. Exports

```text
data/output/
  input/
    csv/<table>.csv
    json/<table>.json
    sql/schema.sql
    sql/seed.sql
    input_manifest.json
  hidden/
    ground_truth.csv
    ground_truth.json
    hidden_manifest.json
  reports/
    source_manifest.json         (generator)
    validation_summary.json      (validator)
    data_exception.csv / .json   (validator)
    reproducibility_report.json  (validator with --reproducibility)
  detect/
  evaluation/
```

The generator also loads the SQL files into `data/output/fraudnet.db` with foreign keys on, for browsing and later stages. It holds input tables only, with no labels, and the validator adds `data_exception`. Its bytes are not part of the reproducibility check; the CSV, JSON, SQL, hidden and source manifest files are.

| File | Format |
|---|---|
| `csv/<table>.csv` | UTF-8, LF line endings, header row, rows sorted by key, empty field for null |
| `json/<table>.json` | One array per table with one record per line, in the CSV's row and column order, `null` for empty values |
| `sql/schema.sql`, `sql/seed.sql` | `STRICT` tables, constraints and append-only triggers, then inserts in parent-before-child order |
| `input_manifest.json` | Path, row count and SHA-256 for every input file, plus the generator seed and scale. No label files are listed |

`data/output/` is git-ignored because it can be regenerated. A scale 0.1 copy of `input/`, `hidden/` and `reports/` is committed in `data/sample/` so reviewers can inspect the data without running code.

`source_manifest.json` records the generator command, seed, scale, Python and library versions, file list, row counts, checksums and data provenance. **Provenance:** all data is synthetic and no external dataset is used, so no licence or attribution is needed.

---

## 13. Evaluation

| Measure | Definition |
|---|---|
| Match rule | A detected network matches a planted group when Jaccard similarity of claimants is at least 0.5. Each planted group matches at most one network |
| Precision | Fraud-matched networks / flagged networks |
| Recall | Rings found / planted rings |
| False-positive rate | Flagged benign look-alike groups / all benign look-alike groups |
| False-negative rate | Rings missed / planted rings, which equals 1 - recall |
| Ranking quality | Precision@k, recall@k, average precision and NDCG |
| Top-rank check | Share of planted rings in the top `N` networks, where `N` = planted ring count |
| Edge-case results | Reported per EC ID. EC-1 to EC-4 must be found, and EC-5 must not be flagged on address alone |
| Explanation check | Every flagged network has indicators with evidence, and every referenced ID exists |
| Hidden-link recovery | Share of EC-4 links recovered |

Results are reported overall and per rule, on the default seed and on unseen seeds.

---

## 14. Brief-to-plan traceability

| Brief requirement | Covered in |
|---|---|
| Link claimants, policies, incidents, providers and payments | 3, 5 |
| Expose decisions and exceptions | 3.9, 4.3, 7, 8.3 |
| Preserve traceability | `source_ref`, evidence, `detector_run`, 4.2 |
| Measurable outputs and evaluation metrics | 13 |
| Conditional rules | 7 |
| At least one exception path | EC-1 to exception investigation: 3.10, 8.3 |
| All four actors | 4.2 |
| Master data first; children use valid parents | 3, 5, 8 |
| Shared contacts, repeated narratives, unusual timing | 8.1 |
| Hidden ground-truth file | 10 |
| State changes as events, without overwriting history | 4.2, 6 |
| Labels from documented rules | 8, 10.1 |
| PK and FK for every entity and relationship | 3, 4, 5.1 |
| Cardinality, optional relationships, effective dates, lifecycle states | 5.1, 5.2, 6 |
| Bridge tables and validated joins | 4.1, 4.3, V-11 |
| Keep anomalies labelled without corrupting unrelated rows | 8.3, 10.1, 11.2 |
| Required ID formats, immutable and consistent | 3, V-01, V-08 |
| Step 1: field-level dictionary for all 10 entities | 3 |
| Steps 2-3: generation order and deterministic IDs | 8, 10.2 |
| Step 4: baseline volume, benign patterns, seed, scale | 2, 8.2 |
| Step 5: valid baseline, then labelled edge cases | 8, 8.3 |
| Step 6: derived values | 7 |
| Step 7: separate ground truth with no leakage | 10 |
| Step 8: all validation categories | 11.1 |
| Step 9: CSV, JSON, SQL, documents, manifest and summary | 12. README and generator command are delivered with the code |
| Step 10: regenerate and compare | 11.3 |
| Planted patterns rank highly | 13 |
| Explanations reference evidence | 3.9, 9, 13 |
| Labels separate from features | 10 |
| FP and FN rates measurable | 13 |
| Realistic distributions | 2 |
| Normal, boundary, failure and exception coverage | 8.3, V-10 |
| Lawful provenance; synthetic data | 12, V-12 |

---

## 15. Approved decisions

All seven were approved by the owner and are recorded in `docs/DECISIONS.md`.

| # | Topic | Decision | Record |
|---|---|---|---|
| 1 | Edge count | At least 8,000 instead of exactly 8,000 | D-006 |
| 2 | Currency and locale | USD with fictional, neutral addresses | D-007 |
| 3 | Number of rings | 24 rings, 4 per pattern | D-008 |
| 4 | Effective-dated contacts | Keep `claimant_contact` | D-009 |
| 5 | Other ID formats | `CLT-`, `POL-`, `PAY-2026-`, `CON-`, `EDG-`, `FIN-`, `NET-`, `EXC-`, `GT-` and event prefixes as shown above | D-005 |
| 6 | Sample data in GitHub | Commit a scale 0.1 sample in `data/sample/`, including `hidden/` | D-010 |
| 7 | Stronger leakage guard | Block hidden-folder paths in `policy_check.py`, and add the removed-folder test with the detector | D-011 |
