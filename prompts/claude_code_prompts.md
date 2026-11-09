# FraudNet

> **Record status:** These are reconstructed prompts based on the supplied project brief, README and timestamped prompt history. They are not verbatim historical submissions. Timestamps mirror the source timeline for sequencing only; they do not prove these prompts were sent at those times.

## Prompt 001
- Time: 2026-11-07 13:17:40 IST

```text
I have read the challenge brief. Before we touch any code, first break the requirements into a proper traceable delivery plan. I want the entities, dependencies, edge cases, measurable outputs and acceptance criteria mapped. dont jump straight into implementation without checking the full scope. Call out anything ambiguous in the brief and tell me what decisions we need to make.
```

## Prompt 002
- Time: 2026-11-07 13:21:42 IST

```text
Please inspect the current repo state, not some old snapshot you have in context. Check the actual Python version, files already committed, dependency declarations and git status. If you cant actually inspect github or my local workspace, tell me clearly, dont assume things and give me old data.
```

## Prompt 003
- Time: 2026-11-07 13:25:25 IST

```text
Check SQLite against every requirement in this challange, not just whether it can store the data. I dont want to choose a database just becuase its easy. Check foreign keys, transactions, append-only investigation history, constraints, reproducibility, concurrent use and deployment. Also compare Streamlit alone with a seperate React and FastAPI setup, what do we really gain? Recommend the smallest architecture that still meets the actual scope.
```

## Prompt 004
- Time: 2026-11-07 13:27:20 IST

```text
Before we lock the stack, list the tradeoffs and what exactly we are giving up with this choice. Keep the first release maintainable, dont add services just because everyone uses them in production.
```

## Prompt 005
- Time: 2026-11-07 13:59:26 IST

```text
Lets make the data dictionary a proper design document, not just a list of columns. Include field types, nullability, allowed values, uniqueness, units, validation rules, keys, cardinality and lifecycle. Challenge the volumes in the brief if there is a good reason, but dont skip any required case just to make generation easier. Explain how ground truth stays separate from detector inputs.
```

## Prompt 006
- Time: 2026-11-07 17:02:14 IST

```text
Approve the seven proposed data-design points only after checking that they cover the brief. Keep the prompts folder out of the public git history for now; it is an audit artefact and we can decide how to publish it at submission. Do not delete local records.
```

## Prompt 007
- Time: 2026-11-07 17:06:11 IST

```text
Check the git index properly before changing the ignore rules, i dont want accidental tracking. I want to understand whether the prompt files were ever committed, whether removing them from tracking would rewrite history, and what the least disruptive option is. Don't force-push or rewrite commits.
```

## Prompt 008
- Time: 2026-11-07 17:51:38 IST

```text
Leave the initial setup commit as it is, no need to keep changing history. We can make a clean follow-up commit when the implementation is ready. Please don't amend history just to make the repository look tidy.
```

## Prompt 009
- Time: 2026-11-07 17:57:07 IST

```text
Proceed with the next data model stage, but first check the ignore file and show exactly which generated files, secrets, env folders and local prompt records are excluded. Don't use broad patterns that hide source files or documentation.
```

## Prompt 010
- Time: 2026-11-07 18:08:13 IST

```text
Where exactly are we creating the SQLite db and which command is actually populating it? I need to inspect the actual rows, indexes and relationships in VS Code. Please make the database path configurable and document it rather than scattering paths through the code.
```

## Prompt 011
- Time: 2026-11-07 18:13:39 IST

```text
Build the smallest useful way to inspect the database first, dont over engineer this part. I want to open the generated database and verify sample joins before we move on. Include a repeatable command and don't make the inspection tool part of the production pipeline unless it genuinely belongs there.
```

## Prompt 012
- Time: 2026-11-08 00:54:15 IST

```text
Do one independent review of the generated schema and data before we proceed further. Check primary-key uniqueness, foreign-key integrity, date ordering, arithmetic totals, lifecycle transitions, enum values, duplicate handling and deterministic output. Dont just rerun the generator and say its fine, check the validation logic also.
```

## Prompt 013
- Time: 2026-11-08 01:12:46 IST

```text
Review this completed reference project and its README as a benchmark, not something to copy blindly. Identify useful product ideas, missing requirements, architecture trade-offs and deployment lessons. Also propose a realistic commit sequence; commit count by itself is not a quality metric.
```

## Prompt 014
- Time: 2026-11-08 01:18:43 IST

```text
Before i run the git commands give them one by one and tell me what each command is staging. Confirm there are no generated datasets, secrets or local-only files in the commit. For deployment, assess whether our chosen stack can be hosted reliably and what persistence limitations we need to disclose.
```

## Prompt 015
- Time: 2026-11-08 01:26:53 IST

```text
Here is the current git status and log. Reconcile it with the implementation plan. Check whether the commits represent coherent changes and whether the remote is up to date. Do not infer a successful push from a local commit.
```

## Prompt 016
- Time: 2026-11-08 11:11:27 IST

```text
The ground truth file is present now, check the separation properly. Review the boundary around it: detector modules, app modules, imports, configuration, logs and generated reports must not leak labels or label-derived fields. Add an automated policy check that fails if the boundary is violated. The evaluator can read labels; the detector and app cannot.
```

## Prompt 017
- Time: 2026-11-08 11:35:01 IST

```text
Give me the remaining work in dependency order, what has to happen first and what can wait. Separate data engineering, detector, evaluation, investigation workflow, UI, documentation and deployment. Include what is already verified versus merely implemented.
```

## Prompt 018
- Time: 2026-11-08 11:36:16 IST

```text
We have a target to finish by 5 PM tomorrow, so plan backwards from that. Build a schedule around dependencies and verification, not optimistic coding estimates. Identify the critical path and the tasks that can run in parallel without creating integration risk.
```

## Prompt 019
- Time: 2026-11-08 11:38:16 IST

```text
Continue with the plan we agreed, but dont start skipping quality checks because of time. Keep the quality gates in place even if the schedule gets tight: tests, data validation, label isolation and reproducibility are not optional. If a task is blocked, report the blocker instead of silently skipping it.
```

## Prompt 020
- Time: 2026-11-08 12:01:13 IST

```text
Before writing the detector, show me the complete architecture and data flow end to end. Explain how raw records become candidate links, how benign explanations reduce evidence, how groups are formed, how scores are calculated and how an investigator can trace every claim back to source records. Include failure paths and measurable outputs.
```

## Prompt 021
- Time: 2026-11-08 13:19:59 IST

```text
The architecture direction looks reasonable, but i want the graph to be useful for an investigator, not just some decorative network picture. Compare practical options for Streamlit, including filtering, hover details, node selection, layout stability and performance. Also keep the eventual investigator experience in scope while finalising the backend.
```

## Prompt 022
- Time: 2026-11-08 13:23:31 IST

```text
Proceed with the selected architecture, but record why we selected it and why the other options were rejected. Keep interfaces between generation, validation, detection, evaluation and investigation explicit so that the UI does not contain business logic.
```

## Prompt 023
- Time: 2026-11-08 13:47:00 IST

```text
Review the architecture document against the code we actually have now, dont assume both are matching. I want to catch architecture drift early: module boundaries, data contracts, score semantics, label access and persistence behaviour must agree. Update the document only where the implementation decision is deliberate.
```

## Prompt 024
- Time: 2026-11-08 15:06:18 IST

```text
Continue, but a passing unit test alone doesnt mean the detector is correct. Check the actual intermediate outputs and make sure the evidence shown to an investigator is the same evidence used to calculate the score.
```

## Prompt 025
- Time: 2026-11-08 15:18:23 IST

```text
The evaluation job is completed now. Inspect the full report, not only the headline metrics. Check per-pattern recall, false positives on benign groups, edge-case handling, ranking quality and whether every explanation reference resolves to a real record.
```

## Prompt 026
- Time: 2026-11-08 15:27:51 IST

```text
The refreshed detector evaluation completed too. Compare it with the previous run and explain any changed rows or metrics. If output changed without a code or data change, investigate nondeterminism before accepting the result.
```

## Prompt 027
- Time: 2026-11-08 15:31:45 IST

```text
Move to the next planned stage only after recording the evaluation findings and any known limitations. Keep the report reproducible from a clean command.
```

## Prompt 028
- Time: 2026-11-08 18:26:10 IST

```text
Give me the actual numbers from the latest run and mention the evaluation scope beside every metric. Distinguish development-seed results from unseen-seed results, and don't combine them into one impressive-looking figure.
```

## Prompt 029
- Time: 2026-11-08 18:27:08 IST

```text
Assess this architecture like a strict technical evaluator, dont be generous with the score. Score the core idea, evidence model, graph construction, explainability, data integrity and operational workflow separately. Give reasons for deductions; don't inflate the score to be encouraging.
```

## Prompt 030
- Time: 2026-11-08 18:30:08 IST

```text
These perfect metrics are actually worrying me. Since the generator and detector were developed together, fresh random seeds from the same generator are not independent evidence of generalisation. Design a stronger challenge: freeze predictions first, define adversarial scenarios before running them, and publish misses as well as hits. Dont tune the detector against the hidden answers, that defeats the whole point.
```

## Prompt 031
- Time: 2026-11-08 18:33:35 IST

```text
Yes we need an adversarial evaluation, but make sure the test is not designed in a way that makes our detector look good. Recommend a defensible scenario set and explain how to prevent leakage between scenario design, detector changes and scoring. Include benign hard negatives, malformed identifiers, missing data, altered narratives and graph structures that can cause accidental chaining.
```

## Prompt 032
- Time: 2026-11-08 18:34:51 IST

```text
The current changes are pushed now. Verify the remote commit before starting the next experiment, then freeze the detector version that the stress plan names. We need an auditable baseline.
```

## Prompt 033
- Time: 2026-11-08 18:41:59 IST

```text
The next change is pushed as well. Check the commit and tag the exact detector revision used for the baseline report; don't rely on a branch name that may move.
```

## Prompt 034
- Time: 2026-11-08 19:13:43 IST

```text
Confirm the stress plan and expected outcomes are already committed before you run any scenarios. I want the repository history to demonstrate that predictions existed before the stress-test results.
```

## Prompt 035
- Time: 2026-11-08 19:27:19 IST

```text
How much of the stress suite is still running, and what remains after it finishes? Give me the real blockers and verification steps, not some guessed finish time.
```

## Prompt 036
- Time: 2026-11-08 19:38:02 IST

```text
The stress command has failed, find out why first. Inspect the traceback and reproduce the failure with the smallest scenario. Don't change detector behaviour just to make the test pass; first determine whether this is a test harness issue, data issue or genuine algorithm failure.
```

## Prompt 037
- Time: 2026-11-08 19:45:45 IST

```text
Proceed with the fixes we approved. For the co-resident rule, leave it out of this release and document the trade-off. We should not suppress legitimate suspicious groups using an overly broad household heuristic.
```

## Prompt 038
- Time: 2026-11-08 20:09:35 IST

```text
The fix is pushed. Verify that the commit contains only the intended changes and rerun the targeted tests plus the affected stress scenarios.
```

## Prompt 039
- Time: 2026-11-08 20:28:46 IST

```text
Is the stress run actually complete? Check the process or task result and tell me which report was produced. Don't infer completion from elapsed time.
```

## Prompt 040
- Time: 2026-11-08 20:33:51 IST

```text
The v0.2 stress test has completed. Compare every prediction against the frozen scenario expectations and classify misses. Report the denominator and scenario coverage, not only the hit count.
```

## Prompt 041
- Time: 2026-11-08 20:53:01 IST

```text
Run the revised detector against the original stress seeds as a regression check. Confirm that improvements on the new scenarios did not break the previously passing cases.
```

## Prompt 042
- Time: 2026-11-08 21:04:53 IST

```text
Lets move to the interface now, but dont start by adding colours and decorating the existing layout. First define the investigator's jobs and the information hierarchy for each screen. I want a distinctive, restrained visual system with consistent spacing, typography and data density. Use charts only where they answer a question.
```

## Prompt 043
- Time: 2026-11-08 21:18:38 IST

```text
The current page is showing way too much information at once. Review the risk queue from an investigator's perspective: what decision must they make first, what evidence is essential, and what can move into a detail view? Reduce cognitive load without hiding material risk information.
```

## Prompt 044
- Time: 2026-11-08 21:21:37 IST

```text
Design the first page for an investigator, not for a data scientist or developer. Keep the ranking, severity, concise reason and next action visible. We can add a field if it supports a real decision, but justify every metric and remove anything that is only there to look technical.
```

## Prompt 045
- Time: 2026-11-08 21:43:33 IST

```text
Before moving to the next page, do a requirement traceability check with the original challenge brief. Map each requirement to code, UI or a test. Identify anything that is only described in documentation but not actually implemented.
```

## Prompt 046
- Time: 2026-11-08 21:57:40 IST

```text
The first page is pushed. Review the diff and open the app at the actual viewport size. Then move to the next page using the same design system; don't introduce a new visual language for every screen.
```

## Prompt 047
- Time: 2026-11-08 22:26:04 IST

```text
Stop all background work properly for tonight. Check that no evaluation or server process is still running, preserve the current state and don't start new tasks. We will continue from the committed checkpoint.
```

## Prompt 048
- Time: 2026-11-09 10:24:47 IST

```text
Start the Streamlit app and first verify the current branch and working tree, dont overwrite anything i changed. I have adjusted the second page locally; inspect the live rendering before making further edits and don't overwrite my changes.
```

## Prompt 049
- Time: 2026-11-09 10:29:12 IST

```text
Compare the current network graph with the reference image i gave. I prefer the reference because its hierarchy is clearer. Reproduce the interaction and visual structure where appropriate, but preserve our actual node and edge semantics. Don't fabricate graph data to make the screenshot look better.
```

## Prompt 050
- Time: 2026-11-09 10:37:30 IST

```text
Now move to the Cases page, but first inspect the investigation schema and transitions. First inspect the investigation schema, event model and permitted state transitions. The UI should expose only valid actions; it must not bypass the service layer or let the user edit sealed history.
```

## Prompt 051
- Time: 2026-11-09 10:48:11 IST

```text
This page is not organised properly at all, the information is all over the place. Rework its hierarchy and alignment. Separate the case list, selected-case summary, action area and event history. Remove repeated fields and secondary data that compete with the next decision. Keep the layout balanced at normal desktop widths and usable on a smaller screen.
```

## Prompt 052
- Time: 2026-11-09 10:56:39 IST

```text
On the dossier page, the evidence panel does not align with the graph and the lower chart is pushed too far down. Fix the layout using a consistent grid and container heights. Please don't change the graph design or evidence content; this is an alignment correction.
```

## Prompt 053
- Time: 2026-11-09 10:58:47 IST

```text
The alignment looks fine now, check it once at smaller screen width also. Before the next page, check the page at more than one viewport width and confirm there is no horizontal overflow or clipped evidence text.
```

## Prompt 054
- Time: 2026-11-09 11:03:58 IST

```text
Continue to the next page. Reuse the shared components and styling tokens. Keep page specific logic out of the common layout unless it is actually reusable.
```

## Prompt 055
- Time: 2026-11-09 11:13:26 IST

```text
The unseen seed evaluation has regenerated, compare it with the earlier report. Compare it with the previous published report and identify whether the change is due to detector code, generator output or evaluation configuration. Keep the old report available so the history remains understandable.
```

## Prompt 056
- Time: 2026-11-09 11:28:22 IST

```text
Apply the reviewed change, but check the complete diff first and dont remove any of my existing edits. Preserve existing user edits, run the page tests and verify that the app still starts from a clean checkout.
```

## Prompt 057
- Time: 2026-11-09 11:37:58 IST

```text
The evaluation task completed. Check its exit status, output files and metric calculations. Confirm the report is generated from the intended detector revision and the expected seed list.
```

## Prompt 058
- Time: 2026-11-09 11:45:05 IST

```text
Before implementing the How it works page, first decide what a new reviewer should understand within 2 minutes: the business problem, why naive shared-value matching fails, the detector stages, one worked example and the limitations. Avoid turning this into a copy of the architecture document.
```

## Prompt 059
- Time: 2026-11-09 11:45:53 IST

```text
Implement the explainer page with that structure, keep it simple but technically correct. Keep the language plain and the example numerically consistent with the detector output. Every score and evidence item shown must come from the real pipeline or be clearly marked as an example, dont mix the two.
```

## Prompt 060
- Time: 2026-11-09 11:49:37 IST

```text
Proceed to the final planned implementation step. Check the acceptance criteria for the full workflow before calling it complete.
```

## Prompt 061
- Time: 2026-11-09 12:22:15 IST

```text
There is a big change in the data between runs, something is not right i guess. Find the exact files and rows that changed. Check seed, scale, generator version, ordering, timestamps and environment-dependent behaviour. We need to know if this is expected regenerated data or some nondeterminism in the pipeline.
```

## Prompt 062
- Time: 2026-11-09 12:25:21 IST

```text
The hosted app is opening at the URL now, check the actual pages and not only whether the link loads. Verify the user-facing pages, initial load, navigation, graph rendering and error handling. Also check what happens after a restart, because SQLite state on an ephemeral host may not persist. Don't claim you tested anything you cannot access.
```

## Prompt 063
- Time: 2026-11-09 12:30:43 IST

```text
Lets make the README the front door of the project, this is what most people will see first. A new reader should understand the insurance-fraud problem before seeing implementation detail. Then show the workflow, architecture, data model, detector reasoning, version history, measured results, app screenshots and local setup. Keep it readable and navigable; diagrams should explain actual flows, not decorate the page.
```

## Prompt 064
- Time: 2026-11-09 12:38:07 IST

```text
Review the README as a technical reviewer who has never seen this repo before. Check factual accuracy against the code and reports, clarity of the claims, links, diagrams, installation steps and whether the limitations are honest. Give me a strict score with specific deductions.
```

## Prompt 065
- Time: 2026-11-09 12:42:05 IST

```text
Put the live application link where a visitor can find it immediately. Also test the local setup instructions from a clean environment, not just from the developer's existing virtual environment. List any missing prerequiste or command that a new user may get stuck on.
```

## Prompt 066
- Time: 2026-11-09 12:52:07 IST

```text
The README still doesnt look organised properly, the sections feel uneven. Reorganise the whole document with consistent section hierarchy, spacing and table widths. Remove the decorative colour legend row; it adds no information. Do not change technical claims unless you verify them against the repository.
```

## Prompt 067
- Time: 2026-11-09 12:54:41 IST

```text
Run the complete test suite from a fresh clone or clean environment, not from the current setup only. Capture the command, exit code and test count. Also run the policy and reproducibility checks; a successful app launch alone is not a release gate.
```

## Prompt 068
- Time: 2026-11-09 12:58:24 IST

```text
Place the live app link beside the project title so it is immediately visible. Use a plain descriptive label. Check that the Markdown renders correctly on GitHub.
```

## Prompt 069
- Time: 2026-11-09 12:59:27 IST

```text
Remove that arrow emoji, it looks a bit too AI generated. It looks decorative and doesn't fit the rest of the README. Prefer clear text and consistent formatting over visual symbols.
```

## Prompt 070
- Time: 2026-11-09 13:02:21 IST

```text
Remove the known limits section from the main README as requested, but do not erase the underlying limitations from the technical record. Keep relevant caveats in the stress-test or architecture documentation so the project remains honest.
```
