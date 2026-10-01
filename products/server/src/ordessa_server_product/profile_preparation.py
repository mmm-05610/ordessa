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
    def __init__(self, core, channels, *, roots, verify, resolver_factory, catalog_factory, realm='local', managed_account_factory=None):
        self.core, self.channels, self.roots = core, channels, dict(roots)
        self.verify, self.resolver_factory, self.catalog_factory, self.realm = verify, resolver_factory, catalog_factory, realm
        self._operations, self._connections = {}, {}
        self._lock = RLock()
        self.managed_account_factory = managed_account_factory

    def resolve_launch_selection(self, *, profile_id, harness_id):
        """Read-only selection before launch, without exporting credential bytes."""
        profile = self.core.profiles.get(profile_id)
        if (profile['realm'] != self.realm or profile['harness_id'] != harness_id
                or profile['archived_at'] is not None or harness_id not in self.roots):
            raise ProfileError('APPLICATION_PORT_ABSENT', 'Matching active Profile and installed Harness required', status=409)
        self.verify(harness_id)
        rows = self.core.profiles.facet_values(profile_id, config_revision=profile['current_revision'])
        choices = [r for r in rows if (r['facet_id'], r['item_id']) == ('assets.model-provider', 'choice')]
        if len(choices) != 1 or choices[0]['quarantined']:
            raise ProfileError('PROFILE_CONFIGURATION_INVALID', 'One current model choice required', status=422)
        resolved = self.resolver_factory().resolve(choices[0]['value'], harness_id=harness_id)
        transport_options = {}
        if resolved.payload.get('authentication') == 'managed-account':
            # Harness validates the dialect; the resource record contains no
            # token, account directory or invented native endpoint.
            initial_model_params(harness_id, resolved.payload, 'create:launch-check')
            if not callable(self.managed_account_factory):
                raise ProfileError('APPLICATION_PORT_ABSENT', 'Managed account launch unavailable', status=409)
            account = self.managed_account_factory(harness_id)
            if account.read(refresh=True) != {'authenticated': True, 'method': 'chatgpt-managed'}:
                raise ProfileError('AUTHENTICATION_REQUIRED', 'Ordessa Codex login required', status=409)
            transport_options['codex_account_directory'] = account.account_directory
        if self.core.profiles.get(profile_id) != profile:
            raise ProfileError('SWITCH_BLOCKED', 'Profile changed during launch selection', status=409)
        return {'snapshot': {'profileId': profile_id, 'profileVersion': profile['version'],
                            'profileRevision': profile['current_revision'], 'payloadDigest': _digest(resolved.payload),
                            'catalogDigest': _digest(resolved.revisions)},
                'transportOptions': transport_options}

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
        if getattr(channel, 'configuration_profile_id', None) is not None:
            expected = {'profileId': profile_id, 'profileVersion': profile['version'],
                        'profileRevision': profile['current_revision'], 'payloadDigest': _digest(resolved.payload),
                        'catalogDigest': _digest(resolved.revisions)}
            if (channel.configuration_profile_id != profile_id
                    or getattr(channel, 'configuration_profile_snapshot', None) != expected):
                raise ValueError('Profile launch selection changed before native creation')
        catalog = self.catalog_factory()
        credential = catalog.application_credential(resolved.payload.get('credentialRef'), harness_id=channel.harness_id)
        model_ids = None
        if channel.harness_id == 'pi' and credential is not None:
            # The current resource catalogue supplies neutral identities. Only
            # Harness translates these into Pi's in-memory provider dialect.
            row = catalog.records.get(resolved.revisions['providerConfigId'])
            projection = catalog.project(row)
            model_ids = [m['modelId'] for m in projection['models']
                if m.get('availability') == 'available'
                and (m.get('protocols') is None or resolved.payload['protocol'] in m['protocols'])]
            if (row['version'] != resolved.revisions['configVersion']
                    or row['models_object_digest'] != resolved.revisions['modelsObjectDigest']
                    or catalog.records.get(row['id']) != row):
                raise ValueError('Pi model catalogue changed during preparation')
        signature = (profile_id, profile['version'], profile['current_revision'],
                     _digest(resolved.payload), _digest(resolved.revisions),
                     _digest(model_ids),
                     hashlib.sha256(credential.encode()).hexdigest() if credential is not None else None)
        if self.core.profiles.get(profile_id) != profile or self.channels.get(connection_id) is not channel:
            raise ValueError('Profile or channel changed during preparation')
        return channel, profile, resolved, credential, signature, model_ids

    def prepare(self, *, connection_id, profile_id, operation_id):
        with self._lock:
            try:
                if (type(operation_id) is not str or not operation_id.startswith('create:')
                        or len(operation_id) <= 7 or len(operation_id) > 128
                        or operation_id.strip() != operation_id or any(ord(c) < 32 or ord(c) == 127 for c in operation_id)):
                    raise ValueError('Bounded creation operation required')
                channel, profile, resolved, credential, signature, model_ids = self._resolve(connection_id, profile_id)
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
                    params = None if channel.harness_id == 'pi' and credential is None else initial_model_params(
                        channel.harness_id, resolved.payload, operation_id, credential=credential, models=model_ids)
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
                    return desired.get('credentialRef') is None and desired.get('authentication') is None
                operation_id = self._connections[cid]
                saved = self._operations[operation_id]
                channel = initial_channel(self.channels, cid, empty=False)
                if saved['channel'] is not channel or channel.harness_id not in self.roots:
                    return False
                self.verify(channel.harness_id)
                # C4 independently resolves the current selected Profile/model
                # and fences its revisions. This proof covers unchanged auth,
                # allowing another model or Profile on the same native route.
                auth_keys = ('provider', 'protocol', 'endpoint', 'credentialRef', 'authentication')
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
