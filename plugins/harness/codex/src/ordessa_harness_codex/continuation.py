"""Exact native-session continuation authority for new Executions."""
from __future__ import annotations
from pacthold.work_core import Ref, RefType
from pacthold.work_core.registry import ProviderDescriptor
from .contracts import CodexContinuationV1

class CodexContinuationResourceProvider:
    provider_id = "codex-continuation"
    supported_contract_ids = frozenset({CodexContinuationV1.contract_id})
    def descriptor(self): return ProviderDescriptor(self.provider_id, "Codex native continuation", "1")
    def make_ref(self, native_id: str, source_provider: str) -> Ref:
        if source_provider not in {"codex-app-server", "codex-interactive"} or not native_id.strip():
            raise ValueError("CONTINUATION_SOURCE_UNSUPPORTED")
        return Ref(RefType.SESSION, self.provider_id, native_id, metadata={"source_provider": source_provider})
    def resolve(self, contract_id, ref, *, context=None):
        del context
        if contract_id != CodexContinuationV1.contract_id or ref.type is not RefType.SESSION or ref.provider != self.provider_id:
            raise ValueError("CONTINUATION_REF_MISMATCH")
        if ref.metadata.get("source_provider") not in {"codex-app-server", "codex-interactive"}:
            raise ValueError("CONTINUATION_SOURCE_UNSUPPORTED")
        return CodexContinuationV1(ref.native_id)
