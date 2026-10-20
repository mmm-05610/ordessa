"""Model declarations projected from explicitly selected public C2 providers.

A descriptor and a protocol declaration are facts, not installation evidence.
There is no native runtime, brand table, discovery or credential storage here.
"""
from dataclasses import dataclass
from types import MappingProxyType
from collections.abc import Mapping
from .protocols import normalize_protocols


@dataclass(frozen=True)
class ModelHarnessDeclaration:
    id: str
    credential_kind: str | None
    wire_protocols: Mapping
    model_control_id: str | None


class ModelConfigurationCatalog:
    def __init__(self, descriptors, *, protocol_ports, model_control_ports):
        if descriptors is None or not isinstance(protocol_ports, Mapping):
            raise ValueError('Selected C2 descriptors and protocol ports required')
        selected = tuple(descriptors)
        if len(selected) > 256:
            raise ValueError('Bounded selected C2 descriptors required')
        if not selected and not isinstance(model_control_ports, Mapping):
            raise ValueError('Explicit selected model-control declarations required')
        declarations, protocols = {}, {}
        for descriptor in selected:
            harness_id = descriptor.harness_id
            if (type(harness_id) is not str or not harness_id or len(harness_id) > 128
                    or harness_id.strip() != harness_id or any(ord(c) < 32 for c in harness_id)
                    or harness_id in declarations):
                raise ValueError('Unique bounded selected model provider required')
            if descriptor.facet_id != 'assets.model-provider' or 'acp' not in descriptor.entries:
                raise ValueError('Selected model-choice C2 provider required')
            port = protocol_ports.get(harness_id)
            if not callable(port):
                raise ValueError('Selected provider protocol declaration required')
            supplied = port()
            if not isinstance(supplied, Mapping) or len(supplied) > 4:
                raise ValueError('Bounded provider protocol declarations required')
            names = normalize_protocols(list(supplied))
            protocols[harness_id] = MappingProxyType({name: 'declared' for name in names})
            if not isinstance(model_control_ports, Mapping):
                raise ValueError('Explicit selected model-control declarations required')
            control_port = model_control_ports.get(harness_id)
            if not callable(control_port):
                raise ValueError('Selected provider model-control declaration required')
            control_id = control_port()
            if control_id is not None and (
                    type(control_id) is not str or not control_id or len(control_id) > 128
                    or control_id.strip() != control_id or any(ord(c) < 32 for c in control_id)):
                raise ValueError('Bounded declared model-control id required')
            credential_kind = ('api-key' if any(claim.target_kind == 'environment'
                               for claim in descriptor.claims) else None)
            declarations[harness_id] = ModelHarnessDeclaration(
                harness_id, credential_kind, MappingProxyType({}), control_id)
        self._declarations = MappingProxyType(declarations)
        self._protocols = MappingProxyType(protocols)

    def __contains__(self, harness_id):
        return harness_id in self._declarations

    def registered(self):
        return tuple(self._declarations)

    def get(self, harness_id):
        return self._declarations[harness_id]

    def wire_protocols(self, harness_id):
        return dict(self._protocols.get(harness_id, {}))
