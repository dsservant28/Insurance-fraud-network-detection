My Applications
/
Associate AI Forward Deployed Engineers
/
Code Challenge
Round 2
72 Hours Code Challenge
Associate AI Forward Deployed Engineers · AI Forward Deployed Engineer

Problem statement
Read it carefully. Your build should cover every point below.

Business Context / Problem
Link claimants, policies, incidents, providers and payments to surface suspicious networks for investigation.

Objective and Scope
Build a working solution for this end-to-end workflow: Link claimants, policies, incidents, providers and payments to surface suspicious networks for investigation. The solution should expose key decisions and exceptions, preserve traceability, and produce measurable outputs. Medium complexity means multiple related entities, conditional rules, at least one exception path and meaningful evaluation metrics.

Primary Actors / Systems
Customer/account holder, operations analyst, risk/compliance reviewer and system administrator

Business Workflow and Rules
1. Generate/reference master data first: Claimant, Policy, Claim, Incident, Provider.
2. Generate dependent transaction/event records using valid parent IDs.
3. Apply business logic: Create claimant and policy records; generate incidents and claims; link service providers, repairers or medical providers using synthetic IDs; create invoices and payment events; inject controlled patterns such as shared contact details, repeated incident narratives and unusual timing; label planted networks in a hidden ground-truth file.
4. Persist state changes as explicit records/events where relevant; do not overwrite history.
5. Generate outcomes and ground-truth labels from documented rules, not independent random assignment.

Entities and Relationships
Core entities: Claimant, Policy, Claim, Incident, Provider, Invoice, Payment, RelationshipEdge, FraudIndicator, Investigation. Define a primary key for every entity and foreign keys for every relationship. Document cardinality (1:1, 1:N, N:M), optional relationships, effective dates and lifecycle states. Use bridge tables for many-to-many relationships; retain event history for state changes; validate all joins. For deliberate anomaly cases, keep an issue_type/ground_truth label rather than silently corrupting unrelated rows.

ID / Nomenclature Conventions
CLM-2026-000001; INC-2026-000001; PRV-000001; INV-PRV-<provider-id>-000001; INVG-2026-000001.

Synthetic Data Generation Instructions (Granular)
Step 1 — Write a data dictionary for: Claimant, Policy, Claim, Incident, Provider, Invoice, Payment, RelationshipEdge, FraudIndicator, Investigation. For each field specify type, required/optional, allowed values, units, uniqueness and validation rule.
Step 2 — Create parent/master tables first, then child and event tables. Apply this domain-specific generation logic: Create claimant and policy records; generate incidents and claims; link service providers, repairers or medical providers using synthetic IDs; create invoices and payment events; inject controlled patterns such as shared contact details, repeated incident narratives and unusual timing; label planted networks in a hidden ground-truth file.
Step 3 — Apply deterministic IDs and naming: CLM-2026-000001; INC-2026-000001; PRV-000001; INV-PRV-<provider-id>-000001; INVG-2026-000001. Keep counters zero-padded, IDs immutable, and referenced IDs exactly consistent across files.
Step 4 — Generate the baseline volume: Generate 5,000 claims, 2,000 claimants, 500 providers and 8,000 relationship edges. Include benign shared households and genuine repeat claims to prevent simplistic false positives. Use a fixed seed (e.g. 20261022) and parameterize scale so starter and full datasets use the same generator.
Step 5 — Generate valid baseline records first, then inject labelled edge cases: Claim links to nonexistent policy; payment exceeds approved amount; duplicate invoice across claimants; planted relationship not represented in edges; benign common address incorrectly treated as proof.
Step 6 — Calculate derived values (totals, balances, scores, statuses and dates) from source records rather than generating them independently.
Step 7 — Produce a separate ground_truth.csv/json for known anomalies, expected decisions or labels; never leak it into input features.
Step 8 — Run validation: primary-key uniqueness, foreign-key integrity, allowed enums, date ordering, arithmetic reconciliation, lifecycle transitions and duplicate checks.
Step 9 — Export CSV/JSON/SQL seed data plus README, schema/data dictionary, generator command, fixed seed, source manifest and validation summary.
Step 10 — Regenerate twice with the same seed and compare row counts/checksums to demonstrate reproducibility.

Suggested Volume and Coverage
Generate 5,000 claims, 2,000 claimants, 500 providers and 8,000 relationship edges. Include benign shared households and genuine repeat claims to prevent simplistic false positives.

Required Edge Cases / Negative Scenarios
Claim links to nonexistent policy; payment exceeds approved amount; duplicate invoice across claimants; planted relationship not represented in edges; benign common address incorrectly treated as proof.

Validation Rules / Acceptance Criteria
Known planted patterns rank highly; explanations reference evidence; labels are separate from features; false-positive and false-negative rates are measurable.

Evaluation Focus for Generated Data
Review: (a) realistic distributions and meaningful variation; (b) consistent IDs and valid joins; (c) dependency/lifecycle consistency across entities; (d) correct derived values and reconciliation; (e) normal, boundary, failure and exception coverage; (f) separate ground truth; (g) fixed-seed reproducibility, documentation and lawful provenance.

Public Data Guidance / Lawful Use
External data is optional. If used, record source URL, dataset/version, retrieval date, license/terms, attribution, transformations and fields discarded. Use only data you are legally permitted to access and redistribute; do not bypass access controls or collect confidential/personal information. If licensing or suitability is unclear, use synthetic data and cite public reference data only for schema inspiration.
Before you submit, make sure you have
Pushed your code to a public GitHub repository
Added a README explaining how to run it
Included any tests the problem asks for