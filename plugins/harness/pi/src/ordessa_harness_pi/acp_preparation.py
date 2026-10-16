"""Pinned Go Pi ACP access/launch metadata; common Unit owns lifecycle.

Pure preparation only. No discovery fallback, spawn, session/record authority,
credential lookup or claim that external MCP inherits environment isolation.
"""
import hashlib
from pathlib import Path

from ordessa_execution_agents.harness.transport import LaunchSpec
from ordessa_execution_agents.preparation import PreparedHarness, SessionBootstrap, ConfigurationResources
from ordessa_harness_pi.launch_validation import verified_executable, verified_unit_private_roots, PiChannelRefused


class PiAcpHarnessPreparation:
    harness_id = 'pi'

    def __init__(self, *, bridge_executable, bridge_sha256, pi_executable, session_id=None,
                 provider=None, model=None):
        self.bridge = verified_executable(bridge_executable)
        self.pi = verified_executable(pi_executable)
        if (not isinstance(bridge_sha256, str) or len(bridge_sha256) != 64
                or any(c not in '0123456789abcdef' for c in bridge_sha256)):
            raise PiChannelRefused('Go ACP bridge requires an exact reviewed artifact digest')
        self.bridge_sha256 = bridge_sha256
        if session_id is not None and (not isinstance(session_id, str) or not session_id.strip()):
            raise PiChannelRefused('Resume requires an explicit native ACP session identity')
        self.session_id = session_id
        # Startup routing is explicit, immutable and selected from the same
        # fixed Profile by the caller's materializer. Never infer a provider
        # from a model name or silently choose a paid/default model.
        if (provider is None) != (model is None):
            raise PiChannelRefused('Provider and model must be selected together')
        for value in (provider, model):
            if value is not None and (not isinstance(value, str) or not value or value.strip() != value
                                     or any(ord(c) < 32 or ord(c) == 127 for c in value)):
                raise PiChannelRefused('Invalid explicit Pi startup routing')
        if provider is not None and '/' in provider:
            raise PiChannelRefused('Pi provider must be an exact provider identity')
        self.provider, self.model = provider, model

    def prepare(self, private_root_facts):
        roots = verified_unit_private_roots(private_root_facts)
        if hashlib.sha256(Path(self.bridge).read_bytes()).hexdigest() != self.bridge_sha256:
            raise PiChannelRefused('Reviewed Go ACP bridge artifact changed')
        sessions = str(Path(roots['profile']) / 'sessions')
        argv = [self.bridge, '--adapter', 'pi', '--pi-bin', self.pi, '--pi-session-dir', sessions]
        if self.provider is not None:
            argv.extend(['--pi-provider', self.provider, '--pi-model', self.model])
        spec = LaunchSpec.build(argv, home=roots['home'], cwd=roots['cwd'],
            extra_env={'PI_CODING_AGENT_DIR': roots['profile'], 'TMPDIR': roots['tmp']})
        return PreparedHarness(self.harness_id, spec,
            SessionBootstrap('resume' if self.session_id else 'fresh', self.session_id or roots['cwd']),
            ConfigurationResources('pi-agent-dir', roots['profile'], False),
            {'identity':'pi','protocol':'acp/v1','bridgeArtifactSha256':self.bridge_sha256,
             'configurationReadMethod':'_ordessa/session/configuration',
             'capabilities':{'existingChannel':True,'externalMcpAutomaticallySandboxed':False}})
