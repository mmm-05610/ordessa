"""Pi action executor over operation-bound native records, never plain ACKs.

This is a plugin-internal execution seam, not a permit issuer or product
composition. C4 must authorize and durably reserve before calling execute.
"""
from dataclasses import asdict
import hashlib
import json

from ordessa_harness_api import ApplicationTarget
from ordessa_harness.application.action_execution import ActionBatch
from ordessa_harness.application.operation_journal import NativeActivationReceipt
from .profile_owner import ProfileSessionOwner
from .registry import AcpChannelRegistry, NativeConfigurationUnavailable


ACTION_ID = 'acp.session.set-config-option'


def configuration_digest(options: list) -> str:
    # Native configOptions consist of finite JSON; canonical keys and array
    # order match Pi's native stableJSON. No secret/settings files are read.
    return hashlib.sha256(json.dumps(options, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class PiSessionActionExecutor:
    def __init__(self, registry: AcpChannelRegistry, owners: ProfileSessionOwner, *,
                 target: ApplicationTarget, expected_configuration_digest: str):
        if (not isinstance(target, ApplicationTarget)
            or not isinstance(expected_configuration_digest, str)
            or len(expected_configuration_digest) != 64
            or any(char not in '0123456789abcdef' for char in expected_configuration_digest)):
            raise ValueError('exact target and independent before digest required')
        self.registry, self.owners, self.target = registry, owners, target
        self.before_digest = expected_configuration_digest
        self.last_receipt = None

    def _snapshot(self, batch):
        if not isinstance(batch, ActionBatch) or batch.target != self.target or len(batch.invocations) != 1:
            raise ValueError('one exact Pi session action required')
        invocation = batch.invocations[0].intent
        payload = invocation.typed_payload
        if (invocation.action_id != ACTION_ID or invocation.schema_version != '1'
            or not isinstance(payload, dict) or set(payload) != {'configId', 'value'}
            or payload['configId'] not in {'model', 'thinkingLevel'}
            or type(payload['value']) is not str or not payload['value']):
            raise ValueError('unsupported native configuration action')
        snapshot = self.owners.readback(self.target)
        channel = self.registry.get(snapshot.owner.connection_id)
        if channel is None or channel.harness_id != 'pi':
            raise ValueError('Pi native owner required')
        if configuration_digest(snapshot.config_options) != self.before_digest:
            raise ValueError('native before configuration changed')
        options = [item for item in snapshot.config_options if item['id'] == payload['configId']]
        if (len(options) != 1 or options[0].get('type') != 'select'
            or not any(item.get('value') == payload['value'] for item in options[0].get('options', []))):
            raise ValueError('native option not exposed')
        return snapshot, channel, payload

    def preflight(self, batch: ActionBatch) -> None:
        self._snapshot(batch)

    def execute(self, operation_id: str, batch: ActionBatch) -> NativeActivationReceipt:
        snapshot, channel, payload = self._snapshot(batch)
        owner = snapshot.owner
        request = {'sessionId': owner.native_session_id, 'operationId': operation_id,
            'expectedGeneration': snapshot.native_generation,
            'expectedConfigDigest': self.before_digest, **payload,
            'actionManifest': json.loads(batch.manifest_json)}
        observed_owner, result = channel._configuration_rpc(owner.native_session_id,
            '_ordessa/session/configuration/apply', request)
        if (observed_owner is not owner or self.registry.get(owner.connection_id) is not channel
            or channel.ended or self.registry.native_session_observation(
                owner.connection_id, owner.native_session_id) is not owner):
            raise NativeConfigurationUnavailable('native action owner changed')
        # This record is issued by the native operation wrapper after actual
        # upstream execution and its own read. Ordinary ACP ACKs lack these
        # target/manifest/operation bindings and can never pass this seam.
        if (result.get('operationId') != operation_id or result.get('state') != 'observed'
            or result.get('generation') != snapshot.native_generation
            or result.get('target') != asdict(self.target)
            or result.get('manifestDigest') != batch.manifest_digest
            or result.get('beforeConfigDigest') != self.before_digest
            or result.get('configId') != payload['configId']
            or result.get('requestedValue') != payload['value']
            or result.get('observedValue') != payload['value']
            or not isinstance(result.get('after'), dict)
            or result['after'].get('generation') != snapshot.native_generation
            or result['after'].get('sessionId') != owner.native_session_id
            or result['after'].get('busy') is not False
            or configuration_digest(result['after'].get('configOptions', [])) != result.get('afterConfigDigest')
            or not isinstance(result.get('evidenceRef'), str)
            or not result['evidenceRef'].startswith('pi-native-operation:')):
            raise NativeConfigurationUnavailable('native action outcome lacks bound owner evidence')
        options = [item for item in result['after']['configOptions']
                   if isinstance(item, dict) and item.get('id') == payload['configId']]
        if len(options) != 1 or options[0].get('currentValue') != payload['value']:
            raise NativeConfigurationUnavailable('native operation record readback mismatch')
        receipt = NativeActivationReceipt(operation_id, self.target, batch.manifest_digest,
            owner.native_session_id, result['afterConfigDigest'], result['evidenceRef'])
        self.last_receipt = receipt
        return receipt
