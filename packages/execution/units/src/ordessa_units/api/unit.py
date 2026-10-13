"""A caller handle is a live view, never a Grant or a persisted outcome."""


class Unit:
    def __init__(self, assembly, instance):
        self._assembly, self._instance = assembly, instance

    @property
    def identity(self):
        return self._instance.prepared_unit['unitRef']

    def snapshot(self):
        return self._assembly.snapshot(self)

    def interaction(self, authorization):
        return self._assembly.interaction(self, authorization)

    def close(self, authorization):
        return self._assembly.close_unit(self, authorization)
