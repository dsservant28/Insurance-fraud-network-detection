# AI usage

The challenge allows AI assistance. This document says how it was used. In short: the owner set the direction and made the design decisions, and an AI coding assistant implemented them under the owner's review.

## The owner's decisions

**Rules and scope**
- Wrote the project rules in `CLAUDE.md`:
  - no label leakage;
  - determinism;
  - append-only history;
  - exact ID formats;
  - synthetic data only;
  - plan before code.
- Set the bar for the project: every planned part delivered, and an app whose design matters as much as the architecture.
- Decided how work would happen: plan first, one module at a time, every change reviewed, and every commit and push made personally.

**Detection and evaluation**
- **Scoring and testing:** chose rarity-weighted scoring with corroboration, and evaluation on a development seed plus unseen seeds, from the options presented.
- **Questioning the perfect scores:** challenged the perfect results as possibly too easy, and asked for the system to earn a rating of at least 9.
- **Stress test:** this led to the stress test, which the owner approved together with the rule that predictions are pushed to git before any stress run.
- **v0.2 fixes:** reviewed the v0.1 failures and approved exactly two fixes for v0.2.
- **Co-resident rule:** rejected an extra explanation for flatmates and blended families, because it would also hide real rings that share an address.
- **v0.2.1:** approved the determinism fix after the bug was reported.

**Investigation workflow**
- Chose the four-eyes rule: whoever opens a case can never confirm it.
- Kept the history append-only, with refusals recorded.

**The app**
- **The graph:** chose an interactive graph library over Streamlit's built-in charts, to make the network view distinctive.
- **The mockup:** reviewed it and rejected the overview as too busy. Decided the app is for the investigator first, with one question per page in plain language, and added a separate **How it works** page for the maths.
- **How it was built:** stopped further mockups and had the app built page by page, reviewing each in the browser.
- **Design calls along the way:**
  - chose the ring-shaped network graph from the mockup over the first built version;
  - sent back the first **Cases** page as disorganised and set the standard for every page: symmetric, aligned and uncluttered;
  - asked for the dossier panels to line up;
  - spotted that the page menu was missing.
- **Deployment:** deployed the app on Streamlit Community Cloud from the owner's own account.

**Quality and delivery**
- Asked for the build to be checked against every line of the problem statement, which added the one-command run and the README.
- Directed the README:
  - explain the problem first, then the design and its versions;
  - remove decorative badges and symbols;
  - put the live link beside the title;
  - drop the limits section.

## What the assistant did

- **Options and implementation:** proposed options with trade-offs for the owner to choose from, then implemented the chosen ones in code, tests and documentation, and recorded each decision in [DECISIONS.md](DECISIONS.md).
- **Checks:** ran the test suite and the policy check before reporting work as done.
- **App screenshots:** screenshotted each app page in a browser to check what the owner would see.
- **Bugs:** reported its own bugs when tests or checks found them, for example the hash-seed dependence in the Louvain split (D-035), and fixed them once the owner approved.

## Safeguards

- **Policy check:** `scripts/policy_check.py` runs after every edit and in the tests. It blocks label names in detector and app code, unseeded randomness or the wall clock in the generator, and hard-coded secrets.
- **No hand-written results:** every reported number comes from a generated report (`docs/EVALUATION.md`, `docs/STRESS*.md`).
- **Order proven by git:** the stress-test predictions were pushed before any stress code or data existed, so the history shows they weren't adjusted after the results.

## Prompt history

The full prompt history is in `prompts/`. It was kept out of git during the build and added at the end of the challenge (D-012).
