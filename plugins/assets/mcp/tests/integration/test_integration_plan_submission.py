"""T10-INT-07: mcp.planForSubmission through the REAL Harness C4 machinery.

The submission leg of the chain: the composed service's
``harness.configuration_service`` port IS the real
``ordessa_harness.application.ConfigurationApplicationService`` over the
real ``HarnessContributionRegistry`` carrier (the brand adapter contributed
the way the product composition does) and the real sqlite
``OperationJournal``; the runtime is the labelled in-memory controlled
runtime of the tests/harness_wiring precedent (fake runtime, labelled - no
CLI spawn, no network), and the native planner seam is the REAL brand
compile over the REAL definition store snapshot from the wire face.

Cells:
* the happy plan with the labelling chain double (assess forced
  ``supported`` - wiring evidence ONLY): the complete effective set
  (native entry + managed exclusion record, both from real stores) is
  compiled, merged and planned by the real service; the plan is fencing on
  the caller's expectedRevision; NOTHING applies (this domain never
  launches: zero activations, zero permit spends, journal file present);
* the honesty counterexample with the REAL brand adapter: assess is
  ``unknown`` -> the real service refuses BEFORE any effect -> the wire
  answers the typed CAPABILITY_UNSUPPORTED family (never fake green);
* no permit / no expectedRevision / revision drift -> the typed refusals
  (FORBIDDEN / INVALID_REQUEST / CONFLICT_VERSION) with zero effects;
* the placeholder gate next to the real port -> SUBMISSION_GATE_AMBIGUOUS
  (one gate, contracts §1).

Evidence ID: T10-INT-07.
"""
from __future__ import annotations

from integration_helpers import PLAN_PARAMS, make_plan_stack, plan_full_setup


def test_plan_submission_happy_path_with_chain_double(tmp_path):
    env = make_plan_stack(tmp_path)
    stack = env["stack"]
    setup = plan_full_setup(stack)
    assert setup["state"].is_file()  # the managed observation really ran

    preview = stack.call("mcp.resolvePreview", serverScope="s1",
                         principal="alice", **PLAN_PARAMS)
    digest = preview["snapshot"]["snapshotDigest"]
    assert preview["snapshot"]["laneByDefinition"]["natsrv"]["lane"] == "native"
    assert preview["snapshot"]["laneByDefinition"]["mansrv"]["lane"] == "managed"

    submission = stack.call("mcp.planForSubmission", serverScope="s1",
                            principal="alice", expectedRevision="base-1",
                            submissionPermit="signed:mcp-permit", **PLAN_PARAMS)
    view = submission["submission"]
    assert view["kind"] == "plan"
    assert view["beforeRevision"] == "base-1"
    assert view["planId"]  # produced by the REAL C4 service
    assert submission["snapshotDigest"] == digest
    assert submission["credentialReferences"] == []  # literal-only chain set
    assert env["planner_calls"] == ["claude-code"]  # the real seam was asked

    # zero-apply facts: planning never launches (contracts §1 row 6)
    assert env["runtime"].activate_count == 0
    assert env["permits"].calls == 0
    assert (tmp_path / "operations.sqlite").is_file()  # the real journal


def test_plan_submission_brand_honesty_refuses(tmp_path):
    """The real claude adapter answers ``unknown`` -> the REAL C4 service
    refuses with capability-unsupported before compile/merge/effect; the
    wire face carries the typed refusal. No chain double, no fake green."""
    env = make_plan_stack(tmp_path, chain_double=False)
    stack = env["stack"]
    stack.expect_refusal(
        "mcp.planForSubmission", family="CAPABILITY_UNSUPPORTED",
        internal_code="MCP_GATE_CAPABILITY_UNSUPPORTED",
        serverScope="s1", principal="alice", expectedRevision="base-1",
        submissionPermit="signed:mcp-permit", **PLAN_PARAMS)
    assert env["runtime"].activate_count == 0
    assert list(env["runtime"].root.iterdir()) == []  # nothing materialized
    assert env["permits"].calls == 0


def test_plan_submission_requires_the_permit(tmp_path):
    env = make_plan_stack(tmp_path)
    stack = env["stack"]
    stack.expect_refusal("mcp.planForSubmission", family="FORBIDDEN",
                         internal_code="SUBMISSION_PERMIT_REQUIRED",
                         serverScope="s1", principal="alice",
                         expectedRevision="base-1", **PLAN_PARAMS)
    assert env["runtime"].activate_count == 0 and env["permits"].calls == 0


def test_plan_submission_requires_the_expected_revision(tmp_path):
    env = make_plan_stack(tmp_path)
    stack = env["stack"]
    stack.expect_refusal("mcp.planForSubmission", family="INVALID_REQUEST",
                         internal_code="EXPECTED_REVISION_REQUIRED",
                         serverScope="s1", principal="alice",
                         submissionPermit="signed:mcp-permit", **PLAN_PARAMS)
    assert env["runtime"].activate_count == 0 and env["permits"].calls == 0


def test_plan_submission_revision_drift_is_a_cas_conflict(tmp_path):
    env = make_plan_stack(tmp_path)
    stack = env["stack"]
    # the real C4 fence: expectedRevision != the runtime's current revision
    stack.expect_refusal("mcp.planForSubmission", family="CONFLICT_VERSION",
                         internal_code="MCP_CAS_CONFLICT",
                         serverScope="s1", principal="alice",
                         expectedRevision="some-other-revision",
                         submissionPermit="signed:mcp-permit", **PLAN_PARAMS)
    assert env["runtime"].activate_count == 0 and env["permits"].calls == 0


def test_second_submission_gate_refuses(tmp_path):
    """contracts §1: one submission gate. The placeholder port next to the
    real C4 port is a typed conflict, never an order-dependent pick."""
    env = make_plan_stack(tmp_path, with_placeholder_gate=True)
    stack = env["stack"]
    stack.expect_refusal("mcp.planForSubmission", family="CONFLICT_REQUEST",
                         internal_code="SUBMISSION_GATE_AMBIGUOUS",
                         serverScope="s1", principal="alice",
                         expectedRevision="base-1",
                         submissionPermit="signed:mcp-permit", **PLAN_PARAMS)
