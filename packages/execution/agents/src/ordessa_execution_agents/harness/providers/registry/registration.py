"""Single-use staging handle for an exact HarnessCatalog registration batch."""

from ordessa_execution_api.environment import AdmissionRefusedError


class HarnessRegistration:
    """A batch can commit once, roll back before commit, and never auto-retry."""

    def __init__(self, catalog, token, entries):
        self._catalog, self._token, self._entries = catalog, token, entries
        self._state = "staged"

    @property
    def owner_key(self):
        entry = self._entries[0]
        return (entry.owner_id, entry.generation)

    @property
    def state(self):
        return self._state

    def commit(self):
        if self._state != "staged":
            raise AdmissionRefusedError("Harness registration is not retryable")
        # Fence before delegating: an exception can follow partial admission,
        # so callers cannot safely replay commit against the same batch.
        self._state = "committing"
        try:
            admitted = self._catalog._commit(self._token, self._entries)
        except BaseException:
            self._state = "unknown"
            raise
        self._state = "committed"
        return admitted

    def rollback(self):
        if self._state != "staged":
            raise AdmissionRefusedError("Harness registration can no longer roll back")
        self._catalog._rollback(self._token, self._entries)
        self._state = "rolled_back"
