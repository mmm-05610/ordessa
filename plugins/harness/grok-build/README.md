# ordessa-harness-grok-build

Actual runtime replacement: `GrokBuildHarnessProvider` and `factory` are exposed via
`ordessa.harness_providers`. Only `ordessa_agents.sdk` is an Ordessa
runtime import. All original Unit RuntimeProvider, projection, lease/grant,
termination ledger, direct ProcessChannel/client and server-plugin adapters are
physically retired. No old class aliases, fallback or second instance owner.

Profile validation fixes the exact Harness definition ref. Prepare is pure;
native argv is approved command prefix plus
`agent stdio`. Context must supply the standard approved work/home/XDG/tmp roots
and distinct `grok-build-home` root, explicit PATH/HOME/XDG/TMPDIR/GROK_HOME, and no
credential-shaped environment keys or CredentialRefs. Native home cannot alias
HOME. Physical directory/source verification belongs to external preparation and
current lifecycle authority, never plugin `stat`, login lookup or ambient env.

Async open_session delegates exactly to original-owner
`ManagedProcess.open_acp_session` and returns that original session observation.
No invocation, raw fd/writer, grant, resource or Use enters this provider.
Only fresh bootstrap is supported. Existing native initialization facts included
an `initialized` notification and non-negotiating peers; current original-owner
integer-v1 two-phase bootstrap has NOT been validated against this real brand.
No claim of real session, model call, permission callback or production acceptance
is made by pure provider tests.

Pinned model-configuration facts remain intentionally empty: dialect absent,
native target None, version range empty. Channel pins do not create model facts.
`compile_config` accepts only an empty map and otherwise refuses
MODEL_CONFIGURATION_UNAVAILABLE. No old AdapterContext/intent/target runtime is
retained. Model readback, custom configuration, credentials, authenticate,
resume/load, reverse permission replies, cancellation, list/close and recovery
remain unavailable unless implemented by the original Agent owner explicitly.
Grok authentication is a client-initiated extension, not a standard ACP auth fallback; no xAI login or credential management is performed.

Packaged native ACP artifacts, registration bytes and model/dialect facts remain
explicit offline inputs, not active registration/readiness or runtime fallbacks.
No installed artifact or credential-backed native acceptance is implied.

All original test files and assertions remain untouched. Current source counts
(non-parametrized definitions, not passing case counts):
client 27, prepared client 23, Unit provider 27,
runtime process 21, termination 14, server plugin 9,
configuration 12, model configuration 16, distribution 1
.
They target retired APIs and require migration to original Agent/endpoint owners;
the historical assertion inventory is preserved, with no skip/delete/fake-green.
In particular frame correlation, no retry, original source/authority, receipt vs
completion, unknown handling, caller-decided permission and termination proof
must survive that migration. New `tests/test_sdk_provider.py` covers only pure
SDK pins/plans/refusals/import boundaries and restricted bootstrap delegation.
No tests/install/build, model/network/management call or Git write was run by
this migration slice. Full brand migration acceptance remains incomplete.
