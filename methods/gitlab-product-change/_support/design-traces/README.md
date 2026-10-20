# Synthetic design-trace timelines

These are synthetic report snapshots for illustrating the report schema. They are not executed method runs, GitLab evidence, or validation results. Times, links, role assignments, decisions, deployments, and metrics are invented. The report values are authored claims only.

## success.report.json

1. Synthetic issue enters Validation backlog with an assigned PM DRI. Problem validation and design/solution validation run over the same time window; their evidence references and proceed/approve decisions satisfy this design scenario's recorded exit conditions.
2. Build planning is recorded with scope, priority, and milestone. The development report identifies a revision, and the test and MR sections report checks and review.
3. The synthetic sequence records a merged revision, staging canary, production canary/smoke, and promotion with version/environment references. This report says nothing about any real GitLab deployment.
4. The outcome section contains a synthetic measurement and the closure decision is complete after the reported verification. The next condition would be the scheduled follow-up measurement; a changed result would require a new decision and report.

## rework-wait-resume.report.json

1. Validation, design, planning, and an initial development/review report are recorded. A synthetic reviewer request opens a blocker on 2026-10-03; the issue remains in the verification/review context while an external response is awaited.
2. The before-wait snapshot records the unresolved blocker and the exact affected report revision. The exit condition is the required external clarification/correction, not an Ordessa wait.
3. After the synthetic blocker is reported resolved on 2026-10-04, a new revision records the correction and resumed checks/review. The rework item records its trigger, updated revision, and completion outcome; the after-wait snapshot identifies the resumed state.
4. The later MR/deployment fields report staging and production verification plus version bindings. A separate outcome measurement is recorded afterward. A further failed check would create another external rework cycle and a new report; this method graph has no loop.

## reject-postpone.report.json

1. A synthetic feature issue enters problem validation. The PM reports insufficient evidence, records the reject/defer decision, and provides the rationale and next evidence needed.
2. Design and solution validation are marked skipped/deferred with owner and rationale. Planning/build/testing/review/deployment remain not started; there is no MR, merge, release, or deployment claim.
3. The closure decision postpones reconsideration until new customer evidence is available. That evidence is the next entry condition for a new validation attempt and a new report. The word rejected here is an external product decision value; it does not mean the artifact-capture operation returned its rejected outcome.
