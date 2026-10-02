"""Harness-owned, effect-once provider restoration over a live ACP owner.

This renews an instance fence, not a Profile application receipt. The consumer
must validate the newly effective configuration before allowing a prompt.
Credentials are supplied afresh for execute and retained only as digests.
Unknown operations are queried, never re-executed, including lost RPC replies.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
from threading import RLock
from contextlib import nullcontext

from ...server_acp.native_action_executor import configuration_digest
from .initial import initial_model_params


@dataclass(frozen=True)
class ProviderRestorationPlan:
    operation_id: str
    before: object
    expected_generation: str
    expected_config_digest: str
    input_digest: str
    harness_id: str
    publication: object
    authentication_digest: str
    mode: str = 'restart-resume'


class _EvidenceCode(Exception):
    """Nominal whitelisted diagnosis code; carries no digests, ids or values."""


@dataclass(frozen=True)
class ProviderRestorationOutcome:
    state: str
    ticket: object
    restored: object = None
    #: Whitelisted nominal condition code only; never a digest, id or value.
    reason: str = None


class ProviderRestorationService:
    operation_prefix = 'restore:'
    mode = 'restart-resume'
    def __init__(self, channels, owners, *, verify, lease=None, managed_account_factory=None):
        self.channels, self.owners, self.verify = channels, owners, verify
        self.lease = lease or (lambda brand, publication: nullcontext())
        self.managed_account_factory = managed_account_factory
        self._plans, self._attempts, self._channels = {}, {}, {}
        self._lock = RLock()

    @staticmethod
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()

    @classmethod
    def _authentication_digest(cls, desired, credential):
        return cls.digest([dict((key, desired.get(key)) for key in
            ('provider', 'protocol', 'endpoint', 'credentialRef', 'authentication')),
            hashlib.sha256(credential.encode()).hexdigest() if credential is not None else None])

    def _channel(self, snapshot):
        owner = snapshot.owner
        channel = self.channels.get(owner.connection_id)
        if (channel is None or channel.ended is not False
            or snapshot.target.channel_id != owner.connection_id
            or self.channels.native_session_observation(owner.connection_id, owner.native_session_id) is not owner):
            raise ValueError('Current native restoration owner required')
        # These pinned adapters expose a provider-resume operation. Pi's live
        # provider registration is a separate native strategy, not a guessed
        # restart implementation or an implicitly advertised capability.
        if channel.harness_id not in ('codex', 'claude-code'):
            raise ValueError('Verified provider restoration route unavailable')
        return channel

    def _request(self, plan, desired, *, credential=None):
        channel = self._channels[plan.operation_id]
        if channel.harness_id != plan.harness_id:
            raise ValueError('Restoration Harness route changed')
        params = initial_model_params(plan.harness_id, desired, plan.operation_id,
                                      credential=credential)
        if params['provider'].get('authentication') is not None:
            if plan.harness_id != 'codex' or self.managed_account_factory is None:
                raise ValueError('Native restoration authentication destination unavailable')
            account = self.managed_account_factory(plan.harness_id)
            if account.read(refresh=True) != {'authenticated': True, 'method': 'chatgpt-managed'}:
                raise ValueError('Managed account login required')
            # Owned backend path, never a Profile field or a public receipt.
            params['provider']['accountDirectory'] = str(account.account_directory)
        return dict(params, sessionId=plan.before.owner.native_session_id,
                    expectedGeneration=plan.expected_generation,
                    expectedConfigDigest=plan.expected_config_digest,
                    target=asdict(plan.before.target))

    def prepare(self, target, desired, *, operation_key, credential=None):
        """Read/validate only; no provider setter, close, resume or ticket."""
        if (type(operation_key) is not str or not operation_key or len(operation_key) > 256
            or operation_key != operation_key.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in operation_key)):
            raise ValueError('Bounded restoration operation key required')
        with self._lock:
            before = self.owners.readback(target)
            if before.busy is not False:
                raise ValueError('Native session is busy')
            channel = self._channel(before)
            publication = self.verify(channel.harness_id)
            for operation_id, outcome in self._attempts.items():
                previous = self._plans[operation_id].before.target
                if ((previous.server_id, previous.session_id, previous.channel_id)
                    == (target.server_id, target.session_id, target.channel_id)
                    and outcome.state == 'unknown'):
                    raise ValueError('Native restoration already pending; query only')
            operation_id = self.operation_prefix + self.digest([asdict(target), operation_key])
            plan = ProviderRestorationPlan(operation_id, before, before.native_generation,
                configuration_digest(before.config_options), '', channel.harness_id, publication,
                self._authentication_digest(desired, credential), self.mode)
            previous_channel = self._channels.get(operation_id)
            if previous_channel is not None and previous_channel is not channel:
                raise ValueError('Restoration operation owner changed')
            self._channels[operation_id] = channel
            try:
                request = self._request(plan, desired, credential=credential)
                if len(json.dumps(request, ensure_ascii=False).encode()) > 65536:
                    raise ValueError('Restoration input exceeds native bounds')
                plan = ProviderRestorationPlan(operation_id, before, before.native_generation,
                    plan.expected_config_digest, self.digest(request), channel.harness_id,
                    publication, plan.authentication_digest, self.mode)
                previous = self._plans.get(operation_id)
                if previous is not None:
                    if (previous.input_digest != plan.input_digest or previous.before.owner is not before.owner
                        or previous.publication != publication):
                        raise ValueError('Restoration key bound to different input')
                    return previous
                if len(self._plans) >= 256:
                    raise ValueError('Restoration plan capacity exhausted')
                self._plans[operation_id] = plan
                return plan
            except Exception:
                if operation_id not in self._plans:
                    self._channels.pop(operation_id, None)
                raise

    def _require_plan(self, plan):
        if (not isinstance(plan, ProviderRestorationPlan)
            or self._plans.get(plan.operation_id) is not plan):
            raise ValueError('Backend-retained restoration plan required')

    def attempted(self, plan):
        with self._lock:
            self._require_plan(plan)
            return plan.operation_id in self._attempts

    def execute(self, plan, desired, *, credential=None):
        with self._lock:
            self._require_plan(plan)
            request = self._request(plan, desired, credential=credential)
            if self.digest(request) != plan.input_digest:
                raise ValueError('Restoration choice or credential changed')
            if plan.operation_id in self._attempts:
                return self.query(plan)
            with self.lease(plan.harness_id, plan.publication):
                return self._execute_once(plan, request)

    def _execute_once(self, plan, request):
        current = self.owners.readback(plan.before.target)
        channel = self._channel(current)
        if (channel is not self._channels[plan.operation_id] or current.owner is not plan.before.owner
            or current.busy is not False or current.native_generation != plan.expected_generation
            or configuration_digest(current.config_options) != plan.expected_config_digest):
            raise ValueError('Restoration before fence changed or busy')
        if self.verify(channel.harness_id) != plan.publication:
            raise ValueError('Restoration configuration publication changed')
        ticket = self.owners.begin_restoration(plan.before.target, operation_id=plan.operation_id)
        if (ticket.before.owner is not current.owner or ticket.before.target != plan.before.target
            or ticket.before.busy is not False or ticket.before.native_generation != plan.expected_generation
            or configuration_digest(ticket.before.config_options) != plan.expected_config_digest):
            raise ValueError('Restoration reservation fence changed')
        # The caller must have journalled the application attempt before
        # execute. Reserve locally before sending; no raw key/error text.
        self._attempts[plan.operation_id] = ProviderRestorationOutcome('unknown', ticket)
        try:
            channel._configuration_rpc(current.owner.native_session_id,
                '_ordessa/session/configuration/restore', request)
        except Exception:
            pass  # reply loss is not permission to send a second effect
        return self.query(plan)

    def credential_binding(self, snapshot, desired, *, credential=None):
        """Retained native route proof; model changes do not rewrite auth.

        A matching digest alone is insufficient: retained operation + native
        owner identity + independent current generation must all still agree.
        """
        with self._lock:
            try:
                current = self.owners.readback(snapshot.target)
                channel = self._channel(current)
                if current.owner is not snapshot.owner or current.native_generation != snapshot.native_generation:
                    return False
                auth = self._authentication_digest(desired, credential)
                for operation_id, outcome in self._attempts.items():
                    plan = self._plans[operation_id]
                    restored = outcome.restored
                    if (outcome.state != 'observed' or restored is None
                        or restored.snapshot.target != snapshot.target
                        or restored.snapshot.native_generation != snapshot.native_generation
                        or restored.snapshot.owner is not snapshot.owner
                        or plan.authentication_digest != auth or channel is not self._channels[operation_id]):
                        continue
                    owner, record = self.channels.query_native_operation(
                        snapshot.owner.connection_id, snapshot.owner.native_session_id, operation_id)
                    return (owner is snapshot.owner and isinstance(record, dict)
                        and record.get('operationId') == operation_id and record.get('state') == 'observed'
                        and record.get('sessionId') == snapshot.owner.native_session_id
                        and record.get('inputDigest') == plan.input_digest)
            except Exception:
                return False
            return False

    def query(self, plan):
        """Queries native operation evidence and fresh state, never effects."""
        with self._lock:
            self._require_plan(plan)
            outcome = self._attempts.get(plan.operation_id)
            if outcome is None:
                raise ValueError('Native restoration has not been attempted')
            code = 'RESTORE_EVIDENCE_UNAVAILABLE'
            try:
                channel = self._channel(plan.before)
                if channel is not self._channels[plan.operation_id]:
                    raise _EvidenceCode('RESTORE_CHANNEL_REPLACED')
                owner, record = self.channels.query_native_operation(
                    plan.before.owner.connection_id, plan.before.owner.native_session_id, plan.operation_id)
                if owner is not plan.before.owner:
                    raise _EvidenceCode('RESTORE_OWNER_CHANGED')
                if not isinstance(record, dict):
                    raise _EvidenceCode('RESTORE_OPERATION_RECORD_MISSING')
                if (record.get('operationId') != plan.operation_id
                    or record.get('sessionId') != owner.native_session_id
                    or record.get('inputDigest') != plan.input_digest):
                    raise _EvidenceCode('RESTORE_OPERATION_IDENTITY_MISMATCH')
                if record.get('state') != 'observed':
                    raise _EvidenceCode('RESTORE_OPERATION_NOT_OBSERVED')
                if outcome.state == 'observed' and outcome.restored is not None:
                    restored = outcome.restored
                    current = self.owners.readback(restored.snapshot.target)
                    if current.owner is not owner or current.native_generation != restored.snapshot.native_generation:
                        raise _EvidenceCode('RESTORE_RENEWED_OWNER_CHANGED_AGAIN')
                else:
                    restored = self.owners.complete_restoration(outcome.ticket)
                if restored.previous_target != plan.before.target:
                    raise _EvidenceCode('RESTORE_RENEWED_WRONG_CONVERSATION')
                if restored.snapshot.owner is not owner:
                    raise _EvidenceCode('RESTORE_RENEWED_OWNER_MISMATCH')
                if (restored.snapshot.target.session_id != plan.before.target.session_id
                    or restored.snapshot.target.server_id != plan.before.target.server_id
                    or restored.snapshot.target.channel_id != plan.before.target.channel_id):
                    raise _EvidenceCode('RESTORE_RENEWED_WRONG_CONVERSATION')
                if (restored.snapshot.native_generation == plan.expected_generation
                    or restored.snapshot.target.runtime_generation <= plan.before.target.runtime_generation):
                    raise _EvidenceCode('RESTORE_RENEWAL_NOT_EVIDENCED')
                outcome = ProviderRestorationOutcome('observed', outcome.ticket, restored)
                code = None
            except _EvidenceCode as exc:
                code = str(exc)
            except Exception:
                code = 'RESTORE_EVIDENCE_UNAVAILABLE'
            if code is not None:
                outcome = ProviderRestorationOutcome('unknown', outcome.ticket, reason=code)
            self._attempts[plan.operation_id] = outcome
            return outcome
