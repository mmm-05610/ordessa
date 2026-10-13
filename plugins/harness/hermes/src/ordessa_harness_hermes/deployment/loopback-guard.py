"""Reviewed offline gate asset for Hermes runs that must not leave loopback.

This is a test asset, deliberately NOT part of the production deployment: the
production template talks to the official DeepSeek root, which is what it
records. A gate that points Hermes at a local fake endpoint projects this file
read-only into ``$HERMES_HOME/sitecustomize.py`` and puts ``$HERMES_HOME``
first on ``PYTHONPATH``, so the gate - not the production artifact - owns the
``sitecustomize`` CPython imports. ``$HERMES_HOME`` is the isolated projection
inside the guest home root (``/runtime/home``); it is never a host directory.

It does three things and nothing else:

1. It installs the AgentBox Python egress guard. Because Hermes is a Python
   program, the guard refuses a non-loopback destination in
   ``socket.connect``/``connect_ex``/``create_connection``/``getaddrinfo``
   *before* resolution or connection, so a refused attempt can never leave the
   guest. A fixed self-test probes a TEST-NET address at load time, which makes
   "the guard is loaded and fail-closed" an observation rather than an
   assumption. Every load, self-test and refusal is appended to the audit file
   named by ``AGENTBOX_EGRESS_AUDIT`` (the project workspace, so the host can
   read it back). Audit records hold host and port only - never a credential,
   header, or request body.

2. It records which ACP session methods Hermes itself handled, by wrapping the
   adapter class right after its module is imported. That is the direct
   observation of "how the stored Session was reopened" (``session/load`` vs
   ``session/resume`` vs a fresh ``session/new``) which the Server cannot see,
   because the reopen happens inside the Worker. Lines go to the file named by
   ``AGENTBOX_ACP_AUDIT``. The same wrapper also records the ACP model state a
   session-creating method answered with (``acp-model <method> current=...
   available=...``), so "which model the adapter itself considers active" is a
   measurement of the real chain rather than a derivation from the
   configuration.

3. It applies the same reviewed deployment bootstrap the production artifact's
   own ``sitecustomize.py`` applies (``agentbox_hermes_bootstrap``), so the gate
   exercises the production start-up path rather than a gate-only variant.

A bootstrap failure is fatal (``SystemExit``), exactly as in production.
"""
from __future__ import annotations

import inspect
import ipaddress
import os
import socket
import sys

#: Audit sinks, injected by the gate through the adapter environment.
EGRESS_AUDIT_ENVIRONMENT = "AGENTBOX_EGRESS_AUDIT"
ACP_AUDIT_ENVIRONMENT = "AGENTBOX_ACP_AUDIT"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "ip6-localhost", "0.0.0.0"})
#: TEST-NET-2 (RFC 5737): never routable, so the self-test cannot reach anything
#: even if a guard were missing.
SELF_TEST_HOST = "198.51.100.7"
SELF_TEST_PORT = 443


def _record(location: str | None, line: str) -> None:
    if not location:
        return
    try:
        with open(location, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        # Auditing must never be the reason a refusal is missed.
        pass


def _is_loopback(host: object) -> bool:
    if host in (None, ""):
        return True
    text = str(host)
    if text in LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


class EgressRefused(OSError):
    """A destination the gate refuses before it can be resolved or contacted."""

    def __init__(self, kind: str, host: object, port: object) -> None:
        self.code = "AGENTBOX_EGRESS_BLOCKED"
        super().__init__(f"AGENTBOX_EGRESS_BLOCKED: {kind} to {host}:{port} is not loopback")


def _install_egress_guard(audit: str | None) -> int:
    refused = 0

    def refuse(kind: str, host: object, port: object) -> None:
        nonlocal refused
        refused += 1
        _record(audit, f"denied {kind} {host}:{port}")
        raise EgressRefused(kind, host, port)

    def address_of(args: tuple) -> tuple[object, object, object]:
        first = args[0] if args else None
        if isinstance(first, tuple) and first:
            return first[0], (first[1] if len(first) > 1 else None), None
        if isinstance(first, str) and len(args) > 1:
            return first, args[1], None
        return None, None, first  # a unix path, which is local IPC, not egress

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create_connection = socket.create_connection
    original_getaddrinfo = socket.getaddrinfo

    def connect(self, address, *rest):  # type: ignore[no-untyped-def]
        host, port, path = address_of((address,))
        if path is None and not _is_loopback(host):
            refuse("connect", host, port)
        return original_connect(self, address, *rest)

    def connect_ex(self, address, *rest):  # type: ignore[no-untyped-def]
        host, port, path = address_of((address,))
        if path is None and not _is_loopback(host):
            refuse("connect_ex", host, port)
        return original_connect_ex(self, address, *rest)

    def create_connection(address, *rest, **kwargs):  # type: ignore[no-untyped-def]
        host, port, path = address_of((address,))
        if path is None and not _is_loopback(host):
            refuse("create_connection", host, port)
        return original_create_connection(address, *rest, **kwargs)

    def getaddrinfo(host, *rest, **kwargs):  # type: ignore[no-untyped-def]
        if not _is_loopback(host):
            refuse("getaddrinfo", host, None)
        return original_getaddrinfo(host, *rest, **kwargs)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.create_connection = create_connection
    socket.getaddrinfo = getaddrinfo
    _record(audit, f"guard-loaded pid={os.getpid()}")
    # Fail-closed self-test: the refusal must happen inside this process, before
    # any syscall, so nothing is contacted and the attempt is recorded.
    try:
        socket.socket().connect((SELF_TEST_HOST, SELF_TEST_PORT))
    except EgressRefused:
        _record(audit, f"self-test-ok {SELF_TEST_HOST}:{SELF_TEST_PORT}")
    except OSError as error:  # pragma: no cover - the guard should have refused
        _record(audit, f"self-test-unexpected {type(error).__name__}")
        raise SystemExit(f"AGENTBOX_EGRESS_GUARD_BROKEN: {error}") from error
    else:  # pragma: no cover - the guard should have refused
        raise SystemExit("AGENTBOX_EGRESS_GUARD_BROKEN: the self-test connection was not refused")
    return refused


def _record_model_state(audit: str | None, name: str, result: object) -> None:
    """Record the ACP model state a session method answered with, if it carried one.

    ``session/new`` (and the load/resume/fork responses) return the adapter's own
    model selector payload: ``models.currentModelId`` plus the advertised
    ``availableModels`` ids. That value is what Hermes itself resolved for the
    session - including any provider-side rewriting - so reading it back is the
    measurement of the native model id. It is recorded as
    ``acp-model <method> current=<id> available=<id,...>``; a response without a
    model state records nothing. Attribute access is defensive (the ACP schema is
    a third-party shape) but a crash here would fail the adapter, so it is only
    ever reading.
    """
    try:
        models = getattr(result, "models", None)
        if models is None:
            return
        current = getattr(models, "current_model_id", None)
        if current is None:
            current = getattr(models, "currentModelId", None)
        available = getattr(models, "available_models", None)
        if available is None:
            available = getattr(models, "availableModels", None)
        identifiers: list[str] = []
        for item in available or ():
            identifier = getattr(item, "model_id", None)
            if identifier is None:
                identifier = getattr(item, "modelId", None)
            if identifier:
                identifiers.append(str(identifier))
        _record(audit, f"acp-model {name} current={current or ''} available={','.join(identifiers)}")
    except Exception:  # noqa: BLE001 - observation must never break the adapter
        _record(audit, f"acp-model {name} unreadable")


class _AcpMethodObserver:
    """Wrap Hermes' ACP session methods so the gate can read them back.

    A meta-path finder returns the real loader for ``acp_adapter.server`` and
    wraps its ``exec_module``, so the class is patched immediately after the
    module executes and before any session can be created. The observation is
    fail-loud: a missing class or method raises at import time instead of
    reporting "no reopen happened" later.

    Every wrapped method records its name when it is called (the order the gate
    reads back), and the session-creating ones additionally record the ACP model
    state their response carried once it returns. The model line is recorded with
    the *result*, so it needs an await on the async methods; both wrappers keep
    the native signature and return the native value untouched.
    """

    OBSERVED = ("new_session", "load_session", "resume_session", "set_session_model", "set_config_option")

    def __init__(self, audit: str | None) -> None:
        self.audit = audit
        self.instrumented = False

    def find_spec(self, fullname, path=None, target=None):  # noqa: ANN001 - import protocol
        if fullname != "acp_adapter.server":
            return None
        from importlib.machinery import PathFinder

        spec = PathFinder.find_spec(fullname, path, target)
        if spec is None or spec.loader is None:
            return spec
        loader = spec.loader
        original_exec = loader.exec_module

        def exec_module(module):  # noqa: ANN001 - import protocol
            original_exec(module)
            self._patch(module)

        loader.exec_module = exec_module
        return spec

    def _patch(self, module) -> None:  # noqa: ANN001 - a module
        agent = getattr(module, "HermesACPAgent", None)
        if agent is None:
            raise SystemExit("AGENTBOX_ACP_INSTRUMENTATION_FAILED: HermesACPAgent is missing")
        audit = self.audit

        def wrap(name: str) -> None:
            original = getattr(agent, name, None)
            if original is None:
                raise SystemExit(f"AGENTBOX_ACP_INSTRUMENTATION_FAILED: {name} is missing")

            if inspect.iscoroutinefunction(original):
                async def observed(self, *args, **kwargs):  # noqa: ANN001 - the native signature
                    _record(audit, f"acp-method {name} pid={os.getpid()}")
                    result = await original(self, *args, **kwargs)
                    _record_model_state(audit, name, result)
                    return result
            else:
                def observed(self, *args, **kwargs):  # noqa: ANN001 - the native signature
                    _record(audit, f"acp-method {name} pid={os.getpid()}")
                    result = original(self, *args, **kwargs)
                    _record_model_state(audit, name, result)
                    return result

            observed.__name__ = name
            setattr(agent, name, observed)

        for name in self.OBSERVED:
            wrap(name)
        self.instrumented = True
        _record(audit, "acp-instrumented " + ",".join(self.OBSERVED))


def _apply_bootstrap() -> None:
    try:
        import agentbox_hermes_bootstrap

        agentbox_hermes_bootstrap.apply()
    except BaseException as error:  # noqa: BLE001 - re-raised as a fatal exit
        raise SystemExit(f"AGENTBOX_HERMES_BOOTSTRAP_FAILED: {error}") from error


def _start() -> None:
    egress_audit = os.environ.get(EGRESS_AUDIT_ENVIRONMENT)
    acp_audit = os.environ.get(ACP_AUDIT_ENVIRONMENT)
    _install_egress_guard(egress_audit)
    observer = _AcpMethodObserver(acp_audit)
    if not any(isinstance(item, _AcpMethodObserver) for item in sys.meta_path):
        sys.meta_path.insert(0, observer)
    _apply_bootstrap()


_start()
