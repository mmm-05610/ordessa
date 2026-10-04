# 013 production-wire / artifact guard checkpoint

Parent source HEAD: 4b320cad97c2e53d3972f224e50302449514a6e3. Primary alone runs tests serially and commits; scoped Luna reviewers never run behavior suites or Git. This report records an intermediate repair checkpoint, not CONTROLLED_SCOPE_DONE.

## Source guard

Public production `agent.submitInput` requires a Mapping expectedConditions before submission service/journal construction. Backend-only SubmissionInput may still capture its trusted facts internally. Caller conditions remain expectations: new submissions compare against freshly resolved native/config authority; existing keys compare the original durable record then query only. Omission cannot bypass click-time source/base conditions. The review does NOT claim omission could redispatch an already spent key.

`production-wire-conditions-guard.txt`: first regression 4 failed / 62 passed, exit1. Missing-dependency fixtures could not pre-read unavailable conditions; their inputs now explicitly use non-authoritative placeholder mappings to exercise the original capability/policy refusal. Original assertions preserved. `production-wire-conditions-verified.txt`: 66 passed / 0 skipped, exit0, including new public-wire omission refusal, zero submission journal/native effects and five real product SIGKILL windows.

## Build and artifact evidence

Fresh full-closure DEB from parent4b, no --skip-pip: retry exit0, 211689720 bytes, SHA256 707b8fbb2e5894b8dbdb1c6c4aee8e6b082bbdac1a6f13b28b2ff904e6ea7e98. The original interrupted 3876-byte residual is preserved and rejected. artifact-build-receipt.json records both attempts and relocation of the extracted artifact physically outside checkout; no installation occurred. Derived bundle manifest / extension lock remain traceable to this actual build, not to the upcoming source guard commit.

`artifact-controlled-4b` first run FAIL: copied runner lacked its F5 sibling; artifact was under repo marker; namespace package origin was None; runtimeIdentity was mistakenly included in its own prerequisite gate. Kept raw. These were QA defects, not inherited product failures. Namespace paths are now all realpath checked; DI probe runs only after static prerequisites and final all-checks still require runtime identity.

`artifact-controlled-guarded-4b`: exit0, all 11 emitted scene statuses pass: isolated shipped Python closure/imports, shared public UI token runtime identity, actual product Server wire/Environment/Agent/SQLite, default and no-Profile two rounds (createWithConfig then existing), original-key backend replay/history, packaged F5 consumers. Controlled Native/FP/policy are explicitly injected; backend replay uses submit with same captured key to prove no redispatch, separately from frontend query-only recovery.

`artifact-f5-guarded-4b`, `artifact-f5-browser-rerun-4b`, `artifact-f5-xvfb-4b`: failed React runs retained. Corrected nonempty ELECTRON_RUN_AS_NODE=0, hidden-window frame waiting and diagnostics, without modifying assertions. `artifact-f5-shared-owner-verified-4b`: exit0; API consumers, independent OS process file-CAS (one written/one conflict), React hook + nonReact selector on SAME owner instance, snapshot identity/selection/update/unmount/release pass. Owned temporary Xvfb only; no user desktop credentials/services. Node is external QA tool, not a shipped requirement. Sandbox remains unproven (--no-sandbox fixture).

Artifact runners now refuse checkout fallbacks, external runtime overrides and realpath escapes from canonical opt/ordessa. `artifact-path-counterexamples.{json,txt}`: all5 intentional violations refused (exit1 expected), no product code loaded. Build script makes required Electron runtime resources hard failures and emits bundle manifest in owned output/stage rather than mutating tracked source. Fresh build of this changed source is still required.

## Remaining / next ready

`artifact-journal-shared-modules-4b.txt`: exit0, two real IndexedDB SIGKILL windows pass (capture commit and possibly-submitted marker commit). Cold browser reopens the same origin/storage; only original target/key query occurs. Initial protocol-before-ready and missing shared module failures remain recorded. Captured unknown has zero result observations; possibly-submitted unknown has one retained observation. No submit/retry/normalization occurs during recovery.

`artifact-frontend-product-valid-key-4b.txt`: exit0, actual shipped Chat adapter/Agent contracts/IndexedDB and actual shipped Server composition pass createWithConfig then existing in withProfile and withoutProfile fixture variants; both frontend/backend cold restart queries the original two keys with no extra native effects. This is controlled public composition, not full Desktop product manifest variants or genuine brands. Earlier failure logs remain, including the uppercase fixture request ID rejection (zero native effects).

That rejection exposed a separate production Chat bug: raw UUID request IDs may begin with a digit, outside frozen Environment local-ID grammar. Future Chat IDs now use chat- prefix; Durable submit validates before any journal/wire operation. Existing journal keys remain unchanged and reconcile queries their original IDs. Serial source regressions are in progress; a new committed-source full build and affected artifact reruns remain necessary.

Three-brand native admission producers/default protected fingerprint remain unavailable rather than fabricated; no real model/data/keys were used. Full Server inherited/new-red ledger remains as previously recorded, not replaced by these narrow greens. UI01 stays queued, 8 tasks /12 cases separate, until core safe boundary; no visual changes substitute for core gaps.

## Request identity and independent case review

Serial source regression: Agent contracts first 93 pass/1 fail; its new legacy recovery fixture had only captured, which journal intentionally refuses to record as dispatched. Input now includes the persisted possibly-submitted marker; accepted/original ID/query-only assertions unchanged. Rerun 94 pass/0 skip; Chat frontend 95 pass/0 skip; npm typecheck exit0. Original failing evidence retained. New request IDs are validated before any durable/wire action; old saved IDs are queried unchanged.

Independent Luna evidence audit: controlled no-Profile Server assembly and frontend adapter do not establish complete alternate Desktop experience or Profile A→M2→prompt-only B→A UX. Two frontend kill windows and five backend product kill windows are separate evidence, not a combined five-window cross-side run. F5 shared-instance and OS-process CAS do not alone prove independently packaged third-party plugin loading, full A98/A103 lifecycle/storage matrix, or two actual Desktop windows. A108/A111 actual IME/GUI remains unverified. Original T012-09..13 remain unchecked until full required conditions.
