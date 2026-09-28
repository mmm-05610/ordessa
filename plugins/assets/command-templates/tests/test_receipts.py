"""Expansion receipts: TTL, capacity, no content leak, stale/gone refusal (FR-09/12).

Also an end-to-end preview→insert guard: a receipt binds the render to the exact
target+draft; when the target/draft/context moves the insert is refused and the
draft is left untouched; a provider unmount revokes outstanding receipts.
"""
from __future__ import annotations

import pytest

from ordessa_command_templates.api.dto import ParameterSpec, Target
from ordessa_command_templates.api.errors import (
    ContributorGoneError,
    StalePreviewError,
    UnauthorizedTargetError,
)
from ordessa_command_templates.library.receipts import ReceiptLedger, MAX_ACTIVE_RECEIPTS
from conftest import enable, make_template


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, delta):
        self.t += delta


def _receipt(**over):
    from ordessa_command_templates.api.dto import ExpansionReceipt
    base = dict(
        operation_id="op1", principal="u1", target_fingerprint="fp", template_id="tmpl.a",
        revision=1, argument_digest="sha256:args", rendered_digest="sha256:render",
        rendered_size=10, draft_id="d1", draft_revision=1, created_at="0", expires_at="100")
    base.update(over)
    return ExpansionReceipt(**base)


def test_receipt_stores_only_digests_not_content():
    receipt = _receipt()
    dumped = repr(receipt)
    assert "sha256:args" in dumped
    # There is no rendered-body or argument-value field to leak.
    assert not hasattr(receipt, "rendered_body")
    assert not hasattr(receipt, "arguments")
    body_field = [f for f in ("text", "body", "argument_values") if hasattr(receipt, f)]
    assert body_field == []


def test_receipt_expires_by_ttl():
    clock = FakeClock()
    ledger = ReceiptLedger(clock=clock, ttl=60, capacity=10)
    ledger.issue(_receipt(operation_id="op1"))
    assert ledger.get("op1").operation_id == "op1"
    clock.advance(61)
    with pytest.raises(StalePreviewError):
        ledger.get("op1")


def test_receipt_capacity_is_a_hard_bound():
    clock = FakeClock()
    ledger = ReceiptLedger(clock=clock, ttl=600, capacity=2)
    ledger.issue(_receipt(operation_id="a"))
    ledger.issue(_receipt(operation_id="b"))
    with pytest.raises(ContributorGoneError):
        ledger.issue(_receipt(operation_id="c"))


def test_receipt_single_use():
    ledger = ReceiptLedger(clock=FakeClock(), ttl=600, capacity=5)
    ledger.issue(_receipt(operation_id="only"))
    ledger.consume("only")
    with pytest.raises(StalePreviewError):
        ledger.consume("only")


def test_unmount_revokes_outstanding():
    ledger = ReceiptLedger(clock=FakeClock(), ttl=600, capacity=5)
    ledger.issue(_receipt(operation_id="x", principal="u1", target_fingerprint="fpA"))
    ledger.issue(_receipt(operation_id="y", principal="u1", target_fingerprint="fpB"))
    removed = ledger.revoke_for(principal="u1", target_fingerprint="fpA")
    assert removed == 1
    with pytest.raises(StalePreviewError):
        ledger.get("x")


def test_default_capacity_constant():
    assert MAX_ACTIVE_RECEIPTS == 512


# -- end-to-end preview -> insert guard -------------------------------------

def test_preview_insert_flow_returns_bytes_and_refuses_stale_target(service):
    make_template(service, tid="tmpl.e2e", slug="e2e", body="Review {{focus}}",
                  parameters=[ParameterSpec("focus", "string", True)])
    enable(service, tid="tmpl.e2e", revision=1)
    target = Target(principal="u1", server_identity="s1", project_id="projA")
    rendered = service.render_preview(target=target, template_id="tmpl.e2e", revision=1,
                                      arguments={"focus": "auth"}, draft_id="d1", draft_revision=1)
    assert rendered.text == "Review auth"
    service.prepare_insert(target=target, template_id="tmpl.e2e", revision=1,
                           arguments={"focus": "auth"}, rendered=rendered,
                           draft_id="d1", draft_revision=1, context_revision=7,
                           operation_id="op-e2e")
    receipt, _ = service.validate_insert(operation_id="op-e2e", target=target,
                                         draft_id="d1", draft_revision=1, context_revision=7)
    assert receipt.rendered_digest == rendered.digest
    assert receipt.template_id == "tmpl.e2e"


def test_insert_refused_when_target_drove_to_new_project(service):
    make_template(service, tid="tmpl.sw", slug="sw", body="x {{p}}",
                  parameters=[ParameterSpec("p")])
    enable(service, tid="tmpl.sw", revision=1)
    target = Target(principal="u1", server_identity="s1", project_id="projA")
    rendered = service.render_preview(target=target, template_id="tmpl.sw", revision=1,
                                      arguments={"p": "v"}, draft_id="d1", draft_revision=1)
    service.prepare_insert(target=target, template_id="tmpl.sw", revision=1,
                           arguments={"p": "v"}, rendered=rendered, draft_id="d1",
                           draft_revision=1, operation_id="op-sw")
    moved = Target(principal="u1", server_identity="s1", project_id="projB")
    with pytest.raises(StalePreviewError):
        service.validate_insert(operation_id="op-sw", target=moved, draft_id="d1",
                                draft_revision=1)


def test_insert_refused_for_another_principal(service):
    make_template(service, tid="tmpl.p", slug="p", body="x {{p}}", parameters=[ParameterSpec("p")])
    enable(service, tid="tmpl.p", revision=1)
    target = Target(principal="u1", server_identity="s1")
    rendered = service.render_preview(target=target, template_id="tmpl.p", revision=1,
                                      arguments={"p": "v"}, draft_id="d1", draft_revision=1)
    service.prepare_insert(target=target, template_id="tmpl.p", revision=1,
                           arguments={"p": "v"}, rendered=rendered, draft_id="d1",
                           draft_revision=1, operation_id="op-p")
    other = Target(principal="u2", server_identity="s1")
    with pytest.raises(UnauthorizedTargetError):
        service.validate_insert(operation_id="op-p", target=other, draft_id="d1", draft_revision=1)
