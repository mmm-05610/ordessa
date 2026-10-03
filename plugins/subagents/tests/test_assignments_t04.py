"""T04 / FR02 + US5: tri-state decisions, pinned revisions, honest disable."""
from __future__ import annotations

import pytest

from ordessa_assets_subagents import dto, errors
from ordessa_assets_subagents.assignments import (
    Assignment,
    AssignmentDecision,
    approve_assignment_update,
    disable_effect,
    pinned_revision,
    validate_assignment,
)
from ordessa_assets_subagents.scopes import Principal, ScopeKind, ServerScope

U1 = Principal("u1")
SCOPE = ServerScope("s1")


class Approvals:
    def __init__(self, approved: set[tuple[str, int]] | None = None) -> None:
        self._approved = approved or set()
        self.calls = 0

    def has_approved_revision(self, definition_id: str, revision: int) -> bool:
        self.calls += 1
        return (definition_id, revision) in self._approved


def assignment(**overrides) -> Assignment:
    base = dict(
        server_scope=SCOPE,
        principal=U1,
        scope_kind=ScopeKind.USER_GLOBAL,
        scope_id=None,
        harness_id="any",
        definition_id="d1",
        decision=AssignmentDecision.ENABLE,
        revision=1,
        row_version=1,
    )
    base.update(overrides)
    return Assignment(**base)


def definition(latest: int = 9) -> dto.AgentDefinition:
    return dto.AgentDefinition(
        server_scope="s1", definition_id="d1", slug="reviewer",
        display_name="Reviewer", description="reads code",
        origin_scope="public", origin_owner="u1", latest_revision=latest,
    )


class TestEnableNeedsApprovedPin:
    def test_enable_without_revision_is_refused(self) -> None:
        bad = assignment(revision=None)
        with pytest.raises(errors.DomainError) as exc:
            validate_assignment(bad, Approvals())
        assert exc.value.code == errors.DEFINITION_INVALID

    def test_enable_with_unapproved_revision_is_refused(self) -> None:
        with pytest.raises(errors.DomainError) as exc:
            validate_assignment(assignment(), Approvals(set()))
        assert exc.value.code == errors.ASSIGNMENT_CONFLICT

    def test_enable_with_approved_pin_passes(self) -> None:
        ok = assignment()
        assert validate_assignment(ok, Approvals({("d1", 1)})) is ok

    def test_inherit_touches_no_approval(self) -> None:
        approvals = Approvals()
        plain = assignment(decision=AssignmentDecision.INHERIT, revision=None)
        assert validate_assignment(plain, approvals) is plain
        assert approvals.calls == 0


class TestDisableIsHonest:
    def test_disable_removes_a_managed_item(self) -> None:
        out = disable_effect(
            assignment(decision=AssignmentDecision.DISABLE, revision=None),
            managed_definition_ids=frozenset({"d1"}),
        )
        assert out.disabled and out.diagnostic is None

    def test_disable_of_native_item_yields_typed_diagnostic_not_disabled(self) -> None:
        out = disable_effect(
            assignment(decision=AssignmentDecision.DISABLE, revision=None),
            managed_definition_ids=frozenset(),
        )
        assert not out.disabled
        assert out.diagnostic is not None
        assert out.diagnostic.code == errors.NATIVE_DISCOVERY_UNCONTROLLED

    def test_disable_effect_rejects_non_disable_decisions(self) -> None:
        with pytest.raises(errors.DomainError):
            disable_effect(assignment(), managed_definition_ids=frozenset({"d1"}))


class TestPinsDoNotMove:
    def test_publishing_newer_revision_leaves_the_pin_at_n(self) -> None:
        pinned = assignment(revision=3)
        assert pinned_revision(pinned, definition(latest=9)) == 3

    def test_pin_never_resolves_to_latest(self) -> None:
        pinned = assignment(revision=3)
        assert pinned_revision(pinned, definition(latest=4)) != 4

    def test_missing_pin_fails_closed(self) -> None:
        with pytest.raises(errors.DomainError) as exc:
            pinned_revision(assignment(revision=None), definition())
        assert exc.value.code == errors.DEFINITION_INVALID

    def test_disable_is_not_a_pin(self) -> None:
        with pytest.raises(errors.DomainError):
            pinned_revision(
                assignment(decision=AssignmentDecision.DISABLE), definition()
            )


class TestAssignmentUpgradeCas:
    def test_create_with_empty_expectation_bumps_to_row_one(self) -> None:
        created = approve_assignment_update(
            None, assignment(row_version=0), expected_row_version=None,
            approvals=Approvals({("d1", 1)}),
        )
        assert created.row_version == 1

    def test_create_over_existing_row_is_stale(self) -> None:
        with pytest.raises(errors.DomainError) as exc:
            approve_assignment_update(
                assignment(row_version=2), assignment(revision=2, row_version=0),
                expected_row_version=None, approvals=Approvals({("d1", 2)}),
            )
        assert exc.value.code == errors.REVISION_STALE

    def test_wrong_expected_version_is_stale_and_writes_nothing(self) -> None:
        existing = assignment(row_version=3)
        with pytest.raises(errors.DomainError) as exc:
            approve_assignment_update(
                existing, assignment(revision=2), expected_row_version=2,
                approvals=Approvals({("d1", 2)}),
            )
        assert exc.value.code == errors.REVISION_STALE
        assert existing.row_version == 3

    def test_matching_expectation_advances_and_requires_approval(self) -> None:
        upgraded = approve_assignment_update(
            assignment(row_version=3), assignment(revision=2),
            expected_row_version=3, approvals=Approvals({("d1", 2)}),
        )
        assert upgraded.row_version == 4
        assert upgraded.revision == 2

    def test_upgrade_to_unapproved_revision_is_refused(self) -> None:
        with pytest.raises(errors.DomainError) as exc:
            approve_assignment_update(
                assignment(row_version=3), assignment(revision=2),
                expected_row_version=3, approvals=Approvals(),
            )
        assert exc.value.code == errors.ASSIGNMENT_CONFLICT
