"""C2 regressions for zero-effect, source-owned submit conditions."""
from __future__ import annotations

from dataclasses import replace

import pytest

from ordessa_agent.submission_journal import (
    JournalConflictError,
    ReliableSubmissionUnsupported,
)
from ordessa_agent.submission_service import (
    NativeSubmitBinding,
    NativeSubmitDeclaration,
)

from test_closeout_submission_service import _input, _service


def test_capture_conditions_returns_complete_trusted_descriptor_without_effects(tmp_path):
    service, environment, journal, port, backend_store, domain_store = _service(tmp_path)
    try:
        descriptor = service.capture_conditions(
            "session:S1", "existing", principal_scope="user:local:agent-test",
        )

        assert descriptor == {
            "binding": {
                "sessionId": "session-1",
                "generation": "2",
                "ownerRef": "harness-owner:session-1",
                "surfaceId": "agent.submit",
                "environment": environment.environment_id,
                "environmentContextRevision": descriptor["binding"]["environmentContextRevision"],
                "providerActivation": descriptor["binding"]["providerActivation"],
            },
            "baseRevision": "native-r4",
            "sourceRevision": "1",
            "configOwnerRef": "agent-config:session:S1",
        }
        assert descriptor["binding"]["environmentContextRevision"]
        assert descriptor["binding"]["providerActivation"]
        assert port.effect_calls == 0
        assert port.query_calls == 0
        assert journal.read(_key(service.environment)) is None
        assert environment.query(_key(service.environment)) is None
    finally:
        backend_store.close()
        domain_store.close()


def test_same_pending_operation_ids_with_new_config_revision_refuse_before_mapping(tmp_path):
    service, _, journal, port, backend_store, domain_store = _service(tmp_path)
    try:
        expected = service.capture_conditions(
            "session:S1", "existing", principal_scope="user:local:agent-test",
        )
        config = service.owners.owners_of("session:S1")["config"]
        later = config.submit_operation({"temperature": 0.4}, "later-selection")
        config.settle_operations((later.operation_id,), state="applied")
        # The caller's captured operation id remains the sole pending ID, but
        # the trusted owner revision has advanced since the capture.
        assert tuple(operation.operation_id for operation in config.list_operations()
                     if operation.state == "pending") == ("op-session:S1-1",)

        with pytest.raises(ReliableSubmissionUnsupported, match="condition"):
            service.submit(replace(_input(), expected_conditions=expected))

        assert journal.read(_key(service.environment)) is None
        assert port.effect_calls == 0
    finally:
        backend_store.close()
        domain_store.close()


def test_changed_native_base_revision_refuses_expected_conditions_before_mapping(tmp_path):
    service, _, journal, port, backend_store, domain_store = _service(tmp_path)
    try:
        expected = service.capture_conditions(
            "session:S1", "existing", principal_scope="user:local:agent-test",
        )
        original = port.resolve_binding

        def changed_binding(target):
            binding = original(target)
            return NativeSubmitBinding(
                target=binding.target,
                owner_ref=binding.owner_ref,
                mode=binding.mode,
                surface_id=binding.surface_id,
                base_revision="native-r5",
                identity=binding.identity,
            )

        port.resolve_binding = changed_binding
        with pytest.raises(ReliableSubmissionUnsupported, match="condition"):
            service.submit(replace(_input(), expected_conditions=expected))

        assert journal.read(_key(service.environment)) is None
        assert port.effect_calls == 0
    finally:
        backend_store.close()
        domain_store.close()


def test_changed_native_owner_identity_refuses_expected_conditions_before_mapping(tmp_path):
    service, _, journal, port, backend_store, domain_store = _service(tmp_path)
    try:
        expected = service.capture_conditions(
            "session:S1", "existing", principal_scope="user:local:agent-test",
        )
        port.declaration = NativeSubmitDeclaration(
            owner_ref="harness-owner:session-1-next",
            existing_conditional=True,
            create_with_config_conditional=True,
            immutable_attachments=True,
        )
        original = port.resolve_binding

        def changed_binding(target):
            binding = original(target)
            return NativeSubmitBinding(
                target=binding.target,
                owner_ref="harness-owner:session-1-next",
                mode=binding.mode,
                surface_id=binding.surface_id,
                base_revision=binding.base_revision,
                identity=binding.identity,
            )

        port.resolve_binding = changed_binding
        with pytest.raises(ReliableSubmissionUnsupported, match="condition"):
            service.submit(replace(_input(), expected_conditions=expected))

        assert journal.read(_key(service.environment)) is None
        assert port.effect_calls == 0
    finally:
        backend_store.close()
        domain_store.close()


def test_unknown_configuration_condition_cannot_be_captured(tmp_path):
    service, _, journal, port, backend_store, domain_store = _service(tmp_path)
    try:
        config = service.owners.owners_of("session:S1")["config"]
        config.settle_operations(("op-session:S1-1",), state="unknown")

        with pytest.raises(ReliableSubmissionUnsupported, match="unknown"):
            service.capture_conditions(
                "session:S1", "existing", principal_scope="user:local:agent-test",
            )

        assert journal.read(_key(service.environment)) is None
        assert port.effect_calls == 0
    finally:
        backend_store.close()
        domain_store.close()


def test_existing_request_compares_expected_conditions_to_frozen_capture_query_only(tmp_path):
    service, _, _, port, backend_store, domain_store = _service(tmp_path)
    try:
        first = service.submit(_input())
        capture = __import__("json").loads(first.record.encoded_input)["capture"]
        frozen = {
            "binding": capture["binding"],
            "baseRevision": capture["baseRevision"],
            "sourceRevision": capture["target"]["config"]["revision"],
            "configOwnerRef": capture["target"]["config"]["ownerRef"],
        }
        changed = {**frozen, "baseRevision": "different-base"}
        calls_before = port.query_calls

        with pytest.raises(JournalConflictError, match="condition"):
            service.submit(replace(_input(), expected_conditions=changed))

        assert port.query_calls == calls_before
        assert port.effect_calls == 1
    finally:
        backend_store.close()
        domain_store.close()


def _key(environment, request_id="submission-1"):
    from ordessa_environment_api import RequestKey

    return RequestKey(
        environment_namespace=environment.environment_id,
        principal_scope="user:local:agent-test",
        request_id=request_id,
    )
