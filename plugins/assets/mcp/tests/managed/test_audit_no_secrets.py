"""Events/facts carry ids + digests only: no header/credential values, no
argument bodies - verified by canary scan of every persisted artefact."""
from __future__ import annotations

import json
from pathlib import Path

from managed_helpers import ALLOWING, SERVER_SCOPE, TOOLS_ONE

HEADER_CANARY = "X-Header-Canary-9e3c"   # a literal header value of the definition
ARGS_CANARY = "args-body-canary-77ab"    # a tool-call argument body
CRED_REF = "cred-token-42ff"             # a credential reference id (opaque)


def test_full_lifecycle_leaves_no_secrets_or_bodies(harness):
    caller = harness.caller()
    revision = harness.install_remote(
        headers={"X-Key": {"literal": HEADER_CANARY},
                 "X-Cred": {"secretRef": CRED_REF}})
    authority = ALLOWING()
    manager = harness.manager(authority=authority)
    harness.factory.set(caller.session_ref, "srv-a", tools=TOOLS_ONE)
    lease, _, _ = harness.bring_up(manager, caller, "srv-a", revision,
                                   credential_revision="cred-rev-1")
    lease = harness.leases.get_lease(lease.lease_id, caller)
    manager.approve_tools(caller=caller, lease_id=lease.lease_id,
                          owner_id=lease.owner_id, tool_names=["echo"])
    manager.call_tool(caller=caller, lease_id=lease.lease_id,
                      owner_id=lease.owner_id, tool_name="echo",
                      arguments={"text": ARGS_CANARY})
    manager.close_lease(caller=caller, lease_id=lease.lease_id,
                        owner_id=lease.owner_id)

    # every durable artefact of the managed domain + the audit stream
    # (stores nest their table under their own root: <root>/managed/*.json)
    managed_dir = Path(harness.root) / "managed" / "managed"
    corpus = {
        "leases.json": (managed_dir / "leases.json").read_text(),
        "catalogs.json": (managed_dir / "catalogs.json").read_text(),
        "audit-events": json.dumps(harness.sink.events),
        "authority-seen": json.dumps(
            [{k: v for k, v in d.items()} for d in authority.seen], default=str),
    }
    for name, text in corpus.items():
        assert ARGS_CANARY not in text, f"argument body leaked into {name}"
        assert HEADER_CANARY not in text, f"header literal leaked into {name}"
        assert CRED_REF not in text, f"credential reference leaked into {name}"
    # positive controls: the ids/digests that SHOULD be there are
    leases_blob = corpus["leases.json"]
    assert json.loads(leases_blob)["leases"][lease.lease_id]["state"] == "closed"
    assert lease.endpoint_fingerprint in leases_blob  # fingerprint is endpoint, not secret
    assert any(e["kind"] == "lease-closed" for e in harness.sink.events)


def test_catalog_digests_are_the_only_tool_payload_stored(harness):
    caller = harness.caller()
    revision = harness.install_remote()
    manager = harness.manager()
    harness.factory.set(caller.session_ref, "srv-a", tools=TOOLS_ONE)
    harness.bring_up(manager, caller, "srv-a", revision)
    blob = (Path(harness.root) / "managed" / "managed"
            / "catalogs.json").read_text()
    data = json.loads(blob)
    assert len(data["observations"]) == 1
    stored = data["observations"][0]
    assert stored["status"] == "current"
    assert stored["tool_names_and_schema_digests"][0][1].startswith("sha256:")
    assert "inputSchema" not in blob  # schemas digested, bodies never kept
