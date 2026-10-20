# ordessa-harness-gemini-cli

Independent brand package (032): the gemini_cli native-channel facts and deploy
knowledge moved out of the retired root `pacthold.harness_kit` super-package. No
aggregate registration; the product selects brands explicitly.

## Current convergence slice

`ordessa.harness_providers` publishes `ordessa_harness_gemini_cli:factory`.
The provider imports only `ordessa_execution_agents.sdk`, validates the exact
Profile harness pin, and compiles the brand's pure configuration to an immutable
LaunchPlan with explicit caller-approved command/environment/directory inputs.
It owns no Unit, environment, process, session journal, credential expansion or
permission issuer. Import/prepare never starts native code or reads login state.

The old GeminiCliClient direct ProcessChannel path is physically retired, including
its duplicate product staging source; no compatibility re-export exists. Native
planning/compile knowledge remains brand-owned and is reused by the new provider.

This is NOT full Gemini runtime migration: resume, reverse requests and credential/session-model application remain unavailable.
Fresh guarded ACP initialize/session-new now delegates to the original Agent owner;
controlled real-peer acceptance covers Profile->prepare->start->session->prompt
and original Engineering BlobStore capture. Native Gemini/model was not invoked.
The new provider refuses these gaps; it never uses the retired client. The old
L1 client tests are retained as outstanding assertion migration, not skipped or
counted as green. Full suite currently has a collection error at absent `acp`;
those tests also reference the intentionally removed client API and need migration
to the original guarded Agent session owner. No dependency install was attempted.

Scoped provider/native-plan tests: 12 passed, including actual ProfileService
pre-commit validation against the real Gemini provider. No real Gemini process,
model call, user login or production readiness was tested. Controlled fresh
bootstrap coverage is recorded in the convergence STATUS; the old L1 suite is
still an explicit unmet gate.
