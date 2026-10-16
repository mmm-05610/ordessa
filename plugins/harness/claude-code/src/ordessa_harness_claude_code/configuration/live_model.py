"""Pinned brand route facts for pure owner-observed model compilation."""
from ordessa_execution_agents.harness.configuration.compilation.native_compile import NativeModelRoute, compile_observed_model

_ROUTE = NativeModelRoute('claude-code', ('main','anthropic','anthropic-messages'))

def compile_live_model(snapshot, desired, source, *, credential_binding=None):
    return compile_observed_model(snapshot, desired, source, _ROUTE,
                                  credential_binding=credential_binding)
