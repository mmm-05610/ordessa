# Units

Units composes an immutable Agent Profile with an existing Environment. Its
consumer API is `ordessa_units.api.UnitManager`, `Unit` and `UnitInteraction`;
`ordessa_units.assembly` binds them to the original store, journal, invocation
authority and records. It requires Python 3.12, matching its direct dependencies.

The local host selects `build_local_unit_owner(...)`, securely provisions a fresh
`OperationJournal(..., acp_turn_opt_in=True)`, then calls
`owner.assemble(journal=journal)`. This returns one public Manager. The host must
provide a finite `UnitRunPermission` backed by its existing access authority;
the builder does not manufacture host grants or authenticate a human.

```python
manager = owner.assemble(journal=journal)
unit = manager.create(owner.spec, owner.authorization())
assert manager.get(unit.identity) is unit
interaction = unit.interaction(owner.authorization())
response = interaction.prompt({"prompt": [{"type": "text", "text": "Reply OK."}]})
event = interaction.next_event(timeout=2)  # native ACP event
interaction.disconnect()
closed = unit.close(owner.authorization())
```

Normal prompt and `request("session/prompt", ...)` use the same internal recorded
turn path. Missing explicit journal opt-in refuses before dispatch. A selected
canonical effect guard without its original Engineering binding also refuses;
there is no unrecorded fallback. The native response and events are transparent.
`cancel()` sends native cancellation; `disconnect()` closes the writer. Neither
stops the Unit. Reconnection and cross-process resume are unavailable.

Close reports the original stop/release outcome and releases only this Unit's
Environment Use. The caller retains its Environment, store and journal. The
public `assembly.process_input.UnitProcessInputBinding` optionally binds one
host-supplied transient input to the exact admitted launch; it creates no new
process authority or credential store.

The execution-only Pi example and current validation receipts are under
`docs/implementation/packages-convergence-20261012/execution/units-api/`.
The package still depends on C1 contracts. Their cross-owner retirement remains
open under the total TODO (14); standalone runtime qualification does not imply
that architectural retirement or default product acceptance is complete.
