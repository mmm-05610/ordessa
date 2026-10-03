"""Fake ports and snapshot builders for the T06/T07 permission/secret tests.

Only fakes - the production authority wiring waits for the
``codex/011-permissions-api-ready`` checkpoint (gap G3) and the credential
wiring uses the injected host layers (gap G7); nothing here touches the
network or spawns (sealed by ``conftest.py``).
"""
from __future__ import annotations

from backend.resolve import McpEffectiveSnapshot


class RecordingAuthority:
    """Fake of the Q5 PermissionAuthority port; records every consultation
    so the tests can pin that a gate-1 refusal never reaches gate 2."""

    def __init__(self, decision=None, error: Exception | None = None):
        self.calls: list = []
        self.decision = decision
        self.error = error

    def authorize_tool_call(self, *, principal=None, session_ref=None, lease_id=None,
                            tool_name=None, args_digest=None, policy_revision=None):
        self.calls.append({"principal": principal, "session_ref": session_ref,
                           "lease_id": lease_id, "tool_name": tool_name,
                           "args_digest": args_digest, "policy_revision": policy_revision})
        if self.error is not None:
            raise self.error
        return self.decision


class FakeCredentialPort:
    """Fake CredentialPort: id -> (plaintext, revision), with call counts."""

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.has_calls: list = []
        self.read_calls: list = []

    def has(self, credential_id):
        self.has_calls.append(credential_id)
        return credential_id in self.values

    def read(self, credential_id):
        self.read_calls.append(credential_id)
        return self.values[credential_id]

    def rotate(self, credential_id, plaintext, revision):
        self.values[credential_id] = (plaintext, revision)

    def revoke(self, credential_id):
        self.values.pop(credential_id, None)


def make_snapshot(allowed=("fetch", "write_file"), *, definition_id="def1", revision=1,
                  canonical_digest="sha256:def1-r1", lane="managed", enforcement="proven",
                  credential_slots=(("TOKEN", "cred-1"),)):
    """A snapshot shaped exactly like ``backend/resolve.py`` output: same
    field names, same entry records, so the glue binds to the real surface."""
    return McpEffectiveSnapshot(
        target_session="sess-1",
        runtime_generation=3,
        project_id="proj-1",
        profile_revision="profile-rev-1",
        definition_revisions=({
            "definition_id": definition_id, "revision": revision,
            "canonical_digest": canonical_digest, "canonical_shape": "v2",
        },),
        assignment_revisions=(),
        credential_ref_revisions=tuple({
            "definition_id": definition_id, "revision": revision,
            "slot": slot, "credential_id": cred,
        } for slot, cred in credential_slots),
        allowed_tool_names=tuple(allowed),
        lane_by_definition={definition_id: {"lane": lane, "enforcement": enforcement}},
        needs_revalidation=(),
        snapshot_digest="sha256:snapshot",
    )
