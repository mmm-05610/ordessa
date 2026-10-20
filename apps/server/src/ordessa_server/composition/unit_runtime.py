"""Root lifetime of a selected Unit admission scope, without a Core registry."""
from pathlib import Path
from ordessa_units.admission.context import UnitAdmissionContext
from ordessa_units.errors import UnitGuaranteeUnavailable

class UnitRuntimeOwner:
    def __init__(self, store_path, *, environment_factory=None, ownership_probe=None,
                 root_ownership_port=None):
        self.store_path = str(Path(store_path))
        self.root_ownership_port = root_ownership_port
        self._factory = environment_factory
        self._ownership_probe = ownership_probe
        self._context = None
        self._closed = False
        self.ever_opened = False
        self.shutdown_report = None

    @property
    def owns_data_root(self):
        return self._ownership_probe is not None and self._ownership_probe() is True

    @property
    def context(self):
        if self._closed:
            raise UnitGuaranteeUnavailable('Unit runtime round is closed')
        return self.open()

    def open(self):
        if self._context is not None and not self._closed:
            return self._context
        if self._factory is None:
            raise UnitGuaranteeUnavailable('selected product has no Unit admission factory')
        context = self._factory(Path(self.store_path))
        if not isinstance(context, UnitAdmissionContext):
            raise TypeError('product factory must return the original UnitAdmissionContext')
        self._context = context
        self._closed = False
        self.ever_opened = True
        self.shutdown_report = None
        return context

    def close(self):
        if self._context is None or self._closed:
            return self.shutdown_report
        report = self._context.close()
        self._closed = True
        self.shutdown_report = report
        return report
