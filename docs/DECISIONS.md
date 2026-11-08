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

## D-022 — Detect with explainable evidence rules, not a trained model
- **Decision:** The detector rebuilds links from raw values and scores them with documented rules: identifier specificity, explaining away, a shared anomaly for shared context, repetition and rarity weighting (`ARCHITECTURE.md` section 2). No supervised model is trained.
- **Options considered:** A supervised classifier trained on the hidden labels; generic graph anomaly scores (degree, PageRank); explainable evidence rules.
- **Choice and why:** The labels come from this project's own generator, so a trained model would partly learn the generator rather than fraud, and the labels must stay out of detection (CLAUDE.md rule 1). Generic graph scores flag busy providers and buildings, which are exactly the look-alikes. Evidence rules can name the IDs and values behind every flag, which the brief requires. Each rule was checked against measured counts on the development seed before it was adopted (`ARCHITECTURE.md` section 8).
- **Trade-off / limitation:** The rules fit the documented fraud patterns. A new pattern needs a new rule. Labels were used only to look at signal behaviour on the development seed, and results are reported on unseen seeds as well.
- **Requirement link:** Detection (rebuild relationships, score, explain); Validation Rules (planted patterns rank highly, labels separate from features).

## D-023 — Build networks only from evidence links, and split oversized groups
- **Decision:** Networks are connected groups of claimants joined by evidence links (identity, billing, story, timing, incident, location). "Holds policy" and "used provider" never join people. A group with more than 12 claimants is split with Louvain community detection (`networkx`, fixed seed).
- **Options considered:** Connected components over every edge; components over evidence links only; community detection on everything.
- **Choice and why:** Joining people through a shared provider creates one giant false network around every busy provider. A provider becomes part of the evidence only when the claims there share an anomaly (`STORY`, `TIMING`). Louvain is a well-known, deterministic-with-seed method that separates groups joined by a weak bridge.
- **Trade-off / limitation:** A ring whose only connection is a plain shared provider, with no shared anomaly, isn't found. The 12-claimant split limit is a tuned setting.
- **Requirement link:** Detection (build networks); Evaluation Focus (false positives).

## D-024 — Score with a noisy-OR over signal families
- **Decision:** Each family contributes its strongest link × coverage, scaled by rarity in the data and reduced by benign explanations. The network score is 1 − Π(1 − family strength). A network is flagged at score ≥ 0.6, and weak families are capped so that none can reach that alone. All values live in `src/fraudnet/detect/detector.toml`.
- **Options considered:** Hand-picked points added together; a weighted sum; noisy-OR.
- **Choice and why:** Noisy-OR treats families as independent evidence, stays between 0 and 1, and doesn't grow just because a network has more members. Capping weak families turns "a weak signal needs corroboration" into arithmetic rather than special cases. Rarity scaling ties weights to the data and gives each explanation a rate that can be checked.
- **Trade-off / limitation:** The family caps and explanation factors are judgement calls. They are tuned on the development seed only, and the one-principle-off evaluation shows their effect.
- **Requirement link:** Detection (score and rank); Explanations reference evidence.

## D-025 — Evaluate on unseen seeds, against comparison methods and with one principle off at a time
- **Decision:** Thresholds are tuned only on seed 20261022. Results are reported on 5 unseen seeds as mean ± standard deviation, compared with "flag any shared value" and "recorded edges only", and repeated with one principle switched off at a time.
- **Options considered:** Report the development seed only; add unseen seeds; add comparison methods and one-principle-off runs as well.
- **Choice and why:** A detector tuned and scored on the same data overstates itself. Unseen seeds show whether the rules generalise, comparison methods show what the design adds, and the one-principle-off runs show which principle matters.
- **Trade-off / limitation:** Unseen seeds come from the same generator, so this tests stability, not real-world performance. Each extra seed adds generation time to evaluation.
- **Requirement link:** Evaluation Focus (precision, recall, FP and FN rates, ranking quality).

## D-026 — Investigation workflow with a four-eyes rule and a hash-chained history
- **Decision:** Cases follow the investigation lifecycle in DATA_DICTIONARY section 6. The person who opened a case can't confirm it, and a blocked attempt is recorded with reason `FOUR_EYES_BLOCKED`. CRITICAL cases must be escalated before closing. Each `investigation_events` row stores `prev_hash` and `event_hash` (SHA-256).
- **Options considered:** Status changes with no role rules; role rules only; role rules plus a hash chain.
- **Choice and why:** Labelling someone as fraud has consequences, so real fraud teams require a second reviewer. Triggers already block edits and deletes. The hash chain also makes tampering detectable if the database file itself were altered, and the app can show the check.
- **Trade-off / limitation:** The four-eyes rule makes the live demo need two different users, which the role switcher provides. The hash chain detects tampering but can't prevent it.
- **Requirement link:** Business Workflow rules 1-5 (actors, history, decisions); Primary Actors.

## D-027 — A custom-designed app with an interactive Cytoscape.js graph
- **Decision:** The Streamlit app uses its own design system (theme, CSS, fonts, HTML components, one colour per signal family). The network graph is drawn with Cytoscape.js through a small custom component. The JS file is kept in the repository.
- **Options considered:** Streamlit's built-in graphviz chart; `pyvis` or `streamlit-agraph`; Cytoscape.js embedded directly.
- **Choice and why:** The app is what reviewers see first. Built-in graphviz is static, and the common wrappers give little control over styling. Cytoscape.js supports click-to-highlight, styling by edge family, dashed unrecorded links and several layouts, with no extra Python dependency. Keeping the file in the repository means the hosted app doesn't rely on an outside CDN.
- **Trade-off / limitation:** A custom component is more code to maintain than a wrapper library. Cytoscape.js's MIT licence must be kept with the file.
- **Requirement link:** Primary Actors / Systems (analyst UI); Explanations reference evidence.

## D-028 — Refinements found by testing the theory on unseen seeds
- **Decision:**
  - A busy provider no longer explains a story told by 3 or more of its customers who all match one another.
  - A shared incident joins people into a network only when two of its parties are also linked another way.
  - A single coincidental provider-based pair (story or early claim) joins nobody unless another family links the same pair.
  - Every indicator sentence names concrete IDs, including the unrecorded-link sentence.
- **Options considered:** Lower the busy-provider percentile; split every network with Louvain; set the split size to the largest ring size; apply the repetition principle (P5) at joining time.
- **Choice and why:** Seed 4242 missed one R-RING-02 ring, because its provider happened to be busy and the explanation discounted all three matching stories. A busy provider makes a coincidental pair likely, not three mutual near-copies. On seeds 777 and 4242, ordinary three-car crashes and single early-claim coincidences attached bystanders to rings, which lowered the match quality. Applying P5 when links join people fixes both without any knowledge of ring sizes. Setting the split size to the largest planted ring would have fitted the generator, so it was rejected.
- **Trade-off / limitation:** A staged incident with no other link between its parties is no longer grouped. It could never be flagged anyway, because incident evidence alone stays below the threshold. Seeds 777 and 4242 were looked at while making these fixes, so the final evaluation reports 5 further seeds that were never examined.
- **Requirement link:** Evaluation Focus (false positives, false negatives); Validation Rules (planted patterns rank highly).

## D-029 — Count one provider fact once, and retire the test seeds that revealed it
- **Decision:** `PROVIDER_CONCENTRATION` support is not counted when a story or early-claim link in the network already rests on that provider. Seeds 101, 202, 303, 404 and 505 are retired as test seeds, and results are reported on new seeds 606, 707, 808, 909 and 1010.
- **Options considered:** Leave the double counting and report it as a limitation; raise the flag threshold; fix the double counting and keep reporting on seeds 101-505; fix it and report on fresh seeds.
- **Choice and why:** The first full evaluation on seeds 101-505 gave ring recall 1.000, look-alike false-positive rate 0.000 and precision 0.948 ± 0.015. Each seed had 1-2 extra LOW-priority networks. Looking at one showed three unrelated claimants with early claims at one small provider, scored 0.55 for timing plus 0.20 for "most members use one provider". Every early-claim link already requires that provider, so the same fact was counted twice. Noisy-OR assumes independent evidence, so this is a flaw in applying the theory, not a threshold to tune. Because the flaw was found by looking at seeds 101-505, results on those seeds no longer test unseen data, so fresh seeds are used.
- **Trade-off / limitation:** R-RING-02 networks backed only by story evidence now score 0.65, a smaller margin over the 0.6 threshold. Three-member early-claim coincidences at a small provider still score 0.55, just below the threshold, by design.
- **Requirement link:** Evaluation Focus (precision, false positives); Validation Rules (labels separate from tuning).

## D-030 — Cases keep a snapshot of their trigger, and record refused actions
- **Decision:**
  - A case stores the run ID, network or exception ID, priority, score and summary at the moment it opens, without an enforced foreign key to `network` or `data_exception`.
  - Events have an `action` column: `NOTE` and `BLOCKED` events keep the status unchanged.
  - Every refused action by case staff is written as a `BLOCKED` event with its reason.
  - The hash chain runs per case.
  - Analysts may clear only LOW or MEDIUM cases that are not escalated.
- **Options considered:** Foreign keys to the detector tables; keeping every detector run in the database; snapshots. Silently rejecting refused actions, or recording them.
- **Choice and why:** The detector and validator replace their tables on every run, so a foreign key would either block the rerun or wipe case history, which must never happen (CLAUDE.md rule 5). A snapshot keeps the case readable exactly as the analyst saw it, and the run ID records which run that was. Recording refusals makes the four-eyes rule and role limits auditable, not just enforced. A per-case chain lets each case be verified and exported on its own.
- **Trade-off / limitation:** A case can point to a network ID that a later run with different settings numbers differently. The run ID shows which run it came from. Regenerating the data deletes the database, and with it the cases, which the hosted app states (D-018). Staff accounts are synthetic, with no real login.
- **Requirement link:** Business Workflow rules 1-5; Primary Actors; Step "at least one exception path".
