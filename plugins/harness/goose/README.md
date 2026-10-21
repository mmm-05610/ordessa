# ordessa-harness-goose

The actual leaf now exports `GooseHarnessProvider` and `factory` through
`ordessa.harness_providers`. Its only Ordessa runtime import is
`ordessa_agents.sdk`. The former direct `AcpClient` subclass and
product staging duplicate are retired, without aliases or a direct spawn fallback.

Profile declarations use `goose.configuration/1`; validation preserves the
brand's existing pure native compiler and exact Harness definition pin. Prepare
uses externally approved immutable roots, command and nonsecret environment.
Nonempty native session configuration, credentials and resume currently refuse
explicitly. Async session opening delegates only to the original owner's restricted
`ManagedProcess.open_acp_session`; the plugin owns no writer, process or ledger.

Native argv remains approved command prefix followed by `acp`. The
`--dangerously-unauthenticated` flag (including `=...`) is refused even in the
approved prefix. Native auto-approval configuration remains refused.

The original six tests in `tests/clients/test_goose_client.py` remain unchanged:
initialize/native session; caller-selected permission cancellation; custom event
preservation; custom command/typed error; cancel notification; forbidden launch
flag. They target the retired client API and are **not passing migration evidence**.
Permission reverse replies, custom commands and cancellation are unavailable in
this bootstrap cut; integer protocol version 1 replaces the old string-version
fixture expectation. The forbidden-flag assertion is additionally represented in
new provider contract tests. The remaining original assertions still require
original-owner integration migration; no skip or compatibility client was added.

`tests/test_sdk_provider.py` adds pure plan/pin/security refusal, immutable output,
exact restricted-bootstrap delegation and SDK import-boundary coverage. These new
tests do not replace L1 protocol assertions. This migration slice ran no tests,
installed no dependencies, and made no real brand/model calls. Native capability
matrix entries remain unobserved and explicitly identify unsupported operations.
