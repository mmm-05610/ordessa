"""A module-attribute capability factory used by the discovery tests."""
from host_fakes import make_capability


class ModuleFactory:
    def build(self, bindings):
        return make_capability('modcap', operation_ids=('modcap.run',))


factory = ModuleFactory()
