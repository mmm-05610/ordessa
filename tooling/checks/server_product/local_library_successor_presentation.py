"""Closed human presentation for the approved Local Library implementation slice.

Instance identities come only from the host-bound typed Intent and Notice. This
adapter fixes the case's small action/path policy; it is not a generic renderer
or a source of authority.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re
from pathlib import PurePosixPath
from uuid import UUID
from zoneinfo import ZoneInfo

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.approvals.consent import WorkPackageNotice
from ordessa_engineering.domain.approvals.implementation import WorkPackageAuthorizationIntent
from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_server.composition.engineering_chat_confirmation import FrozenChatPresentation


_CONTRACT = 'ordessa.work-package-chat-human/1'
_METHOD_ID = 'ordessa.incremental-engineering'
_METHOD_RELEASE = '2.7.2'
_METHOD_SCHEMA = 2
_ACTIONS = ('edit_repository', 'run_checks')
_PATHS = (
    ('catalog/views.py', 'modify'),
    ('catalog/templates/catalog/book_list.html', 'modify'),
    ('catalog/tests/test_views.py', 'modify'),
    ('catalog/tests/test_search.py', 'add'),
)
_EXPECTED_OPERATIONS = {
    'catalog/templates/catalog/book_list.html': ['modify'],
    'catalog/tests/test_search.py': ['add'],
    'catalog/tests/test_views.py': ['modify'],
    'catalog/views.py': ['modify'],
}
_POLICY_TEXT = {
    'checks': 'catalog Django tests with isolated in-memory SQLite, temporary test settings, existing installed dependencies; no live database',
    'excluded': 'models/migrations/settings/dependencies/admin/auth/shared base template/Git/publish/deploy/accept/apply',
    'execution_note': 'Original Unit permission and exact effect mediation remain mandatory; this Grant does not assert OS isolation.',
    'material_egress': 'frozen spec/plan/tasks, required method resources, the four allowed source files, and this implementation report/check results for independent read-only review; no credentials or unrelated private material',
    'predecessor_handling': 'retain original UNKNOWN, closed Unit and debits; no retry, refund, replacement or mutation',
    'preflight': 'Before creating a Unit or consuming actions, verify baseline and all four frozen before hashes, current original permissions and exact effect mediation, and the constrained catalog-check runtime. If unavailable, do not dispatch or install dependencies.',
    'provider': 'DeepSeek official https://api.deepseek.com, deepseek-flash, existing quota',
}
_PREFIX = '检查运行入口已补齐，原图书系统的40项测试通过，真实搜索实施还没开始。'
_APPROVAL_QUESTION = '现在需要你批准一次新的后继派工，原来的UNKNOWN和已消费记录会完整保留。'
_DISCLOSURE = '批准后会如实记录这次答复；这是主Agent记录的聊天批准，平台不独立认证人类身份。'
_REPLY_HINT = '你可以回复：“批准此后继Work及新增edit_repository/run_checks各一次的范围”。'
_SUMMARY_KEYS = frozenset({
    'allowed_operations', 'baseline_commit', 'before_sha256', 'checks', 'excluded',
    'execution_note', 'execution_profile_ref', 'material_egress', 'predecessor',
    'preflight', 'provider', 'repository_id', 'root',
})
_THIRD_SUMMARY_KEYS = (_SUMMARY_KEYS - {'predecessor'}) | {'predecessors'}
_THIRD_PACKAGE = '201104e51dc0d2db77f9975f160d338761f99643b88f9d8a79a77fef3e11b724'
_THIRD_BASELINE = '342d4e9a590caa50bb0749b48cee80b5a3146439'
_THIRD_ROOT = '/home/maoqh/projects/ordessa-demo-local-library'
_PROFILE_KEYS = frozenset({'contentDigest', 'environmentNamespace', 'manifestRevision', 'profileId'})
_PREDECESSOR_KEYS = frozenset({
    'approval_id', 'dispatch_phase', 'execution_operation_ref', 'handling',
    'old_action_consumed', 'work_id',
})
_SHA256_RE = re.compile(r'[0-9a-f]{64}\Z')
_COMMIT_RE = re.compile(r'[0-9a-f]{40}\Z')


def _refuse(code='CONSENT_BINDING_MISMATCH'):
    raise ApplicationError(code)


def _is_id(value):
    return type(value) is str and bool(value.strip()) and len(value) <= 512 and not any(ord(c) < 32 for c in value)


def _uuid(value):
    if type(value) is not str:
        return False
    try:
        return str(UUID(value)) == value.lower()
    except ValueError:
        return False


def _parse_utc(value):
    if type(value) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z', value):
        _refuse('CONSENT_PRESENTATION_CHANGED')
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)
    except ValueError:
        _refuse('CONSENT_PRESENTATION_CHANGED')


def _summary(value):
    if type(value) is not str:
        _refuse()
    try:
        decoded = decode_json(value)
        canonical = canonical_bytes(decoded)
    except (TypeError, ValueError):
        _refuse()
    if type(decoded) is not dict or frozenset(decoded) not in (_SUMMARY_KEYS, _THIRD_SUMMARY_KEYS):
        _refuse()
    if decoded['allowed_operations'] != _EXPECTED_OPERATIONS:
        _refuse()
    for key, expected in _POLICY_TEXT.items():
        if key == 'predecessor_handling':
            continue
        if decoded[key] != expected:
            _refuse()

    baseline = decoded['baseline_commit']
    if type(baseline) is not str or not _COMMIT_RE.fullmatch(baseline):
        _refuse()
    before = decoded['before_sha256']
    if type(before) is not dict or set(before) != set(_EXPECTED_OPERATIONS):
        _refuse()
    for path, operation in _PATHS:
        digest = before[path]
        if operation == 'add':
            if digest is not None:
                _refuse()
        elif type(digest) is not str or not _SHA256_RE.fullmatch(digest):
            _refuse()

    profile = decoded['execution_profile_ref']
    if (type(profile) is not dict or frozenset(profile) != _PROFILE_KEYS
            or type(profile.get('contentDigest')) is not str
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', profile['contentDigest'])
            or not _is_id(profile.get('environmentNamespace'))
            or type(profile.get('manifestRevision')) is not int or profile['manifestRevision'] < 1
            or not _is_id(profile.get('profileId'))):
        _refuse()

    predecessors = _predecessors(decoded)
    keys = (_PREDECESSOR_KEYS | {'attempt', 'unit_id'} if 'predecessors' in decoded
            else _PREDECESSOR_KEYS)
    for predecessor in predecessors:
        old_consumed = (predecessor.get('old_action_consumed')
                        if type(predecessor) is dict else None)
        if (type(predecessor) is not dict or frozenset(predecessor) != keys
            or not _uuid(predecessor.get('approval_id'))
            or predecessor.get('dispatch_phase') != 'unknown'
            or not _uuid(predecessor.get('execution_operation_ref'))
            or predecessor.get('handling') != _POLICY_TEXT['predecessor_handling']
            or type(old_consumed) is not dict
            or set(old_consumed) != {'edit_repository', 'run_checks'}
            or any(type(value) is not int or value != 1 for value in old_consumed.values())
            or not _is_id(predecessor.get('work_id'))):
            _refuse()
        if 'predecessors' in decoded and (type(predecessor['attempt']) is not int
                or predecessor['attempt'] != 1 or type(predecessor['unit_id']) is not str
                or not re.fullmatch(r'unit-[0-9a-f]{32}', predecessor['unit_id'])):
            _refuse()
    if 'predecessors' in decoded and any(len({p[key] for p in predecessors}) != 2
            for key in ('work_id', 'approval_id', 'execution_operation_ref', 'unit_id')):
        _refuse()

    repository_id = decoded['repository_id']
    if not _is_id(repository_id):
        _refuse()
    root = decoded['root']
    if (type(root) is not str or root == '/' or not root.startswith('/') or '\\' in root
            or any(part in {'.', '..'} for part in PurePosixPath(root).parts)
            or str(PurePosixPath(root)) != root):
        _refuse()
    return decoded, sha256(canonical).hexdigest()


def _predecessors(summary):
    if 'predecessors' not in summary:
        return [summary['predecessor']]
    values = summary['predecessors']
    if type(values) is not list or len(values) != 2:
        _refuse()
    return values


def _expected_action_scope(authorization, summary_digest):
    from ordessa_engineering.domain.approvals.scope import (
        ActionScope, EffectLimit, EnvironmentRef, PathRule, RepositoryScope,
    )
    from ordessa_engineering.domain.common.models.values import Digest

    summary, _ = _summary(authorization.request_summary)
    profile = summary['execution_profile_ref']
    rules = tuple(PathRule(path, 'exact', (operation,)) for path, operation in (
        ('catalog/tests/test_search.py', 'add'),
        ('catalog/templates/catalog/book_list.html', 'modify'),
        ('catalog/tests/test_views.py', 'modify'),
        ('catalog/views.py', 'modify'),
    ))
    return ActionScope(
        project_id=authorization.scope.project_id,
        repository_scopes=(RepositoryScope(summary['repository_id'], rules),),
        environment_refs=(EnvironmentRef(
            profile['environmentNamespace'], profile['profileId'],
            Digest('sha256', profile['contentDigest'].split(':', 1)[1])),),
        effect_limits=tuple(EffectLimit(action, summary['repository_id'], Digest('sha256', summary_digest))
                            for action in _ACTIONS),
        exclusions=(),
        implementation_intent_id=authorization.intent_id,
    )


def _authorization(intent):
    if type(intent) is not WorkPackageAuthorizationIntent:
        _refuse()
    authorization = intent.authorization
    summary, summary_digest = _summary(authorization.request_summary)
    profile = summary['execution_profile_ref']
    if (authorization.scope.realm_id != profile['environmentNamespace']
            or authorization.package_ref.realm_id != authorization.scope.realm_id
            or authorization.package_ref.project_id != authorization.scope.project_id
            or authorization.method_ref.method_id != _METHOD_ID
            or authorization.method_ref.release_version != _METHOD_RELEASE
            or authorization.method_ref.schema_version != _METHOD_SCHEMA
            or authorization.action_id != 'incremental.implement-package'
            or authorization.step_id != 'implement'
            or authorization.actions != _ACTIONS
            or tuple((item.action, item.limit) for item in authorization.action_budgets)
                != (('edit_repository', 1), ('run_checks', 1))):
        _refuse()

    expected_scope = _expected_action_scope(authorization, summary_digest)
    scope_map = dict(authorization.scope_by_action)
    if (set(scope_map) != set(_ACTIONS)
            or any(scope_map[action] != expected_scope for action in _ACTIONS)):
        _refuse()
    for action_scope in scope_map.values():
        if (len(action_scope.repository_scopes) != 1
                or len(action_scope.environment_refs) != 1
                or len(action_scope.effect_limits) != 2
                or action_scope.exclusions != ()):
            _refuse()
    if authorization.digest is None or intent.digest is None:
        _refuse()
    if any(p['work_id'] == authorization.work_id for p in _predecessors(summary)):
        _refuse()
    if 'predecessors' in summary and (
            authorization.package_ref.package_id != 'generated-package'
            or authorization.package_ref.digest.hex != _THIRD_PACKAGE
            or summary['baseline_commit'] != _THIRD_BASELINE or summary['root'] != _THIRD_ROOT
            or _parse_utc(authorization.expires_at) - _parse_utc(authorization.not_before)
                != timedelta(hours=4)):
        _refuse()
    return authorization, summary, summary_digest


def _context(intent, authorization, summary):
    if 'predecessors' in summary:
        return _third_context(intent, authorization, summary)
    profile = summary['execution_profile_ref']
    package_digest = authorization.package_ref.digest.hex
    lines = [
        '本次具体范围：',
        f'- 同一个实施包 {authorization.package_ref.package_id}，摘要 {package_digest}；方法{authorization.method_ref.release_version}。',
        f'- 新Work：{authorization.work_id}，revision {authorization.work_revision}。新增 edit_repository、run_checks 各一次正式派工预算，不限制Unit内部模型调用次数。',
        f'- 目标仍是 {summary["root"]}，基线{summary["baseline_commit"]}。仅修改 catalog/views.py、catalog/templates/catalog/book_list.html、catalog/tests/test_views.py，可新增 catalog/tests/test_search.py，实现包内书目搜索。',
        '- 只用现有依赖、临时设置和内存SQLite运行catalog测试。派工前再次检查四路径原始摘要、权限和受控测试入口；不满足就不派工、不消费预算、不安装依赖。',
        f'- 使用原Profile的revision {profile["manifestRevision"]}、deepseek-flash和现有额度，把冻结spec/plan/tasks、必要方法资源、上述源码及此次报告和检查结果发给DeepSeek官方 https://api.deepseek.com，用于实施和独立只读审核。不发送凭据或无关私人材料。',
        '- 原Work、attempt 1、ACP UNKNOWN、已关闭Unit和两笔旧消费都不修改、不退款、不重放。这是新的派工；不能认定旧请求未发送或未计费。',
        '- 允许登记此次报告及独立只读审核；不包含Git提交、发布部署、最终接受/adopt、依赖或全局配置修改、真实数据库变更、服务重启。Local工作目录不代表操作系统沙箱隔离。',
        f'- 有效至今天{datetime.fromisoformat(authorization.expires_at[:-1] + "+00:00").astimezone(ZoneInfo("Asia/Shanghai")):%H:%M:%S}（北京时间）。新Intent摘要为{intent.digest.hex}。正式登记时必须与这次展示的对象和范围一致，否则停止。',
    ]
    before = summary['before_sha256']
    if set(before) != set(_EXPECTED_OPERATIONS):
        _refuse()
    return '\n'.join(lines) + '\n\n' + _DISCLOSURE


def _third_context(intent, authorization, summary):
    """Closed third-attempt view; historical single-predecessor text is stable."""
    profile = summary['execution_profile_ref']
    start, end = _parse_utc(authorization.not_before), _parse_utc(authorization.expires_at)
    local = ZoneInfo('Asia/Shanghai')
    lines = [
        '本次请求为第三次独立派工；尚未登记新Work、Challenge或Grant，尚未消费新预算。',
        f'- 正式包：generated-package；SHA256 {authorization.package_ref.digest.hex}。方法 {authorization.method_ref.release_version}；snapshot {authorization.method_ref.snapshot_digest.hex}。',
        f'- 新Work：{authorization.work_id}，revision {authorization.work_revision}；Work摘要 {authorization.work_digest.hex}。',
        f'- 新Intent：{authorization.intent_id}；摘要 {intent.digest.hex}；Notice摘要 {intent.notice_ref.digest.hex}。',
        '- 新增正式预算：edit_repository=1、run_checks=1，各允许一次正式派工消费；不限制Unit内部模型调用总次数，不退还或复用旧消费。',
        f'- 目标：{summary["root"]}；基线 {summary["baseline_commit"]}。实施该包内的书目搜索。',
        '- 仅可修改 catalog/views.py、catalog/templates/catalog/book_list.html、catalog/tests/test_views.py；可新增 catalog/tests/test_search.py。原始SHA256如下：',
    ]
    lines.extend(f'  {path}：{summary["before_sha256"][path] or "原先不存在，仅可新增"}'
                 for path, _operation in _PATHS)
    lines.extend([
        '- 仅用现有依赖、临时设置和内存SQLite运行catalog检查；不接触真实数据库。创建Unit或消费前必须重核原权限、四路径效果中介、原始摘要和受控检查runtime；任何门缺失即停止，不安装依赖。',
        f'- 原Profile：environmentNamespace={profile["environmentNamespace"]}；profileId={profile["profileId"]}；manifestRevision={profile["manifestRevision"]}；contentDigest={profile["contentDigest"]}。',
        '- 使用现有额度、deepseek-flash，经 DeepSeek 官方 https://api.deepseek.com 发送冻结spec/plan/tasks、必要方法资源、四路径源码及本次报告/检查结果，用于实施和独立只读审核；不发送凭据或无关私人材料。',
        '- 保留原Unit/issuer/records/verifier和真实权限。Local工作目录不代表操作系统沙箱隔离。',
        '- 下列两次旧记录分别保持UNKNOWN、各action已消费1、原Unit已关闭；不重放、不退款、不换绑、不替换旧Unit、不改历史终态；不能据空events认定旧请求未发送或未计费：',
    ])
    lines.extend(f'  Work {p["work_id"]}；attempt {p["attempt"]}；ACP {p["execution_operation_ref"]}；Unit {p["unit_id"]}；Grant {p["approval_id"]}；edit_repository/run_checks各已消费1。'
                 for p in summary['predecessors'])
    lines.extend([
        '- 允许正式登记本次实施报告并进行独立只读审核；不授权最终接受/adopt、Git提交/发布、部署、依赖/全局配置修改、真实数据库变更或服务重启。',
        f'- 新有效窗口为 {authorization.not_before} 至 {authorization.expires_at}，均为UTC，恰好4小时；北京时间 {start.astimezone(local):%Y-%m-%d %H:%M:%S} 至 {end.astimezone(local):%Y-%m-%d %H:%M:%S}。这是待你明确批准的新窗口，不延长或复活旧Grant。',
        '- 批准后仍须经原正式入口登记完全相同的Work/Notice/Intent和新pending Challenge，如实绑定实际展示全文及本次答复；对象、版本、上下文或当前权限不符即停止。',
    ])
    return '\n'.join(lines) + '\n\n' + _DISCLOSURE


def _render(intent, notice, *, presented_at, bound_intent, bound_notice, bound_presented_at):
    if intent != bound_intent or notice != bound_notice or presented_at != bound_presented_at:
        _refuse()
    authorization, summary, _ = _authorization(intent)
    if (type(notice) is not WorkPackageNotice
            or notice.authorization != authorization
            or notice.policy_ref != intent.policy_ref
            or notice.ref != intent.notice_ref):
        _refuse()

    now = _parse_utc(presented_at)
    not_before = _parse_utc(authorization.not_before)
    expires_at = _parse_utc(authorization.expires_at)
    if not not_before <= now < expires_at:
        _refuse('CONSENT_EXPIRED')
    expiry_local = expires_at.astimezone(ZoneInfo('Asia/Shanghai'))
    if ('predecessors' not in summary
            and expiry_local.date() != now.astimezone(ZoneInfo('Asia/Shanghai')).date()):
        _refuse('CONSENT_PRESENTATION_CHANGED')
    expiry_local = expiry_local.replace(microsecond=0)
    context = _context(intent, authorization, summary)
    prefix = ('诊断链受控核验已完成，真实搜索实施仍未完成。'
              if 'predecessors' in summary else _PREFIX)
    question = prefix + _APPROVAL_QUESTION + '\n\n' + context + '\n\n' + _REPLY_HINT
    return {'question': question, 'necessary_context': context}


def build_local_library_successor_presentation(intent, notice, *, presented_at):
    """Bind a trusted host-selected Intent/Notice to this exact human view."""
    authorization, _, _ = _authorization(intent)
    if (type(notice) is not WorkPackageNotice
            or notice.authorization != authorization
            or notice.policy_ref != intent.policy_ref
            or notice.ref != intent.notice_ref):
        _refuse()
    now = _parse_utc(presented_at)
    if not _parse_utc(authorization.not_before) <= now < _parse_utc(authorization.expires_at):
        _refuse('CONSENT_EXPIRED')

    presented_at_value = presented_at

    def render(bound_intent, bound_notice, *, presented_at):
        return _render(bound_intent, bound_notice, presented_at=presented_at,
                       bound_intent=intent, bound_notice=notice,
                       bound_presented_at=presented_at_value)

    return FrozenChatPresentation(
        intent=intent,
        notice=notice,
        presented_at=presented_at_value,
        renderer=render,
        contract_id=_CONTRACT,
    )
