"""Managed bidirectional ACP channel (Server orchestration side).

The seam contract is fixed by `docs/acp-channel-minimal-seam.md` and the
approved target tests in `tests/integration/acp_orchestration`.  This package owns three
facts and nothing else:

  * the connection registry (who holds a channel, on which project, through
    which transport), keyed by (harnessId, projectId) so a re-acquire returns
    the same connection and never a silently different binding;
  * the run record for a channel: exactly one Work Core execution in the
    existing `server_turns` ledger, opened at acquire and ended by release or
    by the Agent's own exit — the state machine is the product's, reused, not
    rewritten here;
  * `channel_run_view`, the single adaptation point where the ledger's real
    terminal facts are read as the client-facing run vocabulary.

It never parses an ACP frame: the relay is a byte-line pipe.  The Server does
not speak on the client's behalf during setup or teardown, and in-flight
requests are answered by nobody when a channel ends — that is the honest
outcome the contract pins.

The transport itself comes from a composition-injected `launch` callback.
The native composition plugs the Harness plugin's production access entry in
there (`access_entry.AccessEntryTransport`): the entry launches the declared
adapter, and the Server speaks ACP through it only after the entry's own
`connect` succeeded - control-plane replies and events are consumed at that
bridge and never relayed, ACP lines are.  Which entry is live is a deployment
fact, never a branch on a Harness name here.

Physically extracted from `ordessa_server` (core-cleanup stage 3): the ACP
channel registry, its transports and its release path belong to the Harness
domain; the wire methods and the stream route are registered by
`ordessa_harness.server_acp.plugin`.
"""
from ordessa_harness.server_acp.access_entry import AccessEntryTransport
from ordessa_harness.server_acp.registry import AcpChannelRegistry
from ordessa_harness.server_acp.runs import channel_run_view
from ordessa_harness.server_acp.transport import NDJSONTransport

__all__ = ["AccessEntryTransport", "AcpChannelRegistry", "channel_run_view",
           "NDJSONTransport"]
