from __future__ import annotations

class CodexInteractiveHostControl:
    provider_id = "codex-interactive"
    def __init__(self, provider): self.provider = provider
    def bind_registry(self, registry): self.registry = registry
    def _handle(self, facts): return self.provider.get_handle(facts.dispatch["id"])
    def attach_command(self, facts):
        descriptor = self._handle(facts).composition_handle.attach_descriptor
        return tuple(descriptor.locator.split()) if descriptor else ()
    def observe(self, facts, handle=None): return self.provider.observe(handle or self._handle(facts))
    def finish(self, facts, handle=None): return self.provider.finish(handle or self._handle(facts))
