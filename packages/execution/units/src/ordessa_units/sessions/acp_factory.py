"""Environment-owned process and same-stream ACP, consumed by UnitLifecycle."""
from dataclasses import dataclass, replace
import os
import asyncio

from ordessa_environments import ProcessRequest, require_guarantees, PROCESS_CAPABILITY, BYTE_CHANNEL_CAPABILITY, FILE_AREA_CAPABILITY
from ordessa_execution_agents.preparation import PreparedAgent, PreparedHarness, ConfigurationResources
from .sdk_client import SdkAcpClient
from ordessa_execution_agents.harness.transport import ProcessChannel
from ordessa_units.lifecycle.unit_lifecycle import UnitLifecycleRefused, same_reference


@dataclass(frozen=True)
class AcpChannelRecord:
    entry: object
    channel: object
    process: object
    prepared_agent: PreparedAgent
    environment_identity: str
    environment_use_identity: str


class AcpChannelFactory:
    def __init__(self, *, environment_instance, environment_sharing, environment_reference, preparation,
                 materializer, agent_id, profile_revision, session_id, timeout, effect_write_guard_required=False,
                 effect_write_owner=None):
        if not callable(getattr(preparation, 'prepare', None)):
            raise UnitLifecycleRefused('Explicit Harness preparation port required')
        self.instance = environment_instance
        if type(environment_sharing) is not bool:
            raise UnitLifecycleRefused("Environment sharing requires an explicit boolean")
        self.sharing = environment_sharing
        self.reference = environment_reference
        self.preparation, self.materializer = preparation, materializer
        self.agent_id, self.profile_revision = agent_id, profile_revision
        self.session_id, self.timeout = session_id, timeout
        if type(effect_write_guard_required) is not bool:
            raise UnitLifecycleRefused('Explicit operation write guard selection required')
        if effect_write_guard_required and effect_write_owner is None:
            raise UnitLifecycleRefused('Original recorded prompt owner required')
        self.effect_write_guard_required = effect_write_guard_required
        self._effect_write_owner = effect_write_owner
        self.environment = None
        self.prepared_agent = None
        self._record = None
        self._roots = None
        self.client_capabilities = {}

    def prepare(self, roots, facts, snapshot):
        if self.prepared_agent is not None:
            if not same_reference(roots, self._roots):
                raise UnitLifecycleRefused('Unit roots changed after fixed preparation')
            return self.prepared_agent
        if facts.get('action') != 'prepare' or facts.get('query') is not False:
            raise UnitLifecycleRefused('Environment acquisition requires verified prepare effect')
        if self.reference.get("environmentId") != self.instance.identity:
            raise UnitLifecycleRefused("Fixed Environment instance identity differs")
        self.environment = self.instance.acquire(self.agent_id, sharing=self.sharing)
        require_guarantees(self.environment, [PROCESS_CAPABILITY, BYTE_CHANNEL_CAPABILITY, FILE_AREA_CAPABILITY])
        harness = self.preparation.prepare(roots)
        if type(harness) is not PreparedHarness:
            raise UnitLifecycleRefused('Harness did not return a fixed preparation')
        if harness.descriptor.get('protocol') != 'acp/v1':
            raise UnitLifecycleRefused('Unit supports only explicitly declared ACP preparation')
        if (harness.session.mode == 'none'
                or harness.session.mode == 'resume' and not self.session_id
                or harness.session.mode == 'fresh' and self.session_id is not None):
            raise UnitLifecycleRefused('Declared session bootstrap is unavailable or differs from fixed Run')
        agent = PreparedAgent(self.agent_id, self.profile_revision, harness)
        spec = harness.launch_spec
        # Validate/provision only launch directories before materialization.
        # Resource location may be a file or directory, owned by its explicit
        # materializer; never invent its format by making it a directory.
        self.environment.files.path(os.path.relpath(harness.resources.location, self.environment.files.root()))
        for path in [spec.cwd, *[spec.env.get(k) for k in
                     ('HOME','TMPDIR','XDG_CONFIG_HOME','XDG_CACHE_HOME','XDG_DATA_HOME','XDG_STATE_HOME')]]:
            if path:
                self.environment.files.ensure(os.path.relpath(path, self.environment.files.root()))
        if not harness.resources.applied:
            if not callable(self.materializer):
                raise UnitLifecycleRefused('Required profile materialization unavailable')
            resources = self.materializer(agent, self.environment, facts, snapshot)
            if (type(resources) is not ConfigurationResources or not resources.applied
                    or resources.kind != harness.resources.kind or resources.location != harness.resources.location):
                raise UnitLifecycleRefused('Profile materialization did not produce owner-confirmed resources')
            harness = replace(harness, resources=resources)
            agent = replace(agent, harness=harness)
        # Launch identity directories are provisioned through the bound file
        # area; including TMPDIR ensures the Pi permission gate can materialize.
        self._roots = dict(roots)
        self.prepared_agent = agent
        return agent

    def open(self, roots, facts):
        if (self.prepared_agent is None or not same_reference(roots, self._roots)
                or facts.get('action') != 'start' or facts.get('query') is not False or self._record is not None):
            raise UnitLifecycleRefused('Fixed preparation/start authority unavailable or already dispatched')
        spec = self.prepared_agent.harness.launch_spec
        process = self.environment.execution.start(ProcessRequest.build(spec.argv, cwd=spec.cwd, env=spec.env))
        self._record = AcpChannelRecord(object(), None, process, self.prepared_agent, self.environment.environment_id, self.environment.identity)
        channel = ProcessChannel.attach(process, name='unit-acp', managed=True)
        self._record = replace(self._record, channel=channel)
        entry = SdkAcpClient(channel.bind_writer(channel.acquire_writer()), name='unit-acp', connect=False,
            require_effect_write_guard=self.effect_write_guard_required,
            effect_write_owner=self._effect_write_owner)
        self._record = replace(self._record, entry=entry)
        entry.open_connection()
        return entry

    @property
    def owned_record(self):
        return self._record

    def record(self, entry):
        if self._record is None or self._record.entry is not entry:
            raise UnitLifecycleRefused('Foreign Unit channel')
        return self._record

    def handshake(self, entry, *, before_effect):
        result = entry.initialize(timeout=self.timeout, before_write=lambda payload: before_effect(),
                                  **self.client_capabilities)
        if result.get('protocolVersion') != 1:
            raise UnitLifecycleRefused('ACP v1 negotiation unavailable')
        return result

    def establish_session(self, entry, handshake, *, before_effect):
        before_effect()  # ACP new/load is a separate native effect after initialize
        params = {'cwd':self.prepared_agent.harness.launch_spec.cwd, 'mcpServers':[]}
        if self.session_id is None:
            return entry.new_session(timeout=self.timeout, before_write=lambda payload: before_effect(), **params)
        entry.load_session(timeout=self.timeout, before_write=lambda payload: before_effect(),
                           sessionId=self.session_id, **params)
        return {'sessionId':entry.session_id}

    def verify_session(self, entry, state):
        record = self.record(entry)
        if record.process.observe().state != "running" or entry.session_id != state.get('sessionId'):
            raise UnitLifecycleRefused('Original ACP session or owned process unavailable')
        return state

    @staticmethod
    def is_running(record):
        return record.process.observe().state == "running"

    @staticmethod
    def termination_facts(record, code):
        observation = record.process.observe()
        if code is None or observation.state != "exited" or observation.exit_code != code:
            raise UnitLifecycleRefused('Owned process exit not confirmed')
        return {'processIdentity':record.process.identity, 'exitCode':str(int(code))}

    def close(self, entry):
        record = self.record(entry)
        if record.channel is None:
            # No SDK loop was created when attach failed. There has been no IO
            # binding, so cleanup uses one temporary loop over the same owner.
            async def cleanup():
                await record.process.cancel()
                return (await record.process.wait_exit(timeout=self.timeout)).exit_code
            return asyncio.run(cleanup())
        try:
            if type(entry) is SdkAcpClient and entry.has_io_loop:
                return entry.run_process_operation(record.channel.close_async(timeout=self.timeout), timeout=3*self.timeout+5)
            # Attachment/client construction failed before a live IO loop.
            # Retain the exact original channel/handle; never launch another.
            return asyncio.run(record.channel.close_async(timeout=self.timeout))
        finally:
            record.channel.fence_all()

    def release(self, entry):
        record = self.record(entry)
        facts = self.termination_facts(record, record.process.observe().exit_code)
        record.process.release()
        if hasattr(entry, 'detach'):
            entry.detach()
        return facts

    def release_environment(self):
        if self.environment is not None:
            self.environment.release()
