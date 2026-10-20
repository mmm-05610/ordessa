"""Stateless application admission for decision operations and original evidence.

The injected existing authority owns authentication/policy. This adapter creates
no evidence ACL, grants, subject entity or shadow result journal. Digest knowledge
never suffices: original store scope and individual evidence access are checked.
"""
from collections.abc import Mapping
import re
from typing import Protocol

from ordessa_interfaces_contracts import Capability, CapabilityError, OperationResult, validate_capability


class DecisionAccessPort(Protocol):
    def authorize_operation(self, invocation, operation_id, request) -> bool: ...
    def authorize_evidence_store(self, invocation, original_store, purpose) -> bool:
        """Verify original store's existing principal/project ownership scope.

        A shared unowned content-addressed directory is NOT a subject namespace.
        Write authorization is allowed only if newly created original artifacts
        inherit this verified existing scope, without an application side journal.
        """
        ...
    def authorize_evidence(self, invocation, original_store, digest) -> bool:
        """Verify original artifact's permitted owner/scope, not hash or action alone."""
        ...


def _refused(code, message):
    return OperationResult('refused', error=CapabilityError(code, message))


def protect_decisions(capability, bindings):
    """Wrap published handlers, preserving original owner ABI/descriptors.

    Missing original evidence ownership policy is unavailable, not public access.
    Used only by product composition; neutral interface host stays domain-free.
    """
    if capability.descriptor.id != 'decisions':
        raise ValueError('decision capability required')
    resolver = bindings.get('invocation_resolver')
    authority = bindings.get('decision_access')
    services = bindings.get('services')
    settings = services.get('decisions') if isinstance(services, Mapping) else None
    store = getattr(settings, 'evidence', None)
    ready = (callable(resolver) and store is not None and all(
        callable(getattr(authority, name, None)) for name in
        ('authorize_operation','authorize_evidence_store','authorize_evidence')))
    handlers = {}
    for operation_id, original in capability.handlers.items():
        async def guarded(request, context, *, _operation=operation_id, _handler=original):
            if not ready:
                return _refused('AUTHORITY_UNAVAILABLE', 'Original decision evidence scope authority unavailable')
            try:
                invocation = resolver(context)
                if invocation is None or authority.authorize_operation(invocation, _operation, request) is not True:
                    return _refused('PERMISSION_DENIED', 'Decision invocation refused')
                if _operation in ('decisions.get','decisions.evidence'):
                    digest = request.get('digest')
                    if type(digest) is not str or not re.fullmatch(r'[0-9a-f]{64}', digest):
                        return _refused('INVALID_INPUT', 'Exact evidence digest required')
                    if (authority.authorize_evidence_store(invocation, store, 'read') is not True
                            or authority.authorize_evidence(invocation, store, digest) is not True):
                        return _refused('PERMISSION_DENIED', 'Decision evidence read refused')
                elif _operation == 'decisions.run':
                    if authority.authorize_evidence_store(invocation, store, 'write') is not True:
                        return _refused('PERMISSION_DENIED', 'Decision evidence write scope refused')
                elif _operation != 'decisions.validate':
                    return _refused('CAPABILITY_UNSUPPORTED', 'Decision operation has no admitted policy')
            except Exception:
                # All checks above precede the owner handler/effects. Never print
                # raw identity, secret or authority callback exceptions.
                return _refused('PERMISSION_DENIED', 'Decision authority refused invocation')
            # Owner executes exactly once; exceptions/results retain host unknown
            # semantics. The app never retries, copies evidence or spends budget.
            return await _handler(request, context)
        handlers[operation_id] = guarded
    protected = Capability(capability.descriptor, handlers)
    validate_capability(protected)
    return protected
