# Design decisions and assumptions

Written by me (the owner). One entry per decision. Newest at the bottom.

Format:
- **Decision:** what was decided
- **Options considered:** the alternatives
- **Choice and why:** what I picked and the reason
- **Trade-off / limitation:** what this costs or leaves out
- **Requirement link:** which line of `docs/problem_statement.md` this serves

---

## D-001 — Python and core libraries
- **Decision:** Use Python 3.13 with exact pins for `numpy`, `pandas` and `networkx` in `requirements.txt`.
- **Options considered:** Python 3.12 or 3.13; `pandas` or the standard-library `csv` module; `networkx` or hand-written graph code.
- **Choice and why:** Python 3.13 was already installed and working. `numpy` supplies the seeded generator that `CLAUDE.md` requires. `pandas` keeps joins, validation and exports short. `networkx` provides connected groups and graph measures with little code. Exact pins protect fixed-seed reproducibility, because random output can change between library versions.
- **Trade-off / limitation:** Adds three dependencies, and byte-identical output is only claimed for these pinned versions. Their own dependencies are not pinned.
- **Requirement link:** Synthetic Data Generation Step 4 (fixed seed) and Step 10 (reproducibility); Validation Rules (planted patterns rank highly).

## D-002 — SQLite as the database
- **Decision:** Use SQLite through Python's built-in `sqlite3` module.
- **Options considered:** SQLite; PostgreSQL in Docker.
- **Choice and why:** SQLite needs no server, so a reviewer can run the project with only `pip install`. The dataset is small, and the brief asks for SQL seed data, not a database server. It supports the keys, constraints, bridge tables and triggers this project needs.
- **Trade-off / limitation:** One writer at a time, and it looks less production-like than PostgreSQL. Foreign keys must be enabled on each connection, and `STRICT` tables are needed for firm data types. Orphan-claim rows need a labelled exceptions table so they can load with foreign keys on. Reproducibility is checked on the CSV, JSON and SQL exports, not the `.db` file.
- **Requirement link:** Business Workflow rule 4 (keep history); Entities and Relationships (keys, bridge tables, event history); Step 9 (SQL seed data).

## D-003 — Streamlit only, in one Python package
- **Decision:** Build the analyst UI in Streamlit at Part D, inside the existing `src/fraudnet/` package. No React, FastAPI or separate frontend and backend folders.
- **Options considered:** Streamlit only; React with FastAPI; command line only.
- **Choice and why:** The brief asks for a working workflow, traceability and measurable results, not a REST API or separate frontend. Streamlit keeps the project in Python and leaves more time for detection and evaluation. Business logic stays outside `app/`, so an API could call the same modules later.
- **Trade-off / limitation:** No API, and no real login or access control. Roles will use a simple selector recorded on investigation events, which is for demonstration only and must be stated in the README.
- **Requirement link:** Primary Actors / Systems; Objective and Scope (decisions, exceptions, traceability).

## D-004 — Invoice ID format
- **Decision:** Invoice IDs use `INV-PRV-000001-000001`: the provider's number, then a counter per provider.
- **Options considered:** `INV-PRV-000001-000001`; `INV-PRV-PRV-000001-000001`.
- **Choice and why:** The brief's `INV-PRV-<provider-id>-000001` already includes `PRV`, so using only the provider's number avoids repeating it. The provider can still be read directly from the ID.
- **Trade-off / limitation:** A strict reading of `<provider-id>` could expect the longer form. The validator checks that the provider part matches `provider_id`.
- **Requirement link:** ID / Nomenclature Conventions; Synthetic Data Generation Step 3.

## D-005 — ID formats for entities the brief doesn't name
- **Decision:** `CLT-000001` claimant, `POL-000001` policy, `PAY-2026-000001` payment, `CON-000001` contact, `EDG-000001` edge, `FIN-000001` fraud indicator, `NET-000001` network, `EXC-000001` exception, `GT-000001` label. Events use `PEV-` policy, `CEV-` claim, `IEV-` invoice, `YEV-` payment and `VEV-` investigation, each followed by 8 digits.
- **Options considered:** The formats above; plain integer keys.
- **Choice and why:** They match the style of the brief's IDs and make each ID's type obvious in files, evidence and explanations.
- **Trade-off / limitation:** More formats for the validator to check.
- **Requirement link:** ID / Nomenclature Conventions; Entities and Relationships (a primary key for every entity).

## D-006 — At least 8,000 relationship edges
- **Decision:** Claims, claimants and providers match the baseline exactly at scale 1.0. Relationship edges must be at least 8,000.
- **Options considered:** Exactly 8,000 edges; a minimum of 8,000.
- **Choice and why:** Edges are derived from source rows, so an exact total would need artificial padding or trimming, which breaks the derived-values rule. More rows would not improve detection.
- **Trade-off / limitation:** A strict reader may expect exactly 8,000. The real count is reported in the manifest.
- **Requirement link:** Step 4 and Suggested Volume; Step 6 (derived values).

## D-007 — USD with fictional, neutral locations
- **Decision:** Amounts are integer US cents. Names, addresses, phones and emails are fictional, using `555-` numbers and reserved `example` domains.
- **Options considered:** USD with neutral locations; INR with Indian locations.
- **Choice and why:** This avoids resemblance to real people or places. Integer cents keep totals exact and files byte-stable.
- **Trade-off / limitation:** Less local to India, and distributions are not calibrated to a real market.
- **Requirement link:** Public Data Guidance / Lawful Use; Evaluation Focus (d) and (g).

## D-008 — 24 planted fraud rings
- **Decision:** Plant 4 rings for each of 6 patterns at scale 1.0, with at least 1 per pattern at smaller scales.
- **Options considered:** A few rings per dataset; 24 rings; a much larger share of fraud.
- **Choice and why:** 24 rings give useful recall and per-pattern results without making fraud unrealistically common.
- **Trade-off / limitation:** Only 4 rings per pattern, so per-pattern results move in steps of 25%. Unseen seeds help offset this.
- **Requirement link:** Business Workflow rule 3; Validation Rules (rates are measurable).

## D-009 — Effective-dated claimant contacts
- **Decision:** Store contact details in `claimant_contact`, with effective dates, instead of on `claimant`.
- **Options considered:** A separate effective-dated table; contact columns on `claimant`.
- **Choice and why:** It meets the brief's effective-date requirement and lets the detector separate a past tenant from a current flatmate.
- **Trade-off / limitation:** One more table, and matching must check for overlapping dates.
- **Requirement link:** Entities and Relationships (effective dates, event history).

## D-010 — Commit a scale 0.1 sample
- **Decision:** Commit a scale 0.1 sample to `data/sample/`, including its ground truth. Full output stays in the git-ignored `data/output/`.
- **Options considered:** No committed data; the sample only; the full dataset.
- **Choice and why:** Reviewers can inspect the data without running code, while the full dataset can be regenerated from the seed.
- **Trade-off / limitation:** Adds files to the repo and makes sample labels visible in the same folder tree. The detector is pointed at `input/` only.
- **Requirement link:** Step 9 (exports); Step 7 (separate ground truth).

## D-011 — Stronger leakage guard
- **Decision:** `policy_check.py` also blocks hidden-folder paths and `hidden_manifest` in detector code. The detector reads only files listed in `input_manifest.json`, and a test will run it with `hidden/` removed and require byte-identical output.
- **Options considered:** Label names only; a broader check on code and runtime behaviour.
- **Choice and why:** Checking label names alone would miss code that opens the hidden folder and reads differently named files.
- **Trade-off / limitation:** A static check can't catch every disguised path, which is why the runtime test is also needed. That test will be added with the detector.
- **Requirement link:** Step 7; Validation Rules (labels are separate from features).

## D-012 — Keep prompts out of git until the end
- **Decision:** `prompts/` is git-ignored and removed from tracking. The owner keeps it locally and adds it to the repo directly at the end of the challenge.
- **Options considered:** Commit prompts throughout; add them at the end.
- **Choice and why:** The owner chose to add the prompt history as one step in the final hours.
- **Trade-off / limitation:** The folder must be un-ignored before submission. The FAQ requires all prompts submitted to every AI tool, so the final history must be complete.
- **Requirement link:** Submission Guidelines item 3 (prompt history required); FAQ items 4 and 6.

## D-013 — Temporary keys until final IDs, and unique baseline contact values
- **Decision:** The generator uses temporary integer keys and assigns final IDs in a separate last step. Baseline phones, emails, bank tokens and addresses are globally unique.
- **Options considered:** Assign IDs on creation; allow accidental collisions in baseline values.
- **Choice and why:** Late IDs stop row creation order from revealing planted records. Unique baselines mean every shared value in the data comes from a documented planting rule, so a false link can't appear by accident.
- **Trade-off / limitation:** Every stage must carry and later replace temporary keys. Real data would contain some accidental collisions, which this baseline does not model.
- **Requirement link:** Step 3 (deterministic IDs); Step 7 (no leakage); Business Workflow rule 5 (labels from documented rules).

## D-014 — Separate source rows from calculated lifecycle
- **Decision:** `transactions.py` creates source facts only. `lifecycle.py` then calculates amounts, payments, events and statuses. Random draws in `lifecycle.py` choose delays and payment outcomes only.
- **Options considered:** Calculate values as each row is created; a separate calculation stage.
- **Choice and why:** Planted rows can go through the same calculations, so totals and statuses stay correct after injection.
- **Trade-off / limitation:** Planned choices such as a customer withdrawing are carried in internal `plan_` columns until the calculation stage. They are never exported.
- **Requirement link:** Step 5 (baseline first, then edge cases); Step 6 (derived values).

## D-015 — Baseline claim and payment simplifications
- **Decision:** Extra claims beyond the incident count come from a second, unrelated driver in a two-party collision. A reversed payment is not reissued, so its claim stays `APPROVED` with an open balance. Each approved invoice is paid in one amount, with failed attempts retried as new rows.
- **Options considered:** Reissuing reversed payments; part-payments for each invoice.
- **Choice and why:** These cover the required failure and multi-party cases while keeping every amount easy to reconcile.
- **Trade-off / limitation:** Real insurers often pay in stages and reissue reversed payments, which this data does not model.
- **Requirement link:** Step 6 (reconciliation); Evaluation Focus (c) and (e).

## D-016 — What the database enforces and what it leaves to validation
- **Decision:** SQLite `STRICT` tables enforce types, keys, foreign keys, allowed values, ID formats, balance and line arithmetic, and append-only events. Overpayments, duplicate external invoice numbers and nonexistent `policy_ref` values are deliberately not blocked.
- **Options considered:** Enforce every rule in the database; enforce nothing and rely on validation.
- **Choice and why:** The database gives a second, independent check on generated rows, while the required edge cases can still load and be reported instead of failing the import.
- **Trade-off / limitation:** Rules across rows, such as lifecycle order and total reconciliation, still need the validator. A payment that exceeds the approved amount is allowed by the schema.
- **Requirement link:** Entities and Relationships; Step 5 (edge cases); Step 8 (validation); Step 9 (SQL seed data).

## D-017 — Limit baseline claims per claimant to 8
- **Decision:** An ordinary claimant can have at most 8 baseline claims, and claim activity is drawn with less skew. The seasonal swing in incident dates was also reduced from 25% to 20%, so monthly counts stay clear of the spike check.
- **Options considered:** Keep the earlier skew (one claimant had 18 claims on one policy in nine months); a less skewed draw alone; a less skewed draw with a hard limit.
- **Choice and why:** An audit showed that 27% of claimants with claims had 4 or more, which did not match the planned "a few with more". Heavy ordinary claimants would also look like suspects and weaken `B-REPEAT-01`. The limit guarantees the maximum at every seed and scale.
- **Trade-off / limitation:** The brief's volumes still force an average of 2.5 claims per claimant in nine months, which is higher than a real insurer would see. Testing several settings showed about 10% of claimants with claims still reach 6 or more, even with nearly equal activity. The limit applies to the baseline only; planted patterns follow their own rules.
- **Requirement link:** Step 4 (benign patterns, volume); Evaluation Focus (realistic distributions).

## D-018 — Host the app on Streamlit Community Cloud with a rebuilt SQLite database
- **Decision:** The live demo runs on Streamlit Community Cloud. On startup it rebuilds SQLite from the seeded generator and runs the detector, so the hosted data always matches the repository.
- **Options considered:** SQLite rebuilt on startup; hosted PostgreSQL on Neon; no live demo.
- **Choice and why:** Rebuilding needs no outside account or second database, keeps one tested schema with its constraints and triggers, and lets a reviewer reproduce the hosted data from the seed. PostgreSQL would need the schema ported and tested on a second engine.
- **Trade-off / limitation:** The host's disk is not permanent, so investigations created on the live app can reset when it restarts. The app must say so on screen and let the user download the investigation history, and the README must state it. Local runs keep their history. Compatibility with Python 3.13 and the pinned libraries, and startup time, must be checked at deployment.
- **Requirement link:** Primary Actors / Systems; Business Workflow rule 4 (keep history); Objective and Scope (decisions, exceptions, traceability).

## D-019 — How planted patterns enter the data
- **Decision:** Planted rows are chosen first, so the baseline can be reduced by the same amount. Shared contacts and joint policies are applied to master data before baseline claims. Planted claims then pass through the same invoice and lifecycle code as all other claims. Each claimant belongs to at most one planted group. Labels cover claimants, planted claims and the providers that are themselves part of the pattern.
- **Options considered:** Add planted rows on top of the baseline; rewrite finished baseline rows; plan first and use one shared code path.
- **Choice and why:** Adding rows on top would break the exact claim count, and rewriting finished rows could leave totals and histories inconsistent. One shared code path keeps derived values correct and leaves no separate style for planted rows to reveal.
- **Trade-off / limitation:** Keeping groups separate means no fraud ring member also belongs to a benign household, which real data can contain. Rings also use a fixed list of patterns, so detection results apply to these patterns and not to fraud in general. Ring claims are placed on both sides of a ring's central date so that claim dates give nothing away.
- **Requirement link:** Business Workflow rules 3 and 5; Step 2; Step 5; Step 6; Step 7.

## D-020 — How the edge cases are planted and labelled
- **Decision:** EC-1 claims name a nonexistent policy and stay under review. EC-2 repeats the last settled payment on a fully paid claim. EC-3 copies one provider invoice onto claims from different claimants. EC-1 and EC-2 are labelled `is_fraud = 0` (data and payment errors), and EC-3 is labelled `is_fraud = 1` (billing the same invoice twice). Recorded edges leave out every link inside each `R-RING-06` ring, including payments into a ring member's shared account.
- **Options considered:** Deny EC-1 claims with a reason code; overpay by changing an amount; treat every edge case as fraud or none as fraud.
- **Choice and why:** A claim with no policy can't be judged, so leaving it open sends it to an exception investigation, as the brief's expected decision says. Repeating a real payment gives an overpayment that still reconciles row by row. Duplicate billing is the one edge case that is a fraud pattern; the other two are errors that need correcting, not a fraud finding.
- **Trade-off / limitation:** Recorded edges are otherwise complete, so a missing edge only ever points to `R-RING-06`. That is why `UNRECORDED_LINK` only raises priority when another signal supports it (section 9). The EC-2 duplicate can arrive after the claim is closed, which real systems usually block.
- **Requirement link:** Step 5 (labelled edge cases); Validation Rules (anomalies labelled without corrupting unrelated rows); Business Workflow rule 5.

## D-021 — Validator design, report locations and the committed sample
- **Decision:** The validator recalculates every rule from the input files without reusing generator code. A shared loader (`fraudnet/inputs.py`) reads only the files listed in `input_manifest.json`, which now also records the seed and scale for the volume check. `data_exception` is written to `reports/` and loaded into `fraudnet.db`. The scale 0.1 sample is committed byte for byte through `.gitattributes`.
- **Options considered:** Reuse generator functions in the checks; keep exceptions in a separate database; let git convert line endings in the sample.
- **Choice and why:** Independent checks catch generator mistakes instead of repeating them, and tests break each rule deliberately to prove each check works. The same loader will serve the detector, so it can't reach `hidden/`. Seed and scale are generator settings, not labels. On Windows git converts line endings by default, which would break the sample's recorded checksums for anyone who clones it.
- **Trade-off / limitation:** Every rule is written twice, once in the generator and once in the validator, so a rule change needs both updated. The reproducibility check regenerates the data three times, which takes about 30 seconds at scale 1.0, so it only runs with `--reproducibility`.
- **Requirement link:** Step 8 (validation); Step 9 (exports and manifest); Step 10 (regenerate and compare); Step 7 (no leakage).
