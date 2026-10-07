from .generic.factory import build_registration, descriptor
from pacthold.extensions import PluginContext
class _Plugin:
    def __init__(self,harness_type=None): self.harness_type=harness_type
    def descriptor(self): return descriptor(self.harness_type)
    def build(self,context:PluginContext): return build_registration(context,self.harness_type)
def create_profile_store(): return _Plugin()
def create_codex(): return _Plugin("codex")
def create_claude(): return _Plugin("claude-code")
def create_opencode(): return _Plugin("opencode")
def create_hermes(): return _Plugin("hermes")
def create_pi(): return _Plugin("pi")
