# AU003 Codex channel reuse decision

Observed repository checkpoint `77a1d8a92c95f607db1671e8c700d96e4ccabe3f`.

| Candidate | Fixed source evidence | Decision |
| --- | --- | --- |
| Official app-server | Existing N002 source evidence pins official docs and npm 0.157.1 Apache-2.0; product `native_clients/codex.py` Git blob `58f9e85ab7ec4ac4ed6de3aa345815fd12b72f09`; nested turn/thread completion and approvals already corrected | Selected original native protocol, preserve fixes and add UnitRecords ownership |
| Official SDK | No installed SDK source artifact established by this worktree audit; N002 official app-server offers required bidirectional approval/session primitives without another SDK | No unsupported SDK-version claim, no dependency install; revisit only with a verified artifact |
| Existing Go ACP bridge | `plugins/harness/pi/vendor/acp-adapter/pkg/codexacp/runtime_runner.go` blob `764e633dd4d86fb23cccf1e302e3787b55df8c34`; bridge speaks ACP around upstream Codex runtime; native pins in `configuration/model/live_service.py` are @agentclientprotocol/codex-acp 1.1.14 | Mature ACP retained for old paths but not selected: required direct native protocol would otherwise be wrapped/reinterpreted |
| Old Harness app-server | `src/pacthold.harness_kit/codex/app_server/provider.py` blob `a25a012e84dd63fda56f1ef891ebb38b5051389f`; imports retired pacthold_runtime_compat/work_core, auto-declines reverse requests and runtime sandbox composition | Do not revive legacy dependencies or import this private provider; reuse native identity knowledge only |
| Old model runtime | `src/pacthold.harness_kit/codex/configuration/runtime.py` blob `bd581272b770eed9d9bd6ffa4821ab43d253db44` pins ACP 1.1.14 and shared NativeLiveModelRuntime | Not an app-server config CAS contract; do not present it as native atomic configuration owner |

The known historical npm artifact is truncated and the launcher dependency is broken (N002). This package has **no executable default** and no fallback. PATH's desktop `/usr/lib/chatgpt/resources/codex` is discovery-only and was not executed. Source migration is not runtime validation. A genuine process/task test needs explicitly approved isolated installation/root, trusted native evidence, and scope/lease ownership.

Explicit injected ports are documented in provider.py. Projection must bind the original UnitRecords instance, not copy its database. channel_factory.open must perform its installation/root checks and managed stdin cut before the first native write. Configuration changes lack a production CAS/evidence adapter and are honestly unavailable. There is no new state ledger to guess completion from actual values.

## Fixed native configuration source follow-up

Official tag `rust-v0.157.1` resolves via GitHub API annotated tag `ac0e23e5232692b95268583c8278c50b8c436d2b` to commit `36650394c5b38c2990ccf2a3457165ca3e9d9726`. Checked primary sources:

- [native configuration read/write service](https://github.com/openai/codex/blob/36650394c5b38c2990ccf2a3457165ca3e9d9726/codex-rs/app-server/src/config_manager_service.rs): native expectedVersion precondition, user layer scope, write status/version and readback.
- [batch parameters and static-settings reload limits](https://github.com/openai/codex/blob/36650394c5b38c2990ccf2a3457165ca3e9d9726/codex-rs/app-server-protocol/schema/typescript/v2/ConfigBatchWriteParams.ts): defaults writing does not hot-reload existing thread model/effort.
- [current thread observation](https://github.com/openai/codex/blob/36650394c5b38c2990ccf2a3457165ca3e9d9726/codex-rs/app-server-protocol/schema/typescript/v2/Thread.ts): loaded configured model/effort, nullable when unavailable; not per-turn execution telemetry.

This refines the initial conservative configuration gap: original journal dispatch binding and ownerSerialized native-defaults management are implemented conditionally, with production evidence/continuation ports still required. No external native atomic compare guarantee is asserted, no schema pin change occurred, and live Codex 0.159.0 has not been treated as equivalent.
