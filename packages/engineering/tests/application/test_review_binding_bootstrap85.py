"""Explicit review-selection bootstrap through the original Engineering owners."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from ordessa_engineering.adapters.persistence.sqlite.review_bindings import SQLiteReviewBindings
from ordessa_engineering.application.contracts.errors import ApplicationError

from submission_wait_business_fixture import build_submission_wait_fixture


def test_unbound_selection_refuses_runtime_until_original_owner_validation(tmp_path):
    e = build_submission_wait_fixture(tmp_path)
    try:
        selection = e["bindings"]
        bindings = SQLiteReviewBindings(e["factory"], e["controls"],
            scope=e["scope"], proposal_ref=None, phases=None)

        with pytest.raises(ApplicationError) as unavailable:
            bindings.resolve_bindings(e["context"], e["method_ref"], "quality_review")
        assert unavailable.value.code == "METHOD_TARGET_BINDINGS_UNAVAILABLE"

        invalid_phases = (replace(selection.phases[0], workflow_node_id="not-the-node"),
                          *selection.phases[1:])
        with pytest.raises(ApplicationError) as invalid:
            bindings.bind_selection(e["context"], proposal_ref=e["proposal"].ref,
                                    phases=invalid_phases)
        assert invalid.value.code == "METHOD_PHASE_BINDING_MISMATCH"

        # A rejected selection is not partially installed and can be retried.
        with pytest.raises(ApplicationError) as still_unbound:
            bindings.resolve_bindings(e["context"], e["method_ref"], "quality_review")
        assert still_unbound.value.code == "METHOD_TARGET_BINDINGS_UNAVAILABLE"

        bindings.bind_selection(e["context"], proposal_ref=e["proposal"].ref,
                                phases=selection.phases)
        actual = bindings.resolve_bindings(e["context"], e["method_ref"], "quality_review")
        assert actual.phase_key == "quality_review"
        assert actual.input_slots == ("proposal_ref",)
        assert actual.targets.targets[0].ref == e["proposal"].mutations[0].proposed_ref
        with pytest.raises(ApplicationError) as rebound:
            bindings.bind_selection(e["context"], proposal_ref=e["proposal"].ref,
                                    phases=selection.phases)
        assert rebound.value.code == "METHOD_SUBJECT_BINDING_MISMATCH"
    finally:
        e["library"].close()


def test_constructor_rejects_partial_or_placeholder_selection(tmp_path):
    e = build_submission_wait_fixture(tmp_path)
    try:
        for proposal_ref, phases in ((None, e["bindings"].phases),
                                     (e["proposal"].ref, None),
                                     (e["proposal"].ref, ())):
            with pytest.raises(ApplicationError) as invalid:
                SQLiteReviewBindings(e["factory"], e["controls"], scope=e["scope"],
                    proposal_ref=proposal_ref, phases=phases)
            assert invalid.value.code == "METHOD_SUBJECT_BINDING_MISMATCH"
    finally:
        e["library"].close()


def test_competing_binds_validate_outside_selection_lock_and_publish_once(tmp_path, monkeypatch):
    e = build_submission_wait_fixture(tmp_path)
    try:
        source = e["bindings"]
        bindings = SQLiteReviewBindings(e["factory"], e["controls"],
            scope=e["scope"], proposal_ref=None, phases=None)
        barrier = Barrier(2)
        original_resolve = bindings._resolve_selection

        def synchronized_resolve(*args):
            barrier.wait(timeout=10)
            return original_resolve(*args)

        monkeypatch.setattr(bindings, "_resolve_selection", synchronized_resolve)

        def attempt_bind():
            try:
                bindings.bind_selection(e["context"], proposal_ref=e["proposal"].ref,
                                        phases=source.phases)
                return "bound"
            except ApplicationError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = tuple(pool.map(lambda _: attempt_bind(), range(2)))
        assert sorted(results) == ["METHOD_SUBJECT_BINDING_MISMATCH", "bound"]
        assert bindings.proposal_ref == e["proposal"].ref
        assert bindings.phases == source.phases
    finally:
        e["library"].close()
