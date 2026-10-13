"""Hermes historical reference value; ProfileService owns all persistence."""
from ordessa_execution_agents.harness.definitions import NativeProfileRef

PROVIDER_ID = "harness-profile"  # preserved historical reference identity

class ProfileRef:
    def __init__(self, pid, revision, digest):
        self.harness_id = "hermes"
        self.profile_id = pid
        self.revision = revision
        self.digest = digest
        self.provider = PROVIDER_ID

    def as_ref(self):
        return NativeProfileRef(PROVIDER_ID, self.profile_id,
                   metadata={"harness_type": "hermes", "revision": str(self.revision),
                             "digest": self.digest})
