"""Public Manager over one original live owner; no second durable inventory."""


class UnitManager:
    def __init__(self, assembly):
        self._assembly = assembly

    def create(self, spec, authorization):
        return self._assembly.create(spec, authorization)

    def get(self, identity):
        return self._assembly.get(identity)

    def list(self):
        return self._assembly.list()

    def close(self, authorization):
        return self._assembly.close_manager(authorization)
