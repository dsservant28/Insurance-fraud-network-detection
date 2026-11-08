# FraudNet: insurance fraud-network detection

FraudNet links claimants, policies, incidents, providers and payments to surface suspicious networks for investigation. It has five parts:

- **A. Generator:** builds a seeded, fully synthetic insurance dataset with labelled fraud rings, innocent look-alikes and five edge cases.
- **B. Detector:** rebuilds relationships from raw values and ranks suspicious networks, explaining each one with concrete IDs. It never reads the labels.
- **C. Evaluation:** measures the detector against the hidden labels and stress-tests it on data it was not designed for.
- **D. Investigation workflow:** analysts and reviewers work cases under a four-eyes rule, with an append-only, hash-chained history.
- **App:** a Streamlit investigator console.

Everything runs locally on free tools: Python 3.13, SQLite and Streamlit.

## Results at a glance

| Measure | Development seed 20261022 | 5 unseen seeds (mean) |
|---|---:|---:|
| Precision | 1.000 | 1.000 |
| Ring recall | 1.000 | 1.000 |
| False-positive rate on innocent look-alikes | 0.000 | 0.000 |
| R-precision (planted networks ranked at the top) | 1.000 | 1.000 |

- **What this shows, and doesn't:** the same generator produced every seed, so a perfect score shows the planted patterns are separated cleanly. It doesn't show performance on real fraud.
- **Stress test on data the detector wasn't designed for:**
  1. The predictions were pushed to git before the run.
  2. Detector v0.1 hit 41 of 51 of them. Its failures are published with their causes.
  3. Detector v0.2 fixed two of those failures and hit **31 of 31** new predictions on seeds no version had seen.
- **Details:** [docs/EVALUATION.md](docs/EVALUATION.md), [docs/STRESS.md](docs/STRESS.md), [docs/STRESS_V02.md](docs/STRESS_V02.md).

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows; on macOS/Linux: source .venv/bin/activate
pip install -e .                  # the package and its pinned dependencies
pip install -r requirements-dev.txt

python -m fraudnet.run            # every stage, full scale, into data/output (about 1.5 minutes)
streamlit run streamlit_app.py    # the investigator console at http://localhost:8501
```

`python -m fraudnet.run` generates, validates, detects, opens demo cases and evaluates. It accepts:
- `--seed` and `--scale`: the default seed is 20261022 and the default scale is 1.0. Scale 0.1 is a quick starter dataset made by the same generator.
- `--reproducibility`: regenerates twice and compares every file.
- `--unseen-seeds 606 707 808 909 1010`: also evaluates those seeds.

Checks:

```bash
pytest -q                         # the full test suite
python scripts/policy_check.py    # no label leakage, no unseeded randomness, no secrets
```

### Stage by stage

| Stage | Command | Writes |
|---|---|---|
| Generate | `python -m fraudnet.generate --seed 20261022 --scale 1.0 --out data/output` | `input/` (CSV, JSON, SQL), `hidden/` labels, `reports/source_manifest.json`, `fraudnet.db` |
| Validate | `python -m fraudnet.validate --data data/output --reproducibility` | `reports/validation_summary.json`, `reports/data_exception.*`, `reports/reproducibility_report.json` |
| Detect | `python -m fraudnet.detect --data data/output` | `detect/` (networks, members, indicators, rebuilt links, explanations) and DB tables |
| Investigate | `python -m fraudnet.investigate --data data/output {demo,list,verify,export FILE}` | Investigation tables in `fraudnet.db`; `export` writes the full history as JSON |
| Evaluate | `python -m fraudnet.evaluate --data data/output --seeds 606 707 808 909 1010 --doc docs/EVALUATION.md` | `evaluation/` and the report |
| Stress test | `python -m fraudnet.evaluate stress --doc docs/STRESS.md` | The stress report (see [docs/STRESS_PLAN.md](docs/STRESS_PLAN.md)) |

The app reads `data/output` if it exists, otherwise the committed sample in `data/sample` (scale 0.1). Set `FRAUDNET_DATA` to point it elsewhere.

## How it works, in brief

**Generator** (`src/fraudnet/generate/`):
- **Order:** master data comes first (claimants, policies, providers), then incidents, claims, invoices, payments and their event histories.
- **One random source:** every random draw comes from one `numpy` generator seeded with the seed.
- **Calculated values:** totals, statuses and day gaps are computed from source records, never drawn at random.
- **Planted patterns:** six fraud-ring patterns, such as shared contact details, repeated narratives, unusual timing and provider collusion.
- **Innocent look-alikes:** families, busy buildings, repeat claimants, storms and popular providers.
- **Edge cases:** the five required ones (EC-1 to EC-5).
- **Labels:** every label comes from a documented planting rule with a `rule_id` and a reason, and goes to `hidden/ground_truth.csv` and `.json`.

**Detector** (`src/fraudnet/detect/`): seven principles turn raw values into evidence.
- **Matching:** links are rebuilt from normalised raw values, not taken from the recorded relationship register.
- **Strength:** shared identifiers are strong evidence and shared addresses weak; rare link types weigh more.
- **Innocent causes:** households, buildings, storms and busy providers are explained away.
- **Shared providers:** a shared provider counts only alongside a shared anomaly.
- **Repetition:** weak patterns must repeat across at least 3 people.
- **Scoring:** networks are scored with a noisy-OR: 1 − Π(1 − fᵢ).
- **Explanations:** every flag carries sentences that cite real IDs and values. A check confirms each cited ID exists.
- **Details:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

**Investigation** (`src/fraudnet/investigate/`): a case opens from a flagged network or from a data exception.
- **Lifecycle:** OPEN → IN_REVIEW → ESCALATED → CLOSED_CONFIRMED or CLOSED_CLEARED.
- **Rules:** only a risk reviewer can confirm, and never on a case they opened (four-eyes). CRITICAL cases must be escalated first. Analysts may clear only LOW or MEDIUM cases.
- **Refusals:** a refused action is recorded as a BLOCKED event.
- **History:** database triggers block edits and deletes, and a SHA-256 hash chain exposes tampering.

## Actors

| Actor (problem statement) | In this system |
|---|---|
| Customer / account holder | The `claimant`, with effective-dated contact history and policies held through a bridge table. Synthetic people, with no login |
| Operations analyst | `OPS_ANALYST`: opens cases, starts reviews, escalates, clears LOW or MEDIUM cases |
| Risk / compliance reviewer | `RISK_REVIEWER`: confirms or clears fraud and reopens cases; can never confirm a case they opened |
| System administrator | `SYS_ADMIN`: runs the pipeline and settings; refused any case decision, and the refusal writes nothing to the case |

Staff accounts are fixed demo users chosen with a selector in the app. There is no real login (D-003).

## Requirements traceability

| Problem statement | Where it is met |
|---|---|
| Workflow 1–2: master data first, children use valid parent IDs | `generate/pipeline.py` stage order; validation V-02 (foreign keys) and V-11 (joins) |
| Workflow 3: link providers; invoices and payments; plant shared contacts, repeated narratives, unusual timing; hidden labels | `generate/plant.py`, `transactions.py`, `lifecycle.py`; `hidden/ground_truth.csv` and `.json` |
| Workflow 4: state changes as records, history never overwritten | `claim_events`, `policy_events`, `invoice_events`, `payment_events`; `investigation_events` is append-only, with triggers and a hash chain |
| Workflow 5: labels from documented rules | Every label has a `rule_id` and a reason: [DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) section 8 |
| Entities, keys, cardinality, bridge tables, effective dates, lifecycle states | [DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) sections 3–5; SQLite STRICT schema with foreign keys |
| ID conventions (`CLM-2026-000001`, `INC-…`, `PRV-…`, `INV-PRV-<provider>-…`, `INVG-2026-…`) | `generate/ids.py`; validation V-01 |
| Step 1: data dictionary | [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) |
| Step 4: 5,000 claims, 2,000 claimants, 500 providers, ≥ 8,000 edges; fixed seed; scale parameter | Scale 1.0 gives 5,000 / 2,000 / 500 / 12,560 edges; `--seed`, `--scale` |
| Step 5: five edge cases | EC-1 orphan policy, EC-2 overpayment, EC-3 duplicate invoice, EC-4 unrecorded ring links, EC-5 common address; all pass in [EVALUATION.md](docs/EVALUATION.md) |
| Step 6: derived values computed | `generate/lifecycle.py` (D-014); validation V-05 (arithmetic) |
| Step 7: separate ground truth, never leaked | `hidden/` folder; `scripts/policy_check.py` blocks label names in detector and app code; a test deletes `hidden/` and gets byte-identical detector output |
| Step 8: PK, FK, enums, dates, arithmetic, lifecycle, duplicate checks | `python -m fraudnet.validate`: checks V-01 to V-12, all PASS |
| Step 9: CSV, JSON, SQL, README, dictionary, generator command, seed, source manifest, validation summary | `data/output/input/{csv,json,sql}`, this README, `reports/source_manifest.json`, `reports/validation_summary.json` |
| Step 10: regenerate twice, compare checksums | `--reproducibility`: 41 of 41 files identical |
| Acceptance: planted patterns rank highly | R-precision 1.000 |
| Acceptance: explanations reference evidence | 341 IDs cited, all found in the input |
| Acceptance: labels separate from features | As in Step 7 |
| Acceptance: FP and FN rates measurable | [EVALUATION.md](docs/EVALUATION.md), [STRESS_V02.md](docs/STRESS_V02.md) |
| Exceptions and decisions exposed | `data_exception` (validator), cases with recommended actions (`HOLD_PAYMENT`, `REVIEW_PAYMENT`, `INVESTIGATE`), BLOCKED events |
| Lawful use | Synthetic data only, with no external data; built-in fictional value lists; validation V-12 |

## Repository layout

```
src/fraudnet/
  generate/     seeded generator, planting rules, labels, exports
  validate/     12 checks, data exceptions, reproducibility
  detect/       link rebuilding, scoring, explanations (never reads labels)
  evaluate/     metrics against labels, comparisons, stress test
  investigate/  cases, roles, append-only hash-chained history
  app/          Streamlit console (reads detector output, never labels)
  run.py        one command for every stage
streamlit_app.py  app entry point
tests/            pytest suite
docs/             data dictionary, architecture, decisions, evaluation and stress reports
data/sample/      committed scale-0.1 sample (data/output is git-ignored and rebuilt by the run)
scripts/          policy_check.py
```

## Documentation

| Document | What it holds |
|---|---|
| [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) | Every entity and field: type, rules, keys, cardinality, planting rules, metrics |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Detection theory, pipeline, scoring, evaluation design, workflow, limitations |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Every design decision, with the options considered, the reason and the trade-off |
| [docs/EVALUATION.md](docs/EVALUATION.md) | Measured results, comparisons and per-rule figures |
| [docs/STRESS_PLAN.md](docs/STRESS_PLAN.md), [STRESS.md](docs/STRESS.md), [STRESS_V02.md](docs/STRESS_V02.md) | The stress test: predictions made before any run, then the v0.1 and v0.2 results |
| [docs/AI_USAGE.md](docs/AI_USAGE.md) | How AI assistance was used |

## Limitations

- **Generated data only:** all data, including the stress scenarios, comes from this repository's generator. The results measure separation of documented patterns, not real-world fraud.
- **Exact matching:** identifiers are matched after standard clean-up, not fuzzily, so a single-character typo breaks a link.
- **Innocent co-residents:** flatmates and blended families with different surnames who share a phone or an account are flagged.
- **Demo roles:** staff roles are demo selectors, not authentication.
- **Hosted cases can reset:** on a hosted copy, the database is rebuilt at start-up, so cases opened there can be lost on restart. Save the history with `python -m fraudnet.investigate --data data/output export FILE`.
