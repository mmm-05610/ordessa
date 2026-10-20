# ordessa-harness-copilot

Independent brand package (032): the copilot native-channel facts and deploy
knowledge moved out of the retired root `pacthold.harness_kit` super-package. No
aggregate registration; the product selects brands explicitly.


## SDK migration status (2026-10-19)

The actual leaf now exports `CopilotHarnessProvider` and the explicit
`ordessa.harness_providers` factory. The old direct-launch client and duplicate
product staging client are removed without aliases. Pinned Profile validation,
native argv compilation, approved explicit HOME/XDG/COPILOT_HOME values and
immutable LaunchPlan are implemented as pure preparation. No ambient executable
lookup, credential inheritance, permission decision or process spawn occurs here.

Native protocol `copilot-cli-jsonrpc/3` is **not ACP**. Managed startup and interaction
remain unavailable until the original Agent owner supports this native protocol;
`open_session` raises `NATIVE_PROTOCOL_BOOTSTRAP_UNAVAILABLE`. The composition
must refuse unsupported protocol before launching. Session/resume/replay and
deferred session configuration are explicitly refused, never replaced by ACP or
fresh session fallback. Pure native facts/compiler APIs remain planning-only.

Original `tests/clients/test_copilot_client.py` assertions are retained unchanged
as outstanding protocol acceptance requirements; they import the retired API
and therefore are not migrated/passing evidence. No test was run in this leaf
worker. Runtime completion, native peer L1 and real CLI L2 are not claimed.
The targeted `tests/test_sdk_provider.py` covers only the new preparation, pin,
entrypoint and fail-closed boundaries; integration runs it separately.
