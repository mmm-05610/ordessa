"""Controlled external admission for the explicit Profile-owned store tests.

No Unit/environment owner or production grant is constructed by this fixture.
"""
from threading import RLock
from ordessa_infrastructure.security.fingerprints import HmacKeyRing
from ordessa_agents.profiles.definitions.errors import ProfileValidationError
from ordessa_agents.profiles.definitions.validation import canonical

class Fingerprint:
    def __init__(self):self.ring=HmacKeyRing({'fixture':b'controlled-profile-test-key'},active_key_id='fixture')
    def describe(self):return self.ring.describe(comparison_scope='profile:test')
    def fingerprint(self,request,surface,digest):
        return self.ring.sign(canonical([request.environment_namespace,request.principal_scope,request.request_id,surface,digest]).encode())

class Admission:
    def __init__(self,policy,namespace):
        self.namespace=namespace;self.principal_scope='fixture-principal';self.policy=policy
        self.admission_lock=RLock();self.fingerprint_port=Fingerprint();self.closed=False
    def check_open(self):
        if self.closed:raise ProfileValidationError('closed external admission')
    def check_namespace(self,namespace):
        if namespace!=self.namespace:raise ProfileValidationError('foreign namespace')

class Validator:
    def __init__(self):self.contents=[];self.refuse=False
    def validate_profile(self,content):
        self.contents.append(content)
        if self.refuse:raise ProfileValidationError('controlled harness refusal')
