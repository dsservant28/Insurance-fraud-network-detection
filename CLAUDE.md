# CLAUDE.md — Project rules for Claude Code

> Owner: Jagadeep Varma Penmetsa. This is an individual 72-hour code challenge (YottaFlex AI, Associate AI FDE).
> AI assistance is allowed and is disclosed in `docs/AI_USAGE.md`. The owner reviews and approves every change.

## 1. What we are building (one paragraph)
An insurance **fraud-network detection** system. Part A: a deterministic synthetic-data generator that creates
claimants, policies, incidents, claims, providers, invoices and payments, plants labelled fraud rings, benign
look-alikes and 5 labelled edge cases, and writes a hidden ground-truth file. Part B: a detector that reads ONLY the
input data, rebuilds relationships from raw attributes, scores and ranks suspicious networks, and explains each with
evidence. Part C: evaluation against ground truth (precision, recall, FP rate, FN rate, ranking quality).
Part D: investigation workflow with append-only event history. Full spec: `docs/problem_statement.md`.

## 2. Hard rules (never break these)
1. **No label leakage.** Code under `src/fraudnet/detect/` must NEVER read ground-truth files or columns
   (`ground_truth`, `is_fraud`, `ring_id`, `planted`, `issue_type`). Only `src/fraudnet/evaluate/` may read ground truth.
   `scripts/policy_check.py` enforces this automatically (hook + `tests/test_policy.py`).
   Never add a `# policy: allow` marker without the owner's explicit approval.
2. **Determinism.** All randomness in the generator comes from one `numpy.random.default_rng(seed)` passed down
   explicitly. No `import random`, no `np.random.<func>` globals, no `datetime.now()` / `date.today()` in generator code.
   Default seed: `20261022`. Same seed + same scale ⇒ byte-identical outputs.
3. **Parents before children.** Master data (Claimant, Policy, Incident, Provider) is created first; children use only
   existing parent IDs — except deliberately planted, labelled edge cases.
4. **Derived values are computed, never randomly generated** (totals, balances, paid amounts, scores, statuses, day gaps).
5. **History is append-only.** Status changes are new rows in `*_events` tables. Never overwrite or delete history.
6. **Ground truth comes from documented planting rules**, not random assignment. Every label has a `rule_id` and reason.
7. **Exact ID formats:** `CLM-2026-000001`, `INC-2026-000001`, `PRV-000001`, `INV-PRV-<provider-id>-000001`
   (counter per provider), `INVG-2026-000001`. Zero-padded, immutable, identical across every file.
   Other entities: see `docs/DECISIONS.md`.
8. **Synthetic data only.** No real personal data, no secrets/keys in the repo.
9. **Explainability.** Every flag/score must carry evidence that references concrete IDs and values.

## 3. Repository layout (keep to this)
```
src/fraudnet/
  generate/     # synthetic data generator (seeded, scale parameter)
  validate/     # PK/FK/enum/date/arithmetic/lifecycle/duplicate checks + reproducibility check
  detect/       # edge rebuilding, fraud indicators, network building & scoring, explanations (NO ground truth)
  evaluate/     # compares detector output to ground truth; metrics
  investigate/  # Investigation entity + append-only events
  app/          # UI / API (decided in DECISIONS.md)
tests/          # pytest
data/           # generated outputs (git-ignored except a small committed sample if decided)
docs/           # problem statement, data dictionary, decisions, requirements trace, AI usage
prompts/        # prompt history (required by YottaFlex) — auto-logged by hook
scripts/        # policy_check.py and helpers
```

## 4. How to work with me (the owner)
- **Plan first.** For any non-trivial task, propose a short plan and wait for approval before writing code.
- **Small steps.** One module/feature per step, with its tests. Keep diffs reviewable.
- **Explain the why.** When you make a design choice, add/append an entry in `docs/DECISIONS.md`
  (decision, alternatives considered, reason, trade-off).
- **Never commit or push.** The owner reviews diffs and commits manually with meaningful messages.
- **Run checks before saying "done":** `python scripts/policy_check.py` and `pytest -q`.
- **Don't invent results.** If something isn't run/verified, say so.
- Ask when a requirement is ambiguous; otherwise make a reasonable assumption and record it in `docs/DECISIONS.md`.

## 5. Stack
Windows dev machine. Python 3.13.0, pytest. Database, UI and libraries are decided by the owner and recorded in
`docs/DECISIONS.md` before they are used. Free / locally runnable only. Avoid heavy dependencies.
Secrets (e.g. DB passwords) come from environment variables / `.env` (git-ignored), never from code.
