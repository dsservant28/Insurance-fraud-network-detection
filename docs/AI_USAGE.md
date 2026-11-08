# AI usage

The challenge allows AI assistance. This document says how it was used.

## Tools

Claude Code, Anthropic's coding assistant, was used in the editor and terminal throughout the build.

## What the assistant did

- **Design:** proposed designs before any code was written: the generator's planting rules, the detector's principles, the scoring, the evaluation protocol, the stress test and the app layout. Each design went to the owner as a short plan, and work started only after the owner approved it.
- **Code and docs:** wrote code, tests and documentation in small steps, one module at a time.
- **Checks:** ran the test suite and the policy check before reporting any step as done.
- **Decisions:** recorded each decision in [DECISIONS.md](DECISIONS.md) with the options considered and the trade-off.

## What the owner did

- **Approvals:** approved or changed every plan before work began. For example, the owner:
  - chose the four-eyes rule and the Cytoscape.js graph;
  - asked for the stress test after reviewing the perfect scores;
  - rejected the co-resident explanation;
  - cut the first app mockup down to an investigator-first page.
- **Commits:** reviewed every diff and made every commit and push personally. The assistant never commits or pushes.
- **Ownership:** owns the submission and the final decisions.

## Safeguards on the assistant's work

- **Project rules:** `CLAUDE.md` sets the rules the assistant must follow: no label leakage, determinism, history kept append-only, exact ID formats, synthetic data only, and plan before code.
- **Policy check:** `scripts/policy_check.py` runs as a hook on every edit and in the tests. It blocks label names in detector and app code, unseeded randomness and the wall clock in the generator, and hard-coded secrets.
- **Results never written by hand:** every reported number comes from a generated report (`docs/EVALUATION.md`, `docs/STRESS*.md`).
- **Stress predictions committed first:** they were pushed before any stress code or data existed, so the git history shows they weren't adjusted after the results.

## Prompt history

The full prompt history is in `prompts/`. It was kept out of git during the build and added at the end of the challenge (D-012).
