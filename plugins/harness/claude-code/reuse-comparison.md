# Claude Code channel selection, AU003

Observed worktree baseline: `77a1d8a92c95f607db1671e8c700d96e4ccabe3f`.
Read-only comparison and implementation in the independent Claude package.
Models 0, Claude process starts 0, installs 0, user configuration changes 0.

| Candidate | Source evidence | Decision and limitation |
| --- | --- | --- |
| Official Python Claude Agent SDK | Fixed commit `9c69ce7aced5cdf2aa1ac86fe62e877b4962de8b`, `client.py`, `types.py`, public Transport interface; source re-read 2026-10-05 | Preferred explicit adapter; SDK owns query/control/read task lifecycle. Its runtime is not installed/verified here. Require existing exact version and fenced custom transport. |
| Zed Claude ACP adapter / old Ordessa ACP bridge | Existing `docs/implementation/agent-tools/night-harness-expansion/evidence/claude-code-channel-report.md`, `plugins/harness/REMOVALS.md`, prior ACP packaging | Additional SDK-to-ACP translation and maintenance surface; no demonstrated advantage needed by this scope. Not selected, not restored and no fallback. |
| Existing native planner and limited stream-json consumer | Existing native planner 43 C, limited consumer 22 C; prior report explicitly says no real CLI/SDK compatibility evidence | Preserve safety fixes, move family protocol to provider package; keep as explicitly selected limited alternative, not proof that SDK/native Unit production is complete. |

Primary pinned source links:

- [Public SDK client](https://github.com/anthropics/claude-agent-sdk-python/blob/9c69ce7aced5cdf2aa1ac86fe62e877b4962de8b/src/claude_agent_sdk/client.py)
- [Native typed messages and Result origin](https://github.com/anthropics/claude-agent-sdk-python/blob/9c69ce7aced5cdf2aa1ac86fe62e877b4962de8b/src/claude_agent_sdk/types.py)
- [Exposed custom transport contract](https://github.com/anthropics/claude-agent-sdk-python/blob/9c69ce7aced5cdf2aa1ac86fe62e877b4962de8b/src/claude_agent_sdk/_internal/transport/__init__.py)
- [SDK default subprocess implementation](https://github.com/anthropics/claude-agent-sdk-python/blob/9c69ce7aced5cdf2aa1ac86fe62e877b4962de8b/src/claude_agent_sdk/_internal/transport/subprocess_cli.py)
- [SDK component metadata](https://github.com/anthropics/claude-agent-sdk-python/blob/9c69ce7aced5cdf2aa1ac86fe62e877b4962de8b/pyproject.toml)

The Transport interface is intentionally exposed by the SDK with an upstream
warning that future releases may change it. The exact optional SDK dependency
pin and same-task lifetime check make this upgrade boundary explicit.

The custom Transport route does not apply SDK subprocess CLI flags. The
provider's existing pure planner and deployment's owned isolated transport must
establish stream-json, verbose and stdio permission routing explicitly. Changing
SDK options cannot be assumed to configure the injected transport.

Current implementation adds real public SDK calls (connect/query/interrupt/
set_model/receive_messages/disconnect), not an Agent engine or copied SDK Query.
All native writes are gated at the custom transport, including SDK-generated
control requests and callback responses. Unanswered approval remains an explicit
callback responsibility; the adapter does not grant any permission itself.
Upstream permission rules/settings may preempt callbacks, so the native write
authority must cover full native effects; callback existence alone is not a
strong per-tool authorization claim.

The existing limited protocol file is copied with only its transport import
changed, retaining unknown framing, one outstanding turn, explicit initialization,
session matching and once-only permissions. The original product source remains
until the main author's shared AU003/AU004 consumer removal. This slice does not
claim A15 passed while that original remains.

Evidence layers: package syntax compile exit 0. Main executor's earlier snapshot
was **96 passed / 0 failed, exit 0, 6.84s**; later fixed-plan/provider identity,
Unicode LF framing, finite JSON/UTF-8 and nonexecutable-artifact counterexamples
are not covered by that snapshot. Final source collection below is **112 tests,
exit 0, 0.12s**, not an execution result:

```bash
PYTHONPATH=plugins/harness/claude-code/src:packages/backend/harness-transport/src /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c plugins/harness/claude-code/pyproject.toml plugins/harness/claude-code/tests --collect-only -q
```

All executions must be rerun serially by the main executor. No P (real
Claude/SDK process) or M (real task)
evidence. Actual executable and installed SDK versions remain unmeasured.
