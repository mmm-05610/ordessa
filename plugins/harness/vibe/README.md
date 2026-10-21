# ordessa-harness-vibe

The actual leaf now exports `VibeHarnessProvider` and `factory` through
`ordessa.harness_providers`. Its only Ordessa runtime import is
`ordessa_agents.sdk`. The former direct `AcpClient` subclass and
product staging duplicate are retired, without aliases or a direct spawn fallback.

Profile declarations use `vibe.configuration/1`; validation preserves the
brand's existing pure native compiler and exact Harness definition pin. Prepare
uses externally approved immutable roots, command and nonsecret environment.
Nonempty native session configuration, credentials and resume currently refuse
explicitly. Async session opening delegates only to the original owner's restricted
`ManagedProcess.open_acp_session`; the plugin owns no writer, process or ledger.

The reviewed native ACP launch shape remains unpinned. Prepare preserves the
externally approved **complete** command prefix verbatim, adding no guessed flags.
It requires explicit `VIBE_HOME` alongside HOME/XDG/TMPDIR/PATH to avoid ambient
shared-home discovery. This is planning support, not installed Vibe acceptance.

The original five tests in `tests/clients/test_vibe_client.py` remain unchanged:
initialize/no-load capability; native session and prompt; custom event payload;
typed error and timeout unknown; owned process close. They target the retired
client API and are **not passing migration evidence**. They require migration to
original-owner integration, including explicit separate terminate authority.
No skip, replacement legacy client or weaker assertion was added.

`tests/test_sdk_provider.py` adds pure plan/pin/security refusal, immutable output,
exact restricted-bootstrap delegation and SDK import-boundary coverage. These new
tests do not replace L1 protocol assertions. This migration slice ran no tests,
installed no dependencies, and made no real brand/model calls. Native capability
matrix entries remain unobserved and explicitly identify unsupported operations.
