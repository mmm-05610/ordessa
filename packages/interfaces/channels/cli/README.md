# CLI channel source

`src/ordessa_interfaces/channels/cli/` is the generic channel owned by the
`ordessa-interfaces` distribution: declarative metadata, multi-level command
matching, help, the `agent-tools/1` envelope, `--save-result` and bounded field
references. It imports no domain owner.

The former standalone `ordessa_cli_runtime` distribution and the
`ordessa-agent` parser were retired on 2026-10-19. The single `ordessa` CLI
(`apps/cli`) and the interface channel replace them. The old runtime's remote
Profile/call semantics are covered by
`apps/cli/tests/test_remote_mode.py`; Profile mutation/CAS semantics are
covered by `apps/cli/tests/test_lower_cli_flow.py`.
