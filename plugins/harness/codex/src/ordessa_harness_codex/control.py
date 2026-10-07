from __future__ import annotations
from typing import Any
from pacthold_runtime_compat.resource_contracts import AgentBoxProfileV1, WorkspaceV1

class CodexAppServerHostControl:
    provider_id="codex-app-server"
    def __init__(self, provider): self.provider=provider; self.registry=None
    def bind_registry(self,registry): self.registry=registry
    def attach_command(self,facts): return None
    def _handle(self,facts):
        return self.provider.get_handle(facts.dispatch["id"])
    def observe(self,facts,handle=None): return self.provider.observe(handle or self._handle(facts))
    def finish(self,facts,handle=None): return self.provider.finish(handle or self._handle(facts))
