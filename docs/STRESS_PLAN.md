# Stress test plan, with predictions made before any result

**Status: registered before any stress data was generated.** This file is committed and pushed on its own,
before the stress scenarios exist in code. The git history shows that every prediction below came first.

## 1. Why this test exists

The detector scores 1.000 on the development seed and on five unseen seeds (docs/EVALUATION.md). Those seeds
come from the same generator with the same settings, and the detector was designed knowing which patterns the
generator plants. So those results show the detector is stable on fresh draws of familiar data. They do not show
how it behaves on data it was not built for.

This test changes the data in ways the detector was not designed around: messy identifiers, rings that hide,
rings of unusual size, innocent groups of kinds the detector has never seen, and missing data. Each change has a
strength dial, and the report shows where the detector breaks.

## 2. Rules

1. **Frozen detector.** The detector under test is version 0.1.0 at commit
   `ddf09cc25bb0280ce1e6a479aaa8f0e28f13fa41`, with settings
   `src/fraudnet/detect/detector.toml` SHA-256
   `3bb79611587da9b45d1787db9e978df43e3004a3f1002b6b7aa51ff76e4bd67e`.
   Nothing under `src/fraudnet/detect/` changes until the v0.1 stress results are written to `docs/STRESS.md`.
2. **Predictions are never edited.** Section 5 stays exactly as committed. If a scenario has to be implemented
   differently from section 4 (for example, a level can't be planted), the change goes in section 8 as a
   dated amendment with its reason, before that scenario is run.
3. **Scoring a prediction.** A prediction is a **hit** when the mean over the stress seeds falls inside its
   range, and a **miss** otherwise. Ranges are not widened after the fact. The report lists every prediction
   with its result.
4. **Fixes are a new version.** If the results show a weakness worth fixing, the fix becomes detector v0.2,
   recorded as a new decision in docs/DECISIONS.md. v0.2 is scored on the confirmation seeds, which neither
   version has seen. The report keeps the v0.1 results and shows both versions side by side.
5. **Seeds.**
   - Stress seeds: 1111, 2222, 3333, 4444, 5555.
   - Confirmation seeds, used only for a v0.2: 6161, 7272, 8383, 9494, 10505.
   - None of these has been used before (D-025, D-028, D-029). Scale 1.0 (2,000 claimants), as in
     docs/EVALUATION.md.
6. **Labels.** Labels still come from documented planting rules, never random assignment (CLAUDE.md rule 6).
   New innocent groups get their own `B-*` rule IDs and reasons. The detector still never reads labels.
7. **The default stays unchanged.** With no scenario, the generator's output stays byte-identical to today's.
   A test checks this. Stress noise uses its own random generator, derived from the seed and the scenario name.

## 3. Measures

For each scenario, level and seed, the report gives:
- precision;
- ring recall, and recall per ring rule;
- false-positive rate per innocent rule, including the new ones;
- mean match Jaccard;
- the number of flagged networks.

Each figure is reported as the mean over the stress seeds, with the spread. Matching uses the same rules as
docs/EVALUATION.md: Jaccard of at least 0.5, and one network per group.

The report also includes:
- **Threshold sweep:** precision and recall for every flag threshold from 0.30 to 0.95 in steps of 0.05, on
  the development seed and the stress seeds with no stress applied.
- **Setting sensitivity:** each numeric setting in detector.toml moved down 30% and up 30%, one at a time.
  The report shows the change in precision and recall.
- **Investigator capacity:** fraud groups found in the top 10, 20 and 50 ranked networks.
- **Failure gallery:** the worst misses and false alarms, each with the detector's own evidence and the
  mechanism that caused it.

## 4. Scenarios

The strength `s` takes the values 0, 0.25, 0.5, 0.75 and 1.0, unless the scenario names discrete levels.
At s = 0, every scenario is the normal dataset.

### S1. Messy identifiers (claimant contact rows only; provider records stay clean)

| ID | Change, applied to each phone, email, bank and address field of each contact row with probability s |
|---|---|
| S1a | **Cosmetic formats** the detector's rules already cover: phone `(555) 123-4567`, `555.123.4567` or `555 123 4567`; email in upper case or with surrounding spaces; bank token in lower case; address in a different case or with the street suffix swapped between short and long forms. |
| S1b | **Same value, different form**, which the detector's rules don't cover. Each field picks one of two alternate forms at random: phone `+1 555-123-4567` or `001 555 123 4567`; email with a plus-tag (`ann.lee+claims@…` or `ann.lee+ins@…`); bank `ACCT 12345678` or `ACCT12345678`; postal code with a 4-digit suffix (`00123-0001` or `00123-0002`). |
| S1c | **Typos:** one character changed. A phone digit, a letter in the email name, a digit of the bank number, or a letter of the street name. |

### S2. Camouflaged rings (strength s)
- **Partial sharing:** in rings that share identifiers (R-RING-01, -03, -04, -05, -06), only
  `max(2, ceil((1 - 0.6 s) · ring size))` members get the shared values. At s = 1, that's 40% of each ring.
  The others still make the ring's claims.
- **Reworded stories (R-RING-02):** each copy of the ring's narrative has `round(6 s)` words swapped for a
  synonym from a fixed table.
- **Spread-out timing (R-RING-03):**
  - claims come up to `10 + 30 s` days after the policy starts (normally 10);
  - the burst window is `30 + 90 s` days (normally 30);
  - the invoice delay is up to `2 + 28 s` days (normally 2).
- **Smaller inflation (R-RING-04):** the invoice multiplier drops from 2.5–4.0 at s = 0 to 1.3–2.0 at s = 1,
  interpolated linearly.

### S3. Ring size and count (discrete levels)

| ID | Levels |
|---|---|
| S3a | Every ring has exactly 2 members. |
| S3b | Every ring has 15 to 25 members. |
| S3c | Twice, three times and four times as many rings per pattern (8, 12 and 16 instead of 4). |

### S4. Innocent groups the detector has never seen

Each is a separate level, with 20 groups at scale 1.0.

| ID | Rule | Group |
|---|---|---|
| S4a | B-ROOM-01 | 2 to 4 unrelated flatmates (different surnames) at one address at the same time. Half of the groups also share a landline phone. |
| S4b | B-FAMILY-02 | 2 to 4 relatives with **different** surnames (a blended or married family) at one address with a joint bank account. |
| S4c | B-FLEET-01 | 5 to 12 employees of one company, with different names and addresses, whose claim payouts go to the employer's single bank account. |
| S4d | B-AGENT-01 | A body shop (a REPAIRER that isn't busy, with 6 to 10 customers) that files its customers' claims using its own boilerplate narrative. The customers are in different cities and claim on different dates. |

### S5. Missing and placeholder data (strength s)

| ID | Change |
|---|---|
| S5a | **Gaps in the relationship records:** each claimant-pair row in `relationship_edge` is dropped with probability s. |
| S5b | **Missing bank details:** each claimant's bank token is removed, on all their contact rows, with probability s. |
| S5c | **Placeholder narratives:** each incident's narrative is replaced, with probability s, by one of `No description provided.`, `See attached report.` or `N/A`. |

### S0. A world with no fraud
- **Removed:** all fraud rings and the EC-3 duplicate invoices.
- **Kept:** the innocent groups and the edge cases EC-1, EC-2 and EC-5.

## 5. Predictions (v0.1, mean over the 5 stress seeds)

### 5.1 Hypotheses: where I expect the detector to break, and why

| # | Hypothesis | Mechanism in the v0.1 code |
|---|---|---|
| H1 | Messy addresses turn some families into false alarms. | The household explanation (`links._contact_links`) needs an exact address-key match. When a family's address is written differently but their shared phone still matches, the phone link is no longer explained, and identity can flag on its own. |
| H2 | Placeholder narratives create false story links. | `N/A` copied across claims at one provider gives IDF-Jaccard 1.0. Nothing checks whether a narrative carries enough information. |
| H3 | Reworded stories escape. | The story threshold of 0.85 is strict, and R-RING-02 rings rest on story evidence alone, scoring exactly 0.65 against a threshold of 0.6. |
| H4 | Rarity hides single-identifier rings when sharing becomes common. | Rarity is `clip(-log10(share)/1.5, 0.5, 1)`. When more claimants share banks or phones, a ring resting on one bank or phone link can fall below 0.6. At 3× rings, the bank share is about 9.8%, so the bank-link strength is about 0.57. |
| H5 | Unrelated co-residents and boilerplate filers are flagged. | Only same-surname households, buildings with 6 or more residents, common events and busy providers are explained away. Flatmates, blended families and a body shop's boilerplate text match none of these. |
| H6 | Big rings fragment. | Groups above 12 claimants are split by Louvain, so a ring of 20 can end up as pieces with Jaccard below 0.5, and the extra pieces count as false positives. |
| H7 | Two-person story or timing rings are missed by design. | The repetition principle (P5) halves weak families below 3 claimants, and isolated provider-based pairs join nobody. |
| H8 | Cosmetic mess and gaps in the relationship records do not matter. | Links are rebuilt from normalised raw values (P1), and the relationship register is only a hint. |
| H9 | Timing rings depend on their shared phone. | An EARLY_CLAIM_PAIR link is capped at 0.55, below the 0.6 flag threshold. R-RING-03 rings flag only because some members share a phone, and the one timing-only network on the development seed scores 0.42. When the phone match breaks, these rings are missed. |

### 5.2 Numeric predictions

Every row is a prediction for the mean over the 5 stress seeds. "Recall" means ring recall unless a rule is named.

| ID | Level | Prediction |
|---|---|---|
| P-S1a | every s | Precision ≥ 0.97, recall ≥ 0.97, false-positive rate on every innocent rule ≤ 0.01 (H8). |
| P-S1b-1 | s = 0.5 | Recall 0.60–0.90. Precision 0.55–0.90. B-HOUSE-01 false-positive rate 0.04–0.25 (H1). |
| P-S1b-2 | s = 1.0 | R-RING-01 recall 0.30–0.80. R-RING-02 recall ≥ 0.9, because it doesn't rest on identifiers. R-RING-03 recall 0.30–0.90 (H9). |
| P-S1c-1 | s = 0.5 | Recall 0.55–0.85. B-HOUSE-01 false-positive rate 0.04–0.25 (H1). |
| P-S1c-2 | s = 1.0 | Recall 0.10–0.30: with every identifier mistyped, only R-RING-02 survives (H9). EC-3 is still found, but it isn't a ring. Precision ≥ 0.85, because the family false alarms disappear once phones are mistyped too. |
| P-S2-1 | s = 0.5 | Recall 0.55–0.85. R-RING-02 recall ≤ 0.25 (H3). |
| P-S2-2 | s = 1.0 | Recall 0.15–0.50. Precision ≥ 0.95, because camouflage removes signals and doesn't create any. Mean match Jaccard below 0.85. |
| P-S2-3 | s = 0.25 | R-RING-02 recall ≤ 0.60 (H3: two reworded words per copy are enough to break most matches). |
| P-S3a | pairs | Recall 0.70–0.90. R-RING-02 recall ≤ 0.10 (H7). R-RING-01, -04, -05 and -06 recall ≥ 0.9. |
| P-S3b | 15–25 members | Recall 0.30–0.80. Precision 0.55–0.90 (H6). |
| P-S3c-1 | 2× rings | Recall ≥ 0.95. Precision ≥ 0.95. |
| P-S3c-2 | 3× and 4× | Recall 0.85–0.99 at 3× and 0.80–0.97 at 4×. The missed rings are mostly R-RING-01 rings that share a single bank (3×) or a single bank or phone (4×) (H4). Precision ≥ 0.95. |
| P-S4a | flatmates | B-ROOM-01 false-positive rate 0.30–0.65: the groups sharing a phone (H5). Recall ≥ 0.97. |
| P-S4b | blended families | B-FAMILY-02 false-positive rate ≥ 0.80 (H5). Precision 0.45–0.75. |
| P-S4c | fleets | B-FLEET-01 false-positive rate ≤ 0.30: the extra shared banks push bank rarity down, to a link strength of about 0.53. As a side effect, R-RING-01 rings that share only a bank are missed, giving recall 0.85–0.99 (H4). |
| P-S4d | body shops | B-AGENT-01 false-positive rate ≥ 0.80 (H5). Precision 0.45–0.75. |
| P-S5a | every s | Recall ≥ 0.97 and precision ≥ 0.97 at every level (H8). |
| P-S5b | s = 1.0 | Recall 0.65–0.90. R-RING-04 recall ≤ 0.25, and R-RING-06 recall ≥ 0.9, because it still shares a phone. |
| P-S5c-1 | s = 0.25 | Precision ≤ 0.70 (H2). |
| P-S5c-2 | s = 1.0 | Precision ≤ 0.40 (H2). Recall 0.60–0.90, because R-RING-02 loses its stories. |
| P-S0 | no fraud | At most 1 flagged network per seed. |
| P-T1 | threshold sweep | Precision and recall both 1.000 on the development seed for every threshold in (0.42, 0.65]. Recall falls once the threshold passes 0.65, because R-RING-02 rings score exactly 0.65. The safe band above the current threshold is therefore narrow, at 0.05. |
| P-T2 | settings ±30% | No more than 6 settings change precision or recall by more than 0.05 on the development seed. I expect them to come from: `flag_threshold`, the caps of SHARED_BANK, SHARED_PHONE, SHARED_EMAIL and SIMILAR_NARRATIVE, `story_min_similarity` and `reference_log10`. |

## 6. What would count against the detector

- **Precision:** any S1a or S5a level with precision below 0.95. That would mean entity resolution (P1) isn't
  doing its job.
- **No fraud present:** more than 1 flagged network per seed in S0.
- **Failure gallery:** any failure the gallery can't explain with a specific mechanism.

## 7. Planned outputs

Commands:
- `python -m fraudnet.evaluate stress --data data/output`, which writes `docs/STRESS.md` and
  `data/output/evaluation/stress.json`.
- The scenario settings live in `src/fraudnet/generate/scenario.py`.

The report places every prediction from section 5 next to its result, marked hit or miss.

## 8. Amendments

Every amendment must be added here, dated, with its reason, before the scenario it affects is run.

**A1 (8 Nov 2026, before any stress run). How implementation choices fill gaps in section 4.** No predicted
range changes. Each item below settles a detail section 4 left open:

- **S1 relationship register.** The relationship register is built from the messy values, as the source
  system would build it. Links it can't see then count as unrecorded, which is the normal rule.
- **S1 noise is drawn per cell.** Each field of each contact row gets one uniform draw and its own sub-seed.
  A cell changes when its draw is below the strength, so a stronger level changes a superset of the cells a
  weaker level changes, in the same world. Provider records and payment payee tokens stay clean.
- **S5a drops claimant-pair rows only:** SHARED_ADDRESS, SHARED_PHONE, SHARED_EMAIL and SHARED_BANK.
  Claimant-to-provider rows are kept.
- **The threshold sweep (P-T1) covers only networks the detector formed.** Groups whose links were all
  explained away never become networks, so they have no score to sweep.
- **Scoring the second sentence of P-S3c-2.** "The missed rings are mostly R-RING-01 rings that share a single
  bank or phone" counts as a hit when at least half of all missed rings at 3× and at 4× are R-RING-01 rings
  sharing a single identifier. The identifier count is read from the ring's planting reason.
- **Scoring the second sentence of P-T2.** "I expect them to come from …" is scored as its own prediction:
  a hit only if every sensitive setting is on that list.
- **Setting sensitivity.** Values are clipped to valid ranges: caps, factors, shares and similarities at 1.0;
  the busy-provider percentile at 0.99. A whole-number setting that rounds back to itself moves by 1 instead.
  The Louvain seed is not a tunable setting and is left out.

**A2 (8 Nov 2026, after the v0.1 results in docs/STRESS.md and before v0.2 met the confirmation seeds). Detector
v0.2 and its predictions.**

The v0.1 results are committed (docs/STRESS.md, 41 of 51 hits). The owner approved three changes (D-032):
- **F1:** a narrative with fewer than 6 distinct words is not a story.
- **F2:** standard identifier rules: phone last 10 digits, email `+tag` dropped, bank letters and digits only,
  postal code first 5 digits.
- **F3:** ring fragments are reported (evaluation only).

A co-resident explanation for flatmates and blended families was considered and **left out**: it would weaken
detection of rings that share an address.

v0.2 still scores 1.000 on the development seed and on unseen seeds 606–1010, with docs/EVALUATION.md unchanged.

**Rules for the v0.2 run:**
- v0.2 is scored on the confirmation seeds 6161, 7272, 8383, 9494 and 10505, which no detector version has seen.
- The v0.1 summary is kept in `docs/stress/stress_v0.1.json` and shown side by side with v0.2.
- The threshold and setting predictions (P-T1, P-T2) were registered for v0.1 only and are not re-scored.

Predictions for v0.2, as the mean over the confirmation seeds. They are encoded in
`src/fraudnet/evaluate/stress.py` as `PREDICTIONS_V02` and checked automatically.

| ID | Hypothesis or fix | Condition | Prediction |
|---|---|---|---|
| V-BASE.1 | F0 | baseline | no stress: precision ≥ 0.99 |
| V-BASE.2 | F0 | baseline | no stress: ring recall ≥ 0.99 |
| V-S1a.0 | H8 | S1a @ 0.25, 0.5, 0.75, 1.0 | precision ≥ 0.97 at every level |
| V-S1a.1 | H8 | S1a @ 0.25, 0.5, 0.75, 1.0 | recall ≥ 0.97 at every level |
| V-S1a.2 | H8 | S1a @ 0.25, 0.5, 0.75, 1.0 | every innocent rule's FP rate ≤ 0.01 |
| V-S1b.1 | F2 | S1b @ 0.25, 0.5, 0.75, 1.0 | recall ≥ 0.95 at every level (was 0.74–0.86) |
| V-S1b.2 | F2 | S1b @ 0.25, 0.5, 0.75, 1.0 | precision ≥ 0.95 at every level (was 0.61–0.74) |
| V-S1b.3 | F2 | S1b @ 0.25, 0.5, 0.75, 1.0 | every innocent rule's FP rate ≤ 0.02 |
| V-S1c.1 | H1 | S1c @ 0.5 | typos unchanged: recall 0.40–0.75 |
| V-S1c.2 | H9 | S1c @ 1.0 | typos unchanged: recall 0.05–0.35 |
| V-S2.1 | H3 | S2 @ 0.5 | reworded stories still escape: R-RING-02 ≤ 0.25 |
| V-S2.2 | H3 | S2 @ 1.0 | recall 0.55–0.85 |
| V-S2.3 | F3 | S2 @ 1.0 | counting ring fragments, precision ≥ 0.90 |
| V-S3a | H7 | S3a @ pairs | two-person story rings still missed: R-RING-02 ≤ 0.10 |
| V-S3b | H6 | S3b @ large | big rings still fragment: recall 0.45–0.80 |
| V-S3c.1 | H4 | S3c @ x2 | recall ≥ 0.95 at 2× |
| V-S3c.2 | H4 | S3c @ x4 | rarity crowding unchanged: recall 0.55–0.85 at 4× |
| V-S4a | H5 | S4a | flatmates still flagged: B-ROOM-01 FP rate 0.35–0.75 |
| V-S4b | H5 | S4b | blended families still flagged: B-FAMILY-02 FP rate ≥ 0.80 |
| V-S4c | H4 | S4c | fleets mostly not flagged: B-FLEET-01 FP rate ≤ 0.30 |
| V-S4d.1 | H4 | S4d | body shops not flagged: B-AGENT-01 FP rate ≤ 0.20 |
| V-S4d.2 | H4 | S4d | story rings crowded out: R-RING-02 recall ≤ 0.40 |
| V-S5a | H8 | S5a @ 0.25, 0.5, 0.75, 1.0 | register gaps still harmless: recall ≥ 0.97 |
| V-S5b.1 | H4 | S5b @ 1.0 | missing banks unchanged: R-RING-04 ≤ 0.25 |
| V-S5b.2 | H4 | S5b @ 1.0 | recall 0.60–0.85 |
| V-S5c.1 | F1 | S5c @ 0.25, 0.5, 0.75, 1.0 | precision ≥ 0.95 at every level (was 0.00–0.45) |
| V-S5c.2 | F1 | S5c @ 0.25, 0.5, 0.75, 1.0 | every innocent rule's FP rate ≤ 0.02 (was up to 0.82) |
| V-S5c.3 | F1 | S5c @ 0.25 | recall 0.90–1.00 at 0.25 (was 0.18) |
| V-S5c.4 | F1 | S5c @ 1.0 | recall 0.78–0.88 at 1.0: only story rings lost (was 0) |
| V-S5c.5 | F1 | S5c @ 1.0 | with no stories left, R-RING-02 ≤ 0.10 |
| V-S0 | H8 | S0 | no-fraud world: at most 2 flagged per seed |

**What these predictions say:**
- **The fixes work:** F1 should cure placeholder narratives (S5c), and F2 should cure the uncovered identifier
  forms (S1b).
- **Nothing else should move:** typos, rewording, ring size, rarity crowding, flatmates and blended families
  stay as v0.1 left them, and the report should show them still failing where they failed.
