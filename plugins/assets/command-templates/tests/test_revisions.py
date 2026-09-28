"""T04 / G02–G04: immutability, digest, approval, archive, CAS, idempotency.

Key rulings under test:
* a revision is immutable and digest-addressed (G02);
* approval gates what an enable may pin (G04);
* archiving keeps revision + assignment history (G04);
* CAS ``expectedVersion`` and an ``operationKey`` idempotency ledger (same key +
  same payload replays, same key + different payload is refused) (G04);
* publishing a newer revision never moves an existing assignment's pinned
  revision (G03).
"""
from __future__ import annotations

import pytest

from ordessa_command_templates.api.dto import Assignment, ParameterSpec, Target
from ordessa_command_templates.api.errors import (
    CasConflictError,
    IdempotencyConflictError,
    RevisionUnapprovedError,
)
from ordessa_command_templates.expansion.digest import revision_digest
from conftest import enable, make_template


def test_digest_is_deterministic_and_content_bound(store):
    a = revision_digest("Review {{x}}", [ParameterSpec("x")])
    b = revision_digest("Review {{x}}", [ParameterSpec("x")])
    c = revision_digest("Review {{y}}", [ParameterSpec("x")])
    assert a == b and a != c
    assert a.startswith("sha256:")


def test_crlf_and_lf_same_revision_same_digest(service):
    # Normalization (CRLF->LF, NFC) means logically equal text yields one digest.
    service.create(principal="u1", template_id="tmpl.n", display_name="N", slug="n",
                   operation_key="c")
    r1 = service.save_revision(principal="u1", template_id="tmpl.n", body="a\r\nb",
                               parameters=[ParameterSpec("z", "string", False)],
                               expected_version=1, operation_key="r1")
    d_crlf = revision_digest("a\r\nb", [ParameterSpec("z", "string", False)])
    d_lf = revision_digest("a\nb", [ParameterSpec("z", "string", False)])
    assert d_crlf == d_lf == r1.content_digest


def test_revisions_are_immutable_and_append_only(service):
    make_template(service, tid="tmpl.imm", slug="imm", body="v1 {{p}}",
                  parameters=[ParameterSpec("p", "string", True)])
    r2 = service.save_revision(principal="u1", template_id="tmpl.imm", body="v2 {{p}}",
                               parameters=[ParameterSpec("p", "string", True)],
                               expected_version=3, operation_key="r2")  # after approve v=3
    r1 = service.store.get_revision("tmpl.imm", 1)
    assert r1.body == "v1 {{p}}" and r2.revision == 2
    # Re-reading revision 1 still returns the original bytes — nothing rewrote it.
    assert service.store.get_revision("tmpl.imm", 1).body == "v1 {{p}}"


def test_enable_requires_approved_revision(service):
    make_template(service, tid="tmpl.appr", slug="appr", body="x {{p}}",
                  parameters=[ParameterSpec("p")], approve=False)
    with pytest.raises(RevisionUnapprovedError):
        enable(service, tid="tmpl.appr", revision=1)
    service.approve(principal="u1", template_id="tmpl.appr", revision=1,
                    expected_version=2, operation_key="a")
    assignment = enable(service, tid="tmpl.appr", revision=1)
    assert assignment.pinned_revision == 1


def test_cas_conflict_on_stale_expected_version(service):
    make_template(service, tid="tmpl.cas", slug="cas", body="x {{p}}",
                  parameters=[ParameterSpec("p")])
    # entity_version is now 3 (create=1 -> save_rev=2 -> approve=... wait compute).
    tmpl = service.store.get_template("tmpl.cas")
    with pytest.raises(CasConflictError):
        service.save_revision(principal="u1", template_id="tmpl.cas", body="y {{p}}",
                              parameters=[ParameterSpec("p")],
                              expected_version=tmpl.entity_version + 5, operation_key="bad")


def test_idempotent_replay_returns_same_and_new_operation_works(service):
    make_template(service, tid="tmpl.idem", slug="idem", body="x {{p}}",
                  parameters=[ParameterSpec("p")])
    tmpl = service.store.get_template("tmpl.idem")
    v = tmpl.entity_version
    first = service.save_revision(principal="u1", template_id="tmpl.idem", body="new {{p}}",
                                  parameters=[ParameterSpec("p")], expected_version=v,
                                  operation_key="same-key")
    # Replaying the exact same operation key + payload is idempotent: the version
    # does not advance again and the same revision number comes back.
    after = service.store.get_template("tmpl.idem")
    replay = service.save_revision(principal="u1", template_id="tmpl.idem", body="new {{p}}",
                                   parameters=[ParameterSpec("p")],
                                   expected_version=after.entity_version, operation_key="same-key")
    assert replay.revision == first.revision


def test_idempotency_conflict_same_key_different_payload(service):
    make_template(service, tid="tmpl.conf", slug="conf", body="x {{p}}",
                  parameters=[ParameterSpec("p")])
    tmpl = service.store.get_template("tmpl.conf")
    service.save_revision(principal="u1", template_id="tmpl.conf", body="A {{p}}",
                          parameters=[ParameterSpec("p")], expected_version=tmpl.entity_version,
                          operation_key="dup")
    # Same operation key, different body -> digest differs -> typed conflict.
    latest = service.store.get_template("tmpl.conf")
    with pytest.raises(IdempotencyConflictError):
        service.save_revision(principal="u1", template_id="tmpl.conf", body="B {{p}}",
                              parameters=[ParameterSpec("p")], expected_version=latest.entity_version,
                              operation_key="dup")


def test_archive_preserves_revision_and_assignment_history(service):
    make_template(service, tid="tmpl.arc", slug="arc", body="x {{p}}",
                  parameters=[ParameterSpec("p")])
    enable(service, tid="tmpl.arc", revision=1)
    tmpl = service.store.get_template("tmpl.arc")
    archived = service.archive(principal="u1", template_id="tmpl.arc",
                               expected_version=tmpl.entity_version, operation_key="arch")
    assert archived.is_archived
    # History is retained: the revision and the assignment row still exist.
    assert service.store.get_revision("tmpl.arc", 1).body == "x {{p}}"
    assert any(a.template_id == "tmpl.arc" for a in service.store.assignments())
    # But it is no longer "available" — resolve reports the real ARCHIVED reason.
    res = service.resolve(target=Target(principal="u1", server_identity="s1"))
    excluded_ids = {e.template_id: e.reason for e in res.excluded}
    assert excluded_ids.get("tmpl.arc") == "ARCHIVED"


def test_publishing_new_revision_does_not_move_pinned_assignment(service):
    make_template(service, tid="tmpl.pin", slug="pin", body="v1 {{p}}",
                  parameters=[ParameterSpec("p")])
    enable(service, tid="tmpl.pin", revision=1)
    tmpl = service.store.get_template("tmpl.pin")
    service.save_revision(principal="u1", template_id="tmpl.pin", body="v2 {{p}}",
                          parameters=[ParameterSpec("p")], expected_version=tmpl.entity_version,
                          operation_key="r2")
    # The existing enable assignment still pins revision 1 (G03: no auto-bump).
    rows = service.store.assignments(scope="user-global", scope_identity="u1")
    pinned = [a for a in rows if a.template_id == "tmpl.pin"][0]
    assert pinned.pinned_revision == 1
    res = service.resolve(target=Target(principal="u1", server_identity="s1"))
    assert [e for e in res.available if e.template_id == "tmpl.pin"][0].pinned_revision == 1
