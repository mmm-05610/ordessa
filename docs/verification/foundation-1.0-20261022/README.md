# Foundation 1.0 — integration review, 2026-10-22

Baseline: `230795bd764f5b6a132eb0822284d512fdf0a616`.
Scope: Codex/Pi native interactions, Local/OpenShell execution, CEL/JeV Decision,
and the existing Server/CLI product composition. This is a capability milestone,
not a claim that every historical package, desktop or Engineering workflow works.

## Integration findings and repairs

1. A turn-completion notification could complete an unrelated pending request.
   Reproduced with a read request preceding a turn. Only acknowledged pending
   operations now match notifications; Codex also matches the acknowledged turn
   id. Duplicate/out-of-order notifications cannot end another turn. Ambiguous
   session-level terminals become unknown instead of choosing an operation.
2. Concurrent replies with different request ids could answer one reverse request
   twice. Reproduced both with successful writes and a lost write receipt. The
   original SQLite pending record now atomically reserves the reply before await;
   unknown delivery never grants another write. A proven not-sent result may be
   retried. No second callback store or authority was added.
3. The native cutover had omitted the original instance writer-epoch fence.
   The original epoch is captured in the operation and rechecked in the existing
   SQLite write guard at the physical write, including reverse replies. The
   migrated lifecycle-race test preserves the zero-bytes and original-record
   assertions. Async close now awaits dispatch cancellation before record cleanup.
4. The Server Decision owner resolved a captured identity without re-verifying it
   before background dispatch. It now consults the original instance authority
   at each scope resolution. A real-authority revocation test proves zero model
   calls after acceptance followed by revocation.
5. An unresolved Decision claim stayed pending after its process disappeared.
   Query now reports pending only for an owner-held running task, otherwise
   unknown; duplicate requests never redispatch. Running keys include the scope.
6. Migrated integration tests mixed the in-process DTO with the wire JSON shape,
   expected an acceptance state to remain unchanged after completion, or still
   used the retired native method. These callers now exercise the new surface
   while retaining original ownership, no-double-effect and lifecycle assertions.
   The new legacy test skip was removed; historical failing expectations remain
   visible in the non-gating ledger.

## Verification layers

The current CI workflow contains the exact reproducible green gates. Install with
Python 3.12, the workspace requirements and `python_workspace.py --install`, then
install the declared `packages/execution/environments[openshell]` extra. Use the
same-source environment; multi-root distributions must be rebuilt after changes.

- Post-review combined gates: **496 passed, 1 skipped in 83.44 s**. The skip
  is the pre-existing host-installed Pi condition; no new skip was introduced.
- Workspace metadata: 34 distributions validated; diff whitespace check passed.
- The combined gate includes the independent default Server wheel closure: its
  own pip check, installed Profile operation and exclusion of upper-layer wheels.
- Four returned real-task artifacts were independently retested during review:
  **6 passed each**, with the original test bytes unchanged. This verifies the
  returned artifacts; it does not rerun the model or sandbox session.
- Focused changed-consumer audit initially exposed the migration defects above.
  Four unrelated historical expectations remain: three proof-manifest hash
  mismatches in `test_root_agent_work_assembly.py`, one old `profiles` capability
  id in `test_sdk_product_owner.py`. They are registered in known-issues and not
  included in a whole-repository green claim.

No model call, user-service restart or real-user database migration occurred in
this integration review. Tests launch and clean up their own local peers/servers.

## Earlier implementation-time real evidence

[Sanitized receipt summaries](receipts.json) bind the local raw receipts by SHA256.
Raw run directories, credentials, account details and host-specific logs are not
published. These receipts predate the review fixes above; those fixes are backed
by controlled regressions and fresh wheel-closure verification, not a repeated
real-model matrix.

| Scenario | Observed result |
| --- | --- |
| Codex / Local | Frozen moving-average defect repaired; host 6 passed; tests unchanged |
| Pi / Local | Same defect repaired; host 6 passed; tests unchanged |
| Codex / OpenShell | Same defect repaired; artifacts retrieved; host 6 passed; sandbox deletion confirmed |
| Pi / OpenShell | Same defect repaired; artifacts retrieved; host 6 passed; sandbox deletion confirmed |
| CEL → JeV → CEL | Accepted in 0.34 s; decision `nine-larger`; one model call; durable evidence; reported usage 316 input / 31 output tokens |
| Long Codex turn | 103.86 s turn, 0.364 s submission, 93 events; another turn in the same thread |
| Cancel / stop | Notification delivery and process termination distinguished; unconfirmed work unknown after stop |
| Restart | Original records reopen; unconfirmed accepted native work unknown; no redispatch |
| Installed product | 34-wheel noneditable installation; imports outside worktree; Profile, exec, CEL and native describe/start/stop |

The repaired source SHA256 for all four retained task artifacts is
`9550556bd215c522977ff12924458d71167bc0964beba02b72b86cb349703b60`.
The unchanged test SHA256 is
`7254966c7e3977d825c200dcbf803f0ecd13c44a59da7e89fc5a5c44cb6d9c80`.
The original frozen-case tests are the oracle, not the Agent's completion message.

## Runtime retirement and remaining limits

Removed narrow runtime: `sdk/native_contracts.py`, `sdk/native_operations.py`,
Server `agent_bindings/native_access.py`, and the native configuration factory.
Current default consumers use `agents.native.*` over the same original records,
endpoint and environment owners. No compatibility forwarder was introduced.
Historical upper-layer ledger tests are not a supported runtime consumer and
still need their separate retirement/migration; whole-repository retirement is
not claimed.

OpenShell native management is limited to list/inspect/health. Mutations use the
same existing lifecycle/exec/files owner. Local does not isolate; OpenShell is a
container, not a VM, and active Landlock enforcement was not established in the
best-effort run. Real approval callbacks and unrestricted Pi concurrent prompts
are not claimed. USD budget reservation is not implemented. Engineering, Units,
new task routing, automatic provisioning and full desktop delivery remain outside
this integration. See [known issues](../../reference/known-issues.md).
