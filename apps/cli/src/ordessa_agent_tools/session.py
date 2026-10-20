"""One foreground session: one loop, one owner set, real retained handles.

The session owns no business state. Commands go through the same generic
channel and the same capability handlers as one-shot usage; the difference is
only that the process (and therefore the original Use/process handles) stays
alive. Ctrl+C cancels the current command task, never the remote operation:
an interrupted effect keeps its original unknown/retained facts.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import uuid

from ordessa_interfaces.channels import cli as channel
from ordessa_interfaces.system_access import CapabilityHost, build_registry

from .composition.agents import PromptWriteGuard, build_agent_domain
from .composition.decisions import build_decision_domain
from .composition.environments import build_environment_domain
from .composition.state import LocalState

_SHELL_TOKENS = {'|', '&', ';', '>', '<', '>>', '<<', '||', '&&'}


class Session:
    def __init__(self, state: LocalState):
        self.state = state
        # A failed construction closes every already-built owner in reverse order:
        # the foreground session never leaves an authority, SQLite handle or
        # provider client behind just because a later domain refused.
        built = []
        try:
            self.environment = build_environment_domain(state, session=True)
            built.append(self.environment)
            self.agents = build_agent_domain(state, session=True, environment=self.environment)
            built.append(self.agents)
            self.decisions = build_decision_domain(state)
            built.append(self.decisions)
        except BaseException:
            for domain in reversed(built):
                try:
                    domain.close()
                except Exception:
                    pass
            raise
        capabilities = [self.environment.capability, *self.agents.capabilities,
                        self.decisions.capability]
        self.capabilities = capabilities
        self.host = CapabilityHost(build_registry(capabilities),
                                   tuple(item.descriptor.id for item in capabilities))
        self.metadata = [registered.descriptor
                         for registered in self.host.registry.operations.values()]
        self.authority = self.environment.authority
        self._command = None

    def close(self):
        try:
            self.agents.close()
        finally:
            self.decisions.close()
            self.environment.close()

    def facts(self) -> dict:
        environment = self.environment.services.session_facts()
        starts = self.agents.records.session_starts()
        active_uses = [use for use in environment['uses'] if use['phase'] != 'released']
        return {'agents': starts, 'uses': active_uses,
                'liveUseHandles': environment['liveUseHandles'],
                'processes': environment['processes']}

    def retained(self, facts) -> bool:
        return bool(facts['agents'] or facts['uses'] or facts['liveUseHandles']
                    or facts['processes'])

    def report(self, facts, stream):
        if not self.retained(facts):
            stream.write('nothing retained\n')
            return
        stream.write('retained work:\n')
        for start in facts['agents']:
            stream.write(f"  agent {start['requestId']} {start['status']} "
                         f"{start['receipt'].get('instanceRef')}\n")
        for use in facts['uses']:
            stream.write(f"  use {use['useIdentity']} phase={use['phase']} "
                         f"pending={use['pendingEffects']}\n")
        for process in facts['processes']:
            stream.write(f"  process {process['processIdentity']} (use {process['useIdentity']})\n")


class Interrupt:
    """Ctrl+C policy for one foreground session.

    The first interrupt during an active ``agents prompt`` sends the provider's
    native cancel notification and leaves the original call running: a cancel
    request is not an outcome, and the original result must not be rewritten as
    cancelled. A second interrupt stops waiting locally and keeps whatever
    unknown/retained facts the original call recorded.
    """

    def __init__(self, session, stderr):
        self.session = session
        self.stderr = stderr
        self.task = None
        self.instance_argument = None
        self.native_attempted = False

    def bind(self, words):
        self.instance_argument = _prompt_instance_argument(words)
        self.native_attempted = False

    def release(self):
        self.task = None
        self.instance_argument = None
        self.native_attempted = False

    def request(self):
        """Signal-handler step: never await here, only schedule."""
        task = self.task
        if task is None or task.done():
            return
        if self.instance_argument is not None and not self.native_attempted:
            self.native_attempted = True
            asyncio.get_running_loop().create_task(self._native_cancel())
            return
        task.cancel()

    async def _native_cancel(self):
        try:
            reference = _read_reference(self.instance_argument)
            deadline = asyncio.get_running_loop().time() + 30
            receipt = await self.session.agents.interactions.cancel_session(
                reference, request_id='sigint-' + uuid.uuid4().hex,
                invocation=self._invocation(), write_guard=PromptWriteGuard(self.session.agents.authority),
                deadline=deadline)
            self.stderr.write('ordessa: cancel notification ' + receipt.state +
                              '; the original prompt result is not rewritten\n')
        except Exception as error:
            self.stderr.write('ordessa: native cancel was not sent (' +
                              type(error).__name__ + '); the original prompt still owns its result\n')
        finally:
            self.stderr.flush()

    def _invocation(self):
        from ordessa_interfaces.system_access.operations import RequestContext
        context = RequestContext(principal=self.session.environment.authority.authenticate(''),
                                 request_id=uuid.uuid4().hex, deadline=None)
        return self.session.environment.authority.resolve(context)


def _prompt_instance_argument(words):
    if words[:2] != ['agents', 'prompt']:
        return None
    for index, token in enumerate(words):
        if token == '--instance-ref' and index + 1 < len(words):
            return words[index + 1]
        if token.startswith('--instance-ref='):
            return token.split('=', 1)[1]
    return None


def _read_reference(argument):
    """Resolve one bounded ``FILE#/pointer`` instance reference; values only."""
    from ordessa_execution_agents.public import AgentInstanceRef
    path, _, pointer = argument.partition('#')
    if not path or not os.path.isabs(path):
        raise ValueError('instance reference must be an absolute result file')
    with open(path, 'rb') as handle:
        raw = handle.read(1048577)
    if len(raw) > 1048576:
        raise ValueError('instance reference file exceeds its bound')
    value = json.loads(raw)
    for part in [item for item in pointer.split('/') if item]:
        if not isinstance(value, dict) or part not in value:
            raise ValueError('instance reference pointer is absent')
        value = value[part]
    return AgentInstanceRef.decode(value)


async def run_session(state: LocalState, *, stdin=None, stdout=None, stderr=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    session = Session(state)
    try:
        loop = asyncio.get_running_loop()
        interactive = bool(getattr(stdin, 'isatty', lambda: False)())
        interrupt = Interrupt(session, stderr)

        try:
            loop.add_signal_handler(signal.SIGINT, interrupt.request)
        except (NotImplementedError, RuntimeError, ValueError):
            pass
        try:
            while True:
                if interactive:
                    stdout.write('ordessa> ')
                    stdout.flush()
                try:
                    line = await _readline(stdin)
                except EOFError:
                    facts = session.facts()
                    session.report(facts, stderr)
                    return 0 if not session.retained(facts) else 6
                if line is None:
                    facts = session.facts()
                    session.report(facts, stderr)
                    return 0 if not session.retained(facts) else 6
                if not line.strip():
                    continue
                try:
                    words = _tokens(line)
                except ValueError as error:
                    stderr.write(f'ordessa: {error}\n')
                    continue
                if not words:
                    continue
                if words[0] in ('exit', 'quit'):
                    facts = session.facts()
                    if session.retained(facts):
                        session.report(facts, stderr)
                        stderr.write('ordessa: release the listed work or inspect it before exit\n')
                        stdout.flush(); stderr.flush()
                        continue
                    return 0
                if words[0] == 'help':
                    channel.render_help(words[1:], session.metadata, stdout)
                    continue
                if words[0] == 'session':
                    stderr.write('ordessa: already in a session\n')
                    continue
                interrupt.task = asyncio.current_task()
                interrupt.bind(words)
                try:
                    code = await channel.async_run(
                        words, host=session.host, authenticate=session.authority.authenticate,
                        metadata=session.metadata, stdin=_empty_stdin(),
                        stdout=stdout, stderr=stderr)
                except asyncio.CancelledError:
                    interrupt.release()
                    stderr.write('ordessa: command interrupted; '
                                 'the original operation result is not rewritten as cancelled\n')
                    continue
                finally:
                    if interrupt.task is asyncio.current_task():
                        interrupt.release()
                stdout.flush()
                stderr.flush()
                if code not in (0,):
                    stderr.write(f'ordessa: command exit {code}\n')
        finally:
            session.close()
    finally:
        try:
            loop.remove_signal_handler(signal.SIGINT)
        except (NotImplementedError, RuntimeError, ValueError):
            pass


async def _readline(stdin):
    if hasattr(stdin, 'readline'):
        try:
            line = await asyncio.to_thread(stdin.readline)
        except (OSError, ValueError):
            raise EOFError
        return None if line == '' else line.rstrip('\n')
    raise EOFError


class _empty_stdin:
    def read(self, *args):
        return b''

    def isatty(self):
        return True


def _tokens(line):
    import shlex
    try:
        words = shlex.split(line, posix=True)
    except ValueError as error:
        raise ValueError(f'cannot parse command: {error}') from None
    for word in words:
        if word in _SHELL_TOKENS or '$(' in word or '`' in word:
            raise ValueError('shell operators are not part of the session grammar')
    return words


__all__ = ['Session', 'run_session']
