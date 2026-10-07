"""Import-only compatibility for the retired distribution names.

No implementation or state is copied. The loader replaces its temporary module
with the canonical one, preserving that module's spec and resource location.
Only the four historical namespaces are intercepted; normal imports are untouched.
"""
import importlib
import importlib.abc
import importlib.util
import sys

ALIASES = {
    "pacthold.harness_kit": "pacthold.harness_kit",
    "ordessa_harness_dsh": "ordessa_harness_dsh",
    "ordessa_harness_qwen": "ordessa_harness_qwen",
    "ordessa_harness_kilo": "ordessa_harness_kilo",
}


class _AliasLoader(importlib.abc.Loader):
    def __init__(self, target):
        self.target = target

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        sys.modules[module.__name__] = importlib.import_module(self.target)


class _AliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        prefix, separator, suffix = fullname.partition(".")
        if prefix not in ALIASES or not separator:
            return None
        canonical = ALIASES[prefix] + "." + suffix
        spec = importlib.util.find_spec(canonical)
        if spec is None:
            return None
        return importlib.util.spec_from_loader(
            fullname, _AliasLoader(canonical),
            is_package=spec.submodule_search_locations is not None,
        )


def install(name):
    if not any(isinstance(finder, _AliasFinder) for finder in sys.meta_path):
        sys.meta_path.insert(0, _AliasFinder())
    sys.modules[name] = importlib.import_module(ALIASES[name])
