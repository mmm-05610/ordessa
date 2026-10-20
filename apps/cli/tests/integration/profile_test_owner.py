"""Explicit controlled Profile owner for product assertion migration.

No kernel/Unit authority is constructed or borrowed. This fixture verifies one
pinned test harness definition; it is not production HarnessCatalog admission.
"""
from threading import RLock
from types import SimpleNamespace
from ordessa_execution_agents.profiles import ProfileService,SqliteProfileStore,ProfileValidationError
from ordessa_infrastructure.security.fingerprints import HmacKeyRing
from ordessa_infrastructure.encoding import canonical_bytes


class Fingerprint:
    def __init__(self):self._ring=HmacKeyRing({'fixture':b'controlled-product-profile-test'},active_key_id='fixture')
    def describe(self):return self._ring.describe(comparison_scope='profile:test')
    def fingerprint(self,request,surface,digest):
        return self._ring.sign(canonical_bytes([request.environment_namespace,request.principal_scope,request.request_id,surface,digest]))


class Admission:
    def __init__(self,namespace,principal,policy):
        self.namespace=namespace;self.principal_scope=principal;self.policy=policy
        self.admission_lock=RLock();self.fingerprint_port=Fingerprint();self.closed=False
    def check_open(self):
        if self.closed:raise ProfileValidationError('controlled Profile owner closed')
    def check_namespace(self,namespace):
        if namespace!=self.namespace:raise ProfileValidationError('foreign namespace')


class PinnedValidator:
    def __init__(self,definition_ref):self._definition=dict(definition_ref)
    def validate_profile(self,content):
        if dict(content.harness_definition_ref)!=self._definition or content.declarations:
            raise ProfileValidationError('only the pinned empty controlled harness profile is supported')


def profile_owner(path,namespace,principal,policy,definition_ref,*,validator=None):
    store=SqliteProfileStore(path);admission=Admission(namespace,principal,policy)
    service=ProfileService(store,admission,PinnedValidator(definition_ref) if validator is None else validator)
    def close():admission.closed=True;store.close()
    return SimpleNamespace(service=service,close=close)
