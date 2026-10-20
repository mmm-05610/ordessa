from types import SimpleNamespace
from contextlib import contextmanager
from ordessa_infrastructure.encoding import canonical_bytes
from dataclasses import dataclass

import pytest

from ordessa_engineering.adapters.native_records.declared_reviewer import (
    DeclaredUnitReviewerSource,
)
from ordessa_engineering.application.contracts.errors import ApplicationError


def test_native_review_operation_has_a_stable_identity_bound_to_plan_and_assignment():
    from dataclasses import replace
    from ordessa_engineering.domain.common.models.identity import Scope
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_engineering.domain.reviews.assignments import ReviewerAssignmentRef
    plan = SimpleNamespace(plan_digest=Digest('sha256', 'a' * 64))
    assignment = SimpleNamespace(ref=ReviewerAssignmentRef(
        Scope('realm', 'project'), 'assignment', Digest('sha256', 'b' * 64)))
    operation = DeclaredUnitReviewerSource.operation_ref(plan, assignment)
    from ordessa_engineering.application.usecases.changes.declared_report import declared_review_operation_ref
    assert operation == declared_review_operation_ref(plan, assignment)
    assert operation.startswith('declared-review/')
    assert operation == DeclaredUnitReviewerSource.operation_ref(plan, assignment)
    assert operation != DeclaredUnitReviewerSource.operation_ref(
        SimpleNamespace(plan_digest=Digest('sha256', 'c' * 64)), assignment)
    assert operation != DeclaredUnitReviewerSource.operation_ref(plan,
        SimpleNamespace(ref=replace(assignment.ref, assignment_id='another-assignment')))


def test_report_source_is_an_optional_same_owner_port(tmp_path):
    factory = SimpleNamespace(authority_id='authority-a')
    methods = SimpleNamespace(factory=factory)
    bindings = SimpleNamespace(factory=factory)
    access = SimpleNamespace(guard_current_capability=lambda *_args: None)
    records = SimpleNamespace(query_acp_turn=lambda *_args, **_kwargs: None)
    blobs = SimpleNamespace(authority_id='authority-a')
    report_source = SimpleNamespace(factory=factory, methods=methods, blobs=blobs,
        correction_review_evidence=lambda *_args: None)
    paths = tuple((tmp_path / name).resolve() for name in ('spec.md', 'plan.md', 'tasks.md', 'README.md'))
    source = DeclaredUnitReviewerSource(factory, access=access, scope=object(), methods=methods,
        bindings=bindings, records=records, blobs=blobs, query_factory=lambda *_args: None,
        source_reviewer=object(), review_paths=paths, report_source=report_source)
    assert source.report_source is report_source

    foreign = SimpleNamespace(factory=object(), methods=methods, blobs=blobs,
        correction_review_evidence=lambda *_args: None)
    with pytest.raises(ApplicationError, match='REVIEW_SOURCE_AUTHORITY_MISMATCH'):
        DeclaredUnitReviewerSource(factory, access=access, scope=object(), methods=methods,
            bindings=bindings, records=records, blobs=blobs, query_factory=lambda *_args: None,
            source_reviewer=object(), review_paths=paths, report_source=foreign)


@dataclass(frozen=True)
class _Ref:
    identifier: str


@dataclass(frozen=True)
class _Plan:
    plan_digest: object
    requirement: object


@dataclass(frozen=True)
class _Assignment:
    ref: object
    request_version: int
    fence: int
    reviewer_unit_ref: dict
    roles: tuple


def test_checkpoint_review_prompt_contains_bounded_historical_check_observation(monkeypatch):
    from ordessa_engineering.adapters.native_records import declared_reviewer as module
    from ordessa_engineering.domain.artifacts.method_binding import MethodRef
    from ordessa_engineering.domain.common.models.refs import BlobRef
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_engineering.domain.reviews.refs import SubmissionRef

    scope = SimpleNamespace(realm_id='realm-a', project_id='project-a')
    method = MethodRef('method-a', '1', 2, Digest('sha256', 'a' * 64))
    submission_ref = SubmissionRef('realm-a', 'project-a', 'submission-a', Digest('sha256', 'b' * 64))
    author = {'environmentNamespace': 'env-a', 'unitId': 'author-unit',
              'ownerProviderRef': {'provider': 'owner'}, 'sourceRevision': 'rev-a'}
    reviewer = {'environmentNamespace': 'env-a', 'unitId': 'reviewer-unit',
                'ownerProviderRef': {'provider': 'owner'}, 'sourceRevision': 'rev-r'}
    @dataclass(frozen=True)
    class _Target:
        ref: object
    @dataclass(frozen=True)
    class _Targets:
        targets: tuple
    @dataclass(frozen=True)
    class _Requirement:
        method_ref: object
        expected_targets: object
    plan = _Plan(Digest('sha256', 'c' * 64), _Requirement(method, _Targets((_Target(submission_ref),))))
    assignment = _Assignment(_Ref('assignment-a'), 0, 1, reviewer, ('reviewer',))
    evidence = {'contract': 'ordessa.original-check-observation/1',
        'checkpoint_ref': {'digest': {'algorithm': 'sha256', 'hex': '1' * 64}},
        'plan_ref': {'digest': {'algorithm': 'sha256', 'hex': '2' * 64}},
        'origin_operation_ref': 'business-op', 'journal_ref': {'digest': {'algorithm': 'sha256', 'hex': '3' * 64}},
        'excerpt_ref': {'digest': {'algorithm': 'sha256', 'hex': '4' * 64}},
        'tool_call_id': 'check-call', 'command_digest': {'algorithm': 'sha256', 'hex': '5' * 64},
        'command_utf8': 'check-suite --offline', 'excerpt_utf8': '{"type":"message"}',
        'files': [], 'limitation': 'selected original Pi journal observation; not independently authenticated execution proof'}
    checkpoint_ref = BlobRef(Digest('sha256', '6' * 64), 1, 'application/json', 'checkpoint')
    submission = SimpleNamespace(ref=submission_ref, package_ref=_Ref('package'),
        checkpoint_ref=checkpoint_ref, method_content=SimpleNamespace(value={'profile_ref': {}}))
    package = SimpleNamespace(ref=_Ref('package'), payload=SimpleNamespace(documents=()))
    dispatch = SimpleNamespace(unit_ref_bytes=canonical_bytes(author), execution_operation_ref='business-op')
    @contextmanager
    def guard(*_args, **_kwargs):
        yield object()
    class _Factory:
        @contextmanager
        def begin(self, *_args, **_kwargs):
            yield SimpleNamespace(
                submissions=SimpleNamespace(resolve=lambda _ref: submission),
                implementation=SimpleNamespace(resolve_package=lambda _ref: package))
    factory = _Factory()
    class _Methods:
        def guard(self, *_args, **_kwargs): return guard()
        def resource_ref(self, _context, _method, name): return _Ref(name)
        def read_resource(self, _context, _ref): return b'{}'
    class _Bindings:
        def resolve_declared_submission_plan(self, *_args):
            return SimpleNamespace(standard=SimpleNamespace(criteria=(SimpleNamespace(statement='criterion'),)))
    monkeypatch.setattr(module, 'resolve_declared_report_binding', lambda *_args: dispatch)
    source = object.__new__(DeclaredUnitReviewerSource)
    source.factory, source.methods, source.bindings = factory, _Methods(), _Bindings()
    source.report_source = SimpleNamespace(correction_review_evidence=lambda _ctx, _sub: evidence)
    result = source.prompt_parameters(SimpleNamespace(scope=scope), plan,
        SimpleNamespace(version=0, fence=1), assignment, 'session-a')
    body = __import__('ordessa_infrastructure.encoding', fromlist=['decode_json']).decode_json(
        result['prompt'][1]['text'].encode())
    assert body['original_check_observation'] == evidence
    assert 'historical selected evidence only' in body['transport_response']['instruction']
    assert 'Do not edit files or run commands.' in body['transport_response']['instruction']

    source.report_source = None
    with pytest.raises(ApplicationError, match='REVIEW_SOURCE_AUTHORITY_MISMATCH'):
        source.prompt_parameters(SimpleNamespace(scope=scope), plan,
            SimpleNamespace(version=0, fence=1), assignment, 'session-a')


@pytest.mark.parametrize('state,operation,expected_mode', [
    ('requested', 'engineering.reviews.record', True),
    ('requested', 'engineering.work.invoke', None),
    ('recorded', 'engineering.work.invoke', False),
])
def test_pending_trust_reaches_original_verifier_only_in_the_record_command(state, operation, expected_mode):
    """Controlled ports stop at the verifier; this test never grants trust."""
    from ordessa_engineering.domain.reviews.refs import SubmissionRef
    from ordessa_engineering.domain.common.models.values import Digest
    @contextmanager
    def guard(*_args, **_kwargs):
        yield ()
    @contextmanager
    def begin(*_args):
        yield SimpleNamespace(reviews=SimpleNamespace(get_request=lambda _: SimpleNamespace(state=state)))
    def require(context, capability):
        if operation != capability:
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
    class AtOriginalVerifier(Exception):
        pass
    modes = []
    def read(*_args, recording, **_kwargs):
        modes.append(recording)
        raise AtOriginalVerifier()
    source = object.__new__(DeclaredUnitReviewerSource)
    source.factory = SimpleNamespace(begin=begin)
    source.scope = object()
    source.source_reviewer = SimpleNamespace(guard_trust=guard)
    source.access = SimpleNamespace(guard_current_capability=guard, require=require)
    source.methods = SimpleNamespace(guard=guard)
    source.bindings = SimpleNamespace(resolve_declared_submission_plan=lambda *_: SimpleNamespace(standard=object()))
    source._read = read
    record = SimpleNamespace(raw_response_ref=object(), plan=SimpleNamespace(review_id='review',
        requirement=SimpleNamespace(method_ref=object(), expected_targets=SimpleNamespace(targets=(
            SimpleNamespace(ref=SubmissionRef('realm', 'project', 'submission', Digest('sha256', 'd' * 64))),)))))
    context = SimpleNamespace(scope=object())
    error = ApplicationError if expected_mode is None else AtOriginalVerifier
    with pytest.raises(error):
        with source.guard_trust(context, (record,)):
            pytest.fail('controlled verifier must never yield trusted evidence')
    assert modes == ([] if expected_mode is None else [expected_mode])


def _source(tmp_path):
    cwd = tmp_path / "unit-cwd"
    cwd.mkdir()
    repository = tmp_path / "repository"
    repository.mkdir()
    paths = tuple((repository / name).resolve() for name in
                  ("spec.md", "plan.md", "tasks.md", "README.md"))

    class _Records:
        def owner_read_unit(self, _unit_id):
            return SimpleNamespace(facts={"privateRootFacts": {"cwd": str(cwd)}})

    source = object.__new__(DeclaredUnitReviewerSource)
    source.records = _Records()
    source.review_paths = frozenset(paths)
    return source, paths


def _update(tool_id, status, decision=None, *, update_type="tool_call"):
    params = {
        "type": update_type,
        "approval": "file",
        "toolCallId": tool_id,
        "status": status,
        "update": {"sessionUpdate": update_type, "toolCallId": tool_id,
                   "status": status, "title": "read file"},
    }
    if decision is not None:
        params["permissionDecision"] = decision
    return {"raw": {"jsonrpc": "2.0", "method": "session/update", "params": params}}


def _permission(tool_id, path, *, approval="file", kind="read", paths=None):
    paths = [path] if paths is None else paths
    return {"raw": {"jsonrpc": "2.0", "id": 17,
        "method": "session/request_permission", "params": {
            "sessionId": "session", "toolCallId": tool_id, "approval": approval,
            "toolCall": {"toolCallId": tool_id, "kind": kind,
                         "locations": [{"path": item} for item in paths]},
            "files": paths,
            "options": [
                {"optionId": "accept", "kind": "allow_once"},
                {"optionId": "acceptForSession", "kind": "allow_always"},
                {"optionId": "decline", "kind": "reject_once"},
            ],
        }}}


def _agent_message():
    return {"raw": {"jsonrpc": "2.0", "method": "session/update", "params": {
        "type": "message", "update": {"sessionUpdate": "agent_message_chunk",
        "content": {"type": "text", "text": "Reviewing the pinned materials."}},
    }}}


def test_go_read_tool_event_may_precede_permission_and_agent_chunks_remain_allowed(tmp_path):
    source, paths = _source(tmp_path)
    receipt = {"events": [
        _agent_message(),
        _update("tool-1", "in_progress"),
        _permission("tool-1", str(paths[0])),
        _update("tool-1", "completed", "approved"),
        _agent_message(),
        {"raw": {"jsonrpc": "2.0", "id": 18, "method": "fs/read_text_file",
                 "params": {"path": str(paths[1])}}},
    ]}

    source._read_only_events({"unitId": "unit"}, receipt)


def test_native_pi_tool_call_update_retains_unique_one_shot_read_gate(tmp_path):
    source, paths = _source(tmp_path)
    initial = _update("native-read", "in_progress", update_type="tool_call_update")
    # Pi announces a tool before the approval subsystem has classified it.
    initial['raw']['params'].pop('approval')
    source._read_only_events({"unitId": "unit"}, {"events": [
        initial,
        _permission("native-read", str(paths[0])),
        _update("native-read", "completed", "approved", update_type="tool_call_update"),
    ]})


@pytest.mark.parametrize("violation", ["outer_type", "command", "write", "missing_permission", "missing_final_approval"])
def test_native_pi_update_mapping_does_not_expand_read_permission(tmp_path, violation):
    source, paths = _source(tmp_path)
    first = _update("native-read", "in_progress", update_type="tool_call_update")
    final = _update("native-read", "completed", "approved", update_type="tool_call_update")
    permission = _permission("native-read", str(paths[0]))
    if violation == "outer_type":
        final["raw"]["params"]["type"] = "tool_call"
    elif violation == "command":
        permission["raw"]["params"]["approval"] = "command"
        permission["raw"]["params"]["toolCall"]["kind"] = "execute"
    elif violation == "write":
        permission["raw"]["params"]["toolCall"]["kind"] = "edit"
    elif violation == "missing_final_approval":
        final["raw"]["params"].pop("approval")
    events = [first, final] if violation == "missing_permission" else [first, permission, final]
    with pytest.raises(ApplicationError, match="REVIEW_READ_ONLY_SCOPE_VIOLATION"):
        source._read_only_events({"unitId": "unit"}, {"events": events})


def _missing_permission(path):
    return [_update("tool-1", "in_progress"), _update("tool-1", "completed", "approved")]


def _mismatched_tool_id(path):
    return [_update("tool-1", "in_progress"), _permission("tool-2", path),
            _update("tool-1", "completed", "approved")]


def _cross_scope(path):
    outside = "/outside/private.md"
    return [_update("tool-1", "in_progress"), _permission("tool-1", path, paths=[path, outside]),
            _update("tool-1", "completed", "approved")]


def _command_permission(path):
    return [_update("tool-1", "in_progress"),
            _permission("tool-1", path, approval="command", kind="execute"),
            _update("tool-1", "completed", "approved")]


def _edit_permission(path):
    return [_update("tool-1", "in_progress"),
            _permission("tool-1", path, kind="edit"),
            _update("tool-1", "completed", "approved")]


def _session_wide_approval(path):
    return [_update("tool-1", "in_progress"), _permission("tool-1", path),
            _update("tool-1", "completed", "approved_for_session")]


def _incomplete(path):
    return [_update("tool-1", "in_progress"), _permission("tool-1", path)]


def _duplicate_permission(path):
    return [_update("tool-1", "in_progress"), _permission("tool-1", path),
            _permission("tool-1", path), _update("tool-1", "completed", "approved")]


@pytest.mark.parametrize("event_builder", [
    _missing_permission, _mismatched_tool_id, _cross_scope, _command_permission,
    _edit_permission, _session_wide_approval, _incomplete, _duplicate_permission,
])
def test_tool_event_requires_unique_matching_one_shot_read_permission(tmp_path, event_builder):
    source, paths = _source(tmp_path)

    with pytest.raises(ApplicationError, match="REVIEW_READ_ONLY_SCOPE_VIOLATION"):
        source._read_only_events({"unitId": "unit"}, {"events": event_builder(str(paths[0]))})


@pytest.mark.parametrize("method,params", [
    ("fs/write_text_file", {"path": "/tmp/spec.md", "content": "changed"}),
    ("terminal/command", {"command": "cat spec.md"}),
])
def test_write_and_command_channels_are_rejected(tmp_path, method, params):
    source, _paths = _source(tmp_path)

    with pytest.raises(ApplicationError, match="REVIEW_READ_ONLY_SCOPE_VIOLATION"):
        source._read_only_events({"unitId": "unit"}, {"events": [
            {"raw": {"jsonrpc": "2.0", "id": 19, "method": method, "params": params}},
        ]})
