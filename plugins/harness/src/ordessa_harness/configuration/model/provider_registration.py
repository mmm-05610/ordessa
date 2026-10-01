"""Pi live admission; never creates a restoration ticket or changes a fence."""
from dataclasses import asdict
from types import SimpleNamespace

from ...server_acp.native_action_executor import configuration_digest
from .initial import initial_model_params
from .restoration import ProviderRestorationService, ProviderRestorationOutcome


class PiProviderRegistrationService(ProviderRestorationService):
    operation_prefix = 'provider:'
    mode = 'live-update'

    def _channel(self, snapshot):
        owner = snapshot.owner
        channel = self.channels.get(owner.connection_id)
        if (channel is None or channel.ended is not False or channel.harness_id != 'pi'
            or snapshot.target.channel_id != owner.connection_id
            or self.channels.native_session_observation(owner.connection_id, owner.native_session_id) is not owner):
            raise ValueError('Current dedicated Pi owner required')
        return channel

    def prepare(self, target, desired, *, operation_key, credential=None):
        # Old installed assets fail closed at a read-only feature query, before
        # plans or effects. Installation trust alone does not prove capability.
        before = self.owners.readback(target)
        channel = self._channel(before)
        self.verify('pi')
        owner, capability = channel._configuration_rpc(before.owner.native_session_id,
            '_ordessa/session/configuration/provider-capability', {'sessionId': before.owner.native_session_id})
        if owner is not before.owner or capability != {'supported': True, 'strategy': 'live-registration', 'version': 1}:
            raise ValueError('Verified Pi live registration unavailable')
        return super().prepare(target, desired, operation_key=operation_key, credential=credential)

    def _request(self, plan, desired, *, credential=None):
        if self._channels[plan.operation_id].harness_id != 'pi':
            raise ValueError('Pi provider route changed')
        params = initial_model_params('pi', desired, plan.operation_id,
            credential=credential, models=[desired.get('model')])
        return dict(params, sessionId=plan.before.owner.native_session_id,
            expectedGeneration=plan.expected_generation, expectedConfigDigest=plan.expected_config_digest,
            target=asdict(plan.before.target))

    def _execute_once(self, plan, request):
        current = self.owners.readback(plan.before.target)
        channel = self._channel(current)
        if (channel is not self._channels[plan.operation_id] or current.owner is not plan.before.owner
            or current.busy is not False or current.native_generation != plan.expected_generation
            or configuration_digest(current.config_options) != plan.expected_config_digest
            or self.verify('pi') != plan.publication):
            raise ValueError('Pi provider before fence changed or busy')
        self._attempts[plan.operation_id] = ProviderRestorationOutcome('unknown', None)
        try:
            channel._configuration_rpc(current.owner.native_session_id,
                '_ordessa/session/configuration/provider-register', request)
        except Exception:
            pass  # Only independent queries can settle a lost reply.
        return self.query(plan)

    def query(self, plan):
        with self._lock:
            self._require_plan(plan)
            if plan.operation_id not in self._attempts:
                raise ValueError('Pi provider registration not attempted')
            outcome = ProviderRestorationOutcome('unknown', None)
            try:
                current = self.owners.readback(plan.before.target)
                channel = self._channel(current)
                owner, record = self.channels.query_native_operation(
                    current.owner.connection_id, current.owner.native_session_id, plan.operation_id)
                if (channel is not self._channels[plan.operation_id] or owner is not plan.before.owner
                    or current.owner is not owner or current.target != plan.before.target
                    or current.native_generation != plan.expected_generation or current.busy is not False
                    or not isinstance(record, dict) or record.get('state') != 'observed'
                    or record.get('kind') != 'provider-registration'
                    or record.get('operationId') != plan.operation_id
                    or record.get('sessionId') != owner.native_session_id
                    or record.get('target') != asdict(plan.before.target)
                    or record.get('inputDigest') != plan.input_digest
                    or record.get('after', {}).get('generation') != current.native_generation
                    or configuration_digest(record['after']['configOptions']) != configuration_digest(current.config_options)):
                    raise ValueError('Pi operation-bound live registration unproven')
                outcome = ProviderRestorationOutcome('observed', None,
                    SimpleNamespace(previous_target=plan.before.target, snapshot=current))
            except Exception:
                pass
            self._attempts[plan.operation_id] = outcome
            return outcome

    def credential_binding(self, snapshot, desired, *, credential=None):
        with self._lock:
            auth = self._authentication_digest(desired, credential)
            for operation_id, plan in self._plans.items():
                if (plan.before.target != snapshot.target or plan.before.owner is not snapshot.owner
                    or plan.authentication_digest != auth or operation_id not in self._attempts):
                    continue
                # C4 may have selected the admitted model since registration;
                # authenticate the retained admission + current exact route,
                # not equality of the old catalogue/selection digest.
                try:
                    current = self.owners.readback(snapshot.target)
                    channel = self._channel(current)
                    owner, record = self.channels.query_native_operation(
                        current.owner.connection_id, current.owner.native_session_id, operation_id)
                    routes = [option.get('_meta', {}).get('ordessaModel')
                        for selector in current.config_options if selector.get('id') == 'model'
                        for option in selector.get('options', [])]
                    matching = [route for route in routes if isinstance(route, dict)
                        and route.get('provider') == desired.get('provider') and route.get('model') == desired.get('model')
                        and route.get('api') == 'openai-completions' and route.get('baseUrl') == desired.get('endpoint')]
                    if (current.owner is snapshot.owner and owner is snapshot.owner
                        and current.native_generation == snapshot.native_generation == plan.expected_generation
                        and channel is self._channels[operation_id] and len(matching) == 1
                        and isinstance(record, dict) and record.get('state') == 'observed'
                        and record.get('kind') == 'provider-registration' and record.get('operationId') == operation_id
                        and record.get('sessionId') == owner.native_session_id and record.get('inputDigest') == plan.input_digest
                        and record.get('target') == asdict(snapshot.target)):
                        return True
                except Exception:
                    continue
            return False


class ProviderTransitionService:
    """Brand-neutral consumer interface; native strategy selection stays here."""
    def __init__(self, channels, owners, **kwargs):
        self.channels, self.owners = channels, owners
        self.live = PiProviderRegistrationService(channels, owners, **kwargs)
        self.restart = ProviderRestorationService(channels, owners, **kwargs)

    def _service(self, plan):
        return self.live if plan.mode == 'live-update' else self.restart

    def prepare(self, target, desired, **kwargs):
        snapshot = self.owners.readback(target)
        channel = self.channels.get(snapshot.owner.connection_id)
        service = self.live if channel is not None and channel.harness_id == 'pi' else self.restart
        return service.prepare(target, desired, **kwargs)

    def execute(self, plan, desired, **kwargs):
        return self._service(plan).execute(plan, desired, **kwargs)

    def query(self, plan):
        return self._service(plan).query(plan)

    def attempted(self, plan):
        return self._service(plan).attempted(plan)

    def credential_binding(self, snapshot, desired, **kwargs):
        return (self.live.credential_binding(snapshot, desired, **kwargs)
                or self.restart.credential_binding(snapshot, desired, **kwargs))
