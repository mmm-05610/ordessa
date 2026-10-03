"""T06 / G03 / G08 / G12: deterministic scoped resolution & conflict handling.

Covers: the fixed layer order with explicit enable/disable overriding earlier
layers while undeclared layers inherit; resolveEffective reporting availability +
source + pinned revision + a real absence reason (never a fake-empty list);
two distinct ids sharing a slug are detected, not silently dropped by layer;
namespaced ``template:<name>`` ids do not claim a bare route; a forced
organisation policy wins over every user preference.
"""
from __future__ import annotations

import pytest

from ordessa_command_templates.api.dto import Assignment, ParameterSpec, Target
from ordessa_command_templates.api.errors import UnauthorizedTargetError
from conftest import enable, make_template


def _a(scope, identity, tid, state, rev=None, harness=None):
    return Assignment(scope=scope, scope_identity=identity, template_id=tid,
                      state=state, pinned_revision=rev, harness_id=harness)


def test_layer_order_explicit_disable_wins_over_lower_enable(service):
    make_template(service, tid="tmpl.t", slug="t", body="x {{p}}",
                  parameters=[ParameterSpec("p")])
    enable(service, tid="tmpl.t", revision=1)  # user-global enable
    # project layer disables for the same id -> final state disabled
    service.store.upsert_assignment(_a("project", "projA", "tmpl.t", "disable"),
                                    expected_version=None, operation_key="proj-dis")
    res = service.resolve(target=Target(principal="u1", server_identity="s1", project_id="projA"))
    entry = [e for e in res.available + res.excluded if e.template_id == "tmpl.t"][0]
    assert entry.state == "disabled" and entry.source == "project"


def test_undeclared_higher_layer_inherits(service):
    make_template(service, tid="tmpl.i", slug="i", body="x {{p}}", parameters=[ParameterSpec("p")])
    enable(service, tid="tmpl.i", revision=1)
    # A project assignment for a *different* project must not affect projA.
    service.store.upsert_assignment(_a("project", "projB", "tmpl.i", "disable"),
                                    expected_version=None, operation_key="pb")
    res = service.resolve(target=Target(principal="u1", server_identity="s1", project_id="projA"))
    entry = [e for e in res.available + res.excluded if e.template_id == "tmpl.i"][0]
    assert entry.state == "available" and entry.source == "user-global"


def test_harness_scoped_layer_applies_only_to_matching_harness(service):
    make_template(service, tid="tmpl.h", slug="h", body="x {{p}}", parameters=[ParameterSpec("p")])
    enable(service, tid="tmpl.h", revision=1)
    service.store.upsert_assignment(
        _a("user-harness", "u1", "tmpl.h", "disable", harness="claude"),
        expected_version=None, operation_key="uh")
    on_claude = service.resolve(target=Target(principal="u1", server_identity="s1", harness_id="claude"))
    off_pi = service.resolve(target=Target(principal="u1", server_identity="s1", harness_id="pi"))
    e_claude = [e for e in on_claude.available + on_claude.excluded if e.template_id == "tmpl.h"][0]
    e_pi = [e for e in off_pi.available + off_pi.excluded if e.template_id == "tmpl.h"][0]
    assert e_claude.state == "disabled" and e_claude.source == "user-harness"
    assert e_pi.state == "available" and e_pi.source == "user-global"


def test_real_absence_reason_not_filtered_to_empty(service):
    # make_template approves revision 1; publish a second, *unapproved* revision.
    make_template(service, tid="tmpl.unapp", slug="unapp", body="x {{p}}",
                  parameters=[ParameterSpec("p")])
    tmpl = service.store.get_template("tmpl.unapp")
    service.save_revision(principal="u1", template_id="tmpl.unapp", body="y {{p}}",
                          parameters=[ParameterSpec("p")], expected_version=tmpl.entity_version,
                          operation_key="r2")
    # A stale/corrupt pin to the *unapproved* revision 2 is written straight to the
    # store (the service gate would refuse it) purely to prove resolve explains the
    # condition with a real reason instead of hiding the item as a clean empty list.
    conn = service.store.connect()
    try:
        conn.execute(
            "INSERT INTO ct_assignment(scope,scope_identity,harness_id,template_id,state,"
            "pinned_revision,entity_version,updated_at) VALUES (?,?,?,?,?,?,?,?)",
            ("user-global", "u1", "", "tmpl.unapp", "enable", 2, 1, "2026-01-01"))
        conn.commit()
    finally:
        conn.close()
    res = service.resolve(target=Target(principal="u1", server_identity="s1"))
    entry = [e for e in res.excluded if e.template_id == "tmpl.unapp"][0]
    assert entry.reason == "REVISION_UNAPPROVED"


def test_same_slug_different_ids_detected_not_dropped(service):
    make_template(service, tid="tmpl.one", slug="review", body="one {{p}}",
                  parameters=[ParameterSpec("p")])
    make_template(service, tid="tmpl.two", slug="review", body="two {{p}}",
                  parameters=[ParameterSpec("p")])
    enable(service, tid="tmpl.one", revision=1)
    enable(service, tid="tmpl.two", revision=1)
    res = service.resolve(target=Target(principal="u1", server_identity="s1"))
    assert "review" in res.conflicts
    # Both survive resolution — neither is silently deleted by layer order.
    assert {e.template_id for e in res.available} == {"tmpl.one", "tmpl.two"}


def test_namespaced_route_does_not_claim_bare_command(service):
    # The domain id and its display slug coexist with a native bare /review.
    make_template(service, tid="tmpl.review", slug="review", body="x {{p}}",
                  parameters=[ParameterSpec("p")])
    from ordessa_command_templates.api import schema
    assert schema.validate_namespaced_route("template:review") == "template:review"
    # A bare '/review' is NOT a route this domain may register.
    with pytest.raises(Exception):
        schema.validate_namespaced_route("/review")


def test_forced_org_policy_overrides_disable(service):
    make_template(service, tid="tmpl.pol", slug="pol", body="x {{p}}", parameters=[ParameterSpec("p")])
    service.store.upsert_assignment(_a("user-global", "u1", "tmpl.pol", "disable"),
                                    expected_version=None, operation_key="dis")
    res = service.resolve(target=Target(principal="u1", server_identity="s1"),
                          org_policy={"tmpl.pol": ("enable", 1)})
    entry = [e for e in res.available + res.excluded if e.template_id == "tmpl.pol"][0]
    assert entry.state == "available" and entry.source == "org-policy"


def test_forced_org_policy_disable_overrides_user_enable(service):
    make_template(service, tid="tmpl.pol2", slug="pol2", body="x {{p}}", parameters=[ParameterSpec("p")])
    enable(service, tid="tmpl.pol2", revision=1)
    res = service.resolve(target=Target(principal="u1", server_identity="s1"),
                          org_policy={"tmpl.pol2": ("disable", None)})
    entry = [e for e in res.available + res.excluded if e.template_id == "tmpl.pol2"][0]
    assert entry.state == "blocked-policy" and entry.reason == "FORCED_DISABLED_BY_POLICY"


def test_project_assignment_requires_authorized_port(bare_service):
    make_template(bare_service, tid="tmpl.pa", slug="pa", body="x {{p}}", parameters=[ParameterSpec("p")])
    assignment = _a("project", "projA", "tmpl.pa", "enable", rev=1)
    with pytest.raises(UnauthorizedTargetError):
        bare_service.set_assignment(principal="u1", assignment=assignment,
                                    expected_version=None, operation_key="pa")


def test_profile_scope_not_written_through_service(service):
    make_template(service, tid="tmpl.pf", slug="pf", body="x {{p}}", parameters=[ParameterSpec("p")])
    assignment = _a("profile", "profA", "tmpl.pf", "enable", rev=1)
    with pytest.raises(UnauthorizedTargetError):
        service.set_assignment(principal="u1", assignment=assignment,
                               expected_version=None, operation_key="pf")
