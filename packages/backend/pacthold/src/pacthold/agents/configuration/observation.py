"""Agent full-snapshot source; subscription authority belongs to Environment."""
from dataclasses import fields, is_dataclass
from pacthold.agents.submissions.owners import wire_value


def snapshot_wire(snapshot):
    return {'ownerRef': snapshot.owner_ref, 'revision': snapshot.revision,
        'observedEvidence': snapshot.observed_evidence,
        'fields': wire_value(snapshot.fields), 'resolved': wire_value(snapshot.resolved),
        'operations': [{'operationId': op.operation_id, 'patchKinds': list(op.patch_kinds),
            'sourceRef': op.source_ref, 'submittedAtOrder': op.submitted_at_order,
            'state': op.state} for op in snapshot.operations]}


class ConfigObservationSource:
    def __init__(self, owner):
        self.owner = owner

    def attach(self, sink, *, cursor=None):
        # No historical replay is claimed. Resumption starts a new full chain
        # and explicitly reports loss of the old cursor's continuity.
        if cursor is not None:
            sink.gap('gap')
        return self.owner.attach_observer(lambda snapshot:
            sink.snapshot(str(snapshot.revision), snapshot_wire(snapshot)))


def envelope_wire(value):
    if is_dataclass(value):
        return {field.name: envelope_wire(getattr(value, field.name)) for field in fields(value)}
    if hasattr(value, 'items'):
        return {key: envelope_wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [envelope_wire(item) for item in value]
    return value
