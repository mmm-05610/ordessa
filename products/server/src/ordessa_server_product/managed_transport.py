"""Environment-admitted wrapper for the public managed ACP transport.

This adapter knows only the transport lifecycle. It does not parse ACP frames,
make permission decisions, or claim durable/reliable delivery. Normal
start/write/release requests run inside RAW Environment invocations. The sole
post-cut exception is explicit cleanup of an already-owned unknown start,
which may call only the retained transport's public release receipt method.
Callback failures are never retried here.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import uuid4

from ordessa_environment_api import GuaranteeLevel, RequestKey


_SURFACE_START = "native.channel-start"
_SURFACE_WRITE = "native.channel-write"
_SURFACE_RELEASE = "native.channel-release"


@dataclass(frozen=True)
class PendingTransportClosure:
    """Exact owner and Environment fact retained after ambiguous start."""

    environment: Any
    activation: Any
    transport: "EnvironmentManagedTransport"
    request: RequestKey
    activity: Any | None


class ManagedTransportStartUnknown(RuntimeError):
    """Start callback may have created a native instance; retain its owner."""

    def __init__(self, cause: BaseException, pending: PendingTransportClosure) -> None:
        super().__init__(f"managed transport start outcome unknown: {cause}")
        self.pending_closure = pending


class EnvironmentManagedTransport:
    """Apply same-Environment RAW admission to a started public transport."""

    def __init__(self, environment: Any, transport: Any) -> None:
        self._environment = environment
        self._transport = transport
        self._last_dispatch_started = False
        self._start_outcome_unknown = False
        self._last_request: RequestKey | None = None

    @classmethod
    def open(cls, environment: Any, unstarted_transport: Any) -> "EnvironmentManagedTransport":
        """Start transport under Environment admission and return its wrapper.

        If admission refuses, ``start`` is not called. If the callback begins
        and then raises, the failure carries the wrapper and exact Environment
        request fact so the composition can retain closure responsibility.
        This method never closes or retries an uncertain start.
        """
        wrapper = cls(environment, unstarted_transport)
        try:
            wrapper._invoke(_SURFACE_START, "start", unstarted_transport.start)
        except BaseException as exc:
            if wrapper._last_dispatch_started:
                wrapper._start_outcome_unknown = True
                request = wrapper._last_request
                try:
                    activity = environment.query(request) if request is not None else None
                except BaseException:
                    activity = None
                pending = PendingTransportClosure(
                    environment,
                    getattr(environment, "native_channel_activation", None),
                    wrapper,
                    request,
                    activity,
                )
                raise ManagedTransportStartUnknown(exc, pending) from exc
            raise
        return wrapper

    def _invoke(self, surface_id: str, operation: str, callback, *, content: bytes = b""):
        request = RequestKey(
            environment_namespace=self._environment.environment_id,
            principal_scope="local",
            request_id="managed-transport-" + uuid4().hex,
            comparison={"operation": operation},
        )
        self._last_request = request
        digest = sha256(operation.encode("ascii") + b"\0" + content).hexdigest()
        result: list[Any] = []

        def dispatch() -> None:
            self._last_dispatch_started = True
            result.append(callback())

        self._environment.invoke(
            surface_id,
            request,
            guarantee=GuaranteeLevel.RAW,
            input_digest=digest,
            principal="local",
            handler=dispatch,
        )
        # A new request key is issued for every call, so a successful invoke
        # must have run the callback. Keep this explicit rather than fabricate
        # a return value if the Environment implementation changes.
        if not result:
            raise RuntimeError("Environment admitted transport operation without dispatch result")
        return result[0]

    def send_line(self, text: str) -> None:
        if not isinstance(text, str):
            raise TypeError("transport line must be a string")
        frozen = text
        self._invoke(
            _SURFACE_WRITE,
            "write",
            lambda: self._transport.send_line(frozen),
            content=frozen.encode("utf-8"),
        )

    def request_release(self) -> Any:
        release = getattr(self._transport, "request_release", None)
        if not callable(release):
            raise RuntimeError("managed transport has no truthful release receipt")
        return self._invoke(_SURFACE_RELEASE, "request-release", release)

    def release_owned_after_unknown_start(self) -> Any:
        """Explicit cleanup of an already-owned ambiguous start.

        This method invokes only the retained transport's public release
        receipt operation. It cannot start or write, and is reserved for the
        product composition's exact pending-closure record after an admission
        cut has blocked ordinary invokes.
        """
        if not self._start_outcome_unknown:
            raise RuntimeError("transport has no unknown-start cleanup obligation")
        release = getattr(self._transport, "request_release", None)
        if not callable(release):
            raise RuntimeError("managed transport has no truthful release receipt")
        return release()

    def terminate(self) -> None:
        terminate = getattr(self._transport, "terminate", None)
        if not callable(terminate):
            raise RuntimeError("managed transport has no terminate operation")
        self._invoke(_SURFACE_RELEASE, "terminate", terminate)

    @property
    def pid(self) -> Any:
        return self._transport.pid

    @property
    def established(self) -> Any:
        return self._transport.established

    @property
    def configuration_profile_snapshot(self) -> Any:
        return getattr(self._transport, "configuration_profile_snapshot", None)

    @configuration_profile_snapshot.setter
    def configuration_profile_snapshot(self, value: Any) -> None:
        self._transport.configuration_profile_snapshot = value

    def __getattr__(self, name: str) -> Any:
        # Preserve the existing transport surface, such as instance_directory
        # and release_report, without interpreting any of those values.
        return getattr(self._transport, name)
