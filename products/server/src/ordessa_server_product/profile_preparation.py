"""Bounded backend startup reservations, independent of Profile C4 receipts."""
import hashlib
import json
from copy import deepcopy
from threading import RLock

from ordessa_profile.errors import ProfileError
from ordessa_server.errors import ServerError
from ordessa_harness.configuration.model.initial import initial_channel, initial_model_params


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class NativeProfilePreparation:
    def __init__(self, core, channels, *, roots, verify, resolver_factory, catalog_factory, realm='local'):
        self.core, self.channels, self.roots = core, channels, dict(roots)
        self.verify, self.resolver_factory, self.catalog_factory, self.realm = verify, resolver_factory, catalog_factory, realm
        self._operations, self._connections = {}, {}
        self._lock = RLock()

    def _resolve(self, connection_id, profile_id):
        channel = initial_channel(self.channels, connection_id, empty=False)
        profile = self.core.profiles.get(profile_id)
        if (profile['realm'] != self.realm or profile['harness_id'] != channel.harness_id
                or profile['archived_at'] is not None):
            raise ValueError('Active matching local Profile required')
        if channel.harness_id not in self.roots:
            raise ValueError('Trusted enhanced installation required')
        self.verify(channel.harness_id)
        rows = self.core.profiles.facet_values(profile_id, config_revision=profile['current_revision'])
        choices = [r for r in rows if (r['facet_id'], r['item_id']) == ('assets.model-provider', 'choice')]
        if len(choices) != 1 or choices[0]['quarantined']:
            raise ValueError('One current nonquarantined model choice required')
        resolved = self.resolver_factory().resolve(choices[0]['value'], harness_id=channel.harness_id)
        credential = self.catalog_factory().application_credential(resolved.payload.get('credentialRef'), harness_id=channel.harness_id)
        signature = (profile_id, profile['version'], profile['current_revision'],
                     _digest(resolved.payload), _digest(resolved.revisions),
                     hashlib.sha256(credential.encode()).hexdigest() if credential is not None else None)
        if self.core.profiles.get(profile_id) != profile or self.channels.get(connection_id) is not channel:
            raise ValueError('Profile or channel changed during preparation')
        return channel, profile, resolved, credential, signature

    def prepare(self, *, connection_id, profile_id, operation_id):
        with self._lock:
            try:
                if (type(operation_id) is not str or not operation_id.startswith('create:')
                        or len(operation_id) <= 7 or len(operation_id) > 128
                        or operation_id.strip() != operation_id or any(ord(c) < 32 or ord(c) == 127 for c in operation_id)):
                    raise ValueError('Bounded creation operation required')
                channel, profile, resolved, credential, signature = self._resolve(connection_id, profile_id)
                if operation_id != 'create:' + channel.session_scope_id:
                    raise ValueError('Operation does not match initial channel scope')
                saved = self._operations.get(operation_id)
                if saved is not None:
                    if saved['channel'] is not channel or saved['signature'] != signature:
                        raise ValueError('Preparation identity or revisions changed')
                elif connection_id in self._connections or len(self._operations) >= 4096:
                    raise ValueError('Initial channel already reserved or capacity exhausted')
                else:
                    initial_channel(self.channels, connection_id)
                    params = None if channel.harness_id == 'pi' else initial_model_params(
                        channel.harness_id, resolved.payload, operation_id, credential=credential)
                    saved = {'channel': channel, 'signature': signature, 'payload': deepcopy(resolved.payload),
                             'input_digest': _digest(params) if params is not None else None,
                             'state': 'not-required' if params is None else 'unknown'}
                    # Reserve both identities BEFORE any provider effect; store no secret.
                    self._operations[operation_id] = saved
                    self._connections[connection_id] = operation_id
                    if params is not None:
                        try:
                            record = self.channels.prepare_native_creation(connection_id, params)
                            saved['state'] = self._state(record, operation_id, saved)
                        except Exception:
                            saved['state'] = 'unknown'
                    return self._projection(saved, operation_id, connection_id, profile, profile_id)
                if saved['state'] != 'not-required':
                    try:
                        saved['state'] = self._state(self.channels.query_native_creation(connection_id, operation_id), operation_id, saved)
                    except Exception:
                        saved['state'] = 'unknown'
                return self._projection(saved, operation_id, connection_id, profile, profile_id)
            except ProfileError:
                raise
            except ServerError as exc:
                raise ProfileError(exc.code, 'Native Profile model or credential cannot be resolved', status=409) from None
            except Exception:
                raise ProfileError('SWITCH_BLOCKED', 'Native Profile preparation unavailable or changed', status=409) from None

    @staticmethod
    def _state(record, operation_id, saved):
        if not isinstance(record, dict) or record.get('operationId') != operation_id or record.get('inputDigest') != saved['input_digest']:
            return 'unknown'
        return 'prepared' if record.get('state') in ('prepared', 'observed') else 'unknown'

    @staticmethod
    def _projection(saved, operation_id, connection_id, profile, profile_id):
        return {'state': saved['state'], 'operation_id': operation_id, 'connection_id': connection_id,
                'profile_id': profile_id, 'harness_id': profile['harness_id'], 'profile_revision': profile['current_revision']}

    def credential_binding(self, snapshot, desired):
        """Private C4 proof: same credential/config, retained operation and owner.

        No credential is removed from desired. Startup ACK alone is insufficient:
        the retained operation must independently observe this native generation.
        """
        with self._lock:
            try:
                cid = snapshot.owner.connection_id
                if cid not in self._connections:
                    # Preserve the existing model-only C4 route; new credential
                    # references always need startup evidence. A channel with a
                    # reservation can never use this absence rule.
                    return desired.get('credentialRef') is None
                operation_id = self._connections[cid]
                saved = self._operations[operation_id]
                channel = initial_channel(self.channels, cid, empty=False)
                if saved['channel'] is not channel or channel.harness_id not in self.roots:
                    return False
                self.verify(channel.harness_id)
                # C4 independently resolves the current selected Profile/model
                # and fences its revisions. This proof covers unchanged auth,
                # allowing another model or Profile on the same native route.
                auth_keys = ('provider', 'protocol', 'endpoint', 'credentialRef')
                if any(desired.get(key) != saved['payload'].get(key) for key in auth_keys):
                    return False
                credential = self.catalog_factory().application_credential(desired.get('credentialRef'), harness_id=channel.harness_id)
                fingerprint = hashlib.sha256(credential.encode()).hexdigest() if credential is not None else None
                if fingerprint != saved['signature'][-1]:
                    return False
                record = self.channels.query_native_creation(cid, operation_id)
                after = record.get('after')
                return (self._state(record, operation_id, saved) == 'prepared' and record.get('state') == 'observed'
                    and isinstance(after, dict) and after.get('sessionId') == snapshot.owner.native_session_id
                    and after.get('generation') == snapshot.native_generation
                    and self.channels.native_session_observation(cid, snapshot.owner.native_session_id) is snapshot.owner)
            except Exception:
                return False
