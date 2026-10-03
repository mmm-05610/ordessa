"""T03: bounded, cancellable, credential-less MCP handshake probes.

Two transports, one question each - "does this server answer an initialize
request" - answered under the hard bounds of
:attr:`backend.probe_policy.ProbePolicy` (wall-clock timeout, response byte
bound, kill grace). This upgrades the legacy stdio probe
(``SC/assets/mcp_probe.py``): the selector read, ``max_bytes``,
``start_new_session``, the killpg SIGTERM->grace->SIGKILL shutdown, the
finally-cleanup and the credential-less env allowlist are kept verbatim in
shape; the upgrades are protocol negotiation, cooperative cancellation,
guaranteed whole-process-group reaping (children *and* grandchildren), and a
graded facts shape.

The probe proves exactly one level of the FR-02 ladder: the initialize
handshake. It never returns or claims a tool catalog - a server that stuffs
``tools`` into its initialize result is ignored - and it can never prove
credential usability: every ``secretRef`` / declared header is excluded from
the run and reported under ``credentialScope: "unproven"`` (contracts.md §1
probe row; verification.md counterexample 8).

The probe is pure side-effect-once: no storage read or write, no definition
mutation, no native config, no model call. Every temporary process is killed
on every exit path, and the remote path carries **no** credentials at all.
"""
from __future__ import annotations

import json
import os
import selectors
import signal
import ssl
import subprocess
import time
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlsplit

from .definition import canonical_definition_v2
from .errors import (
    MCP_DEFINITION_INVALID,
    MCP_TRANSPORT_UNSUPPORTED,
    PROBE_AUTH_REQUIRED,
    PROBE_CANCELLED,
    PROBE_COMMAND_INVALID,
    PROBE_CONNECTION_FAILED,
    PROBE_FORMAT_INVALID,
    PROBE_PROTOCOL_MISMATCH,
    PROBE_REDIRECT_REFUSED,
    PROBE_RESPONSE_TOO_LARGE,
    PROBE_SPAWN_FAILED,
    PROBE_TIMEOUT,
    PROBE_URL_NOT_ALLOWED,
    McpError,
)
from .probe_policy import (
    DEFAULT_PROBE_POLICY,
    ProbePolicy,
    unproven_remote_headers,
    unproven_stdio_environment,
)

# -- probe typed codes ----------------------------------------------------------
# T014 converge: the probe family is registered in backend/errors.py (this
# module keeps re-exporting the names for its consumers). The five legacy
# codes keep their exact strings and ``"{code}: {message}"`` shape (raised
# through McpError, which formats identically to the legacy McpProbeError).

_REQUEST_ID = 1


def initialize_request(policy: ProbePolicy = DEFAULT_PROBE_POLICY) -> dict:
    """The one JSON-RPC message a probe ever sends (request id ``1``).

    ``params.protocolVersion`` is the newest version the *client* supports;
    the server's answer carries the negotiated version, which is what the
    result records.
    """
    return {
        "jsonrpc": "2.0",
        "id": _REQUEST_ID,
        "method": "initialize",
        "params": {
            "protocolVersion": policy.supported_protocol_versions[0],
            "capabilities": {},
            "clientInfo": {"name": policy.client_name, "version": policy.client_version},
        },
    }


def probe_definition(
    canonical: Mapping[str, Any], *,
    policy: ProbePolicy = DEFAULT_PROBE_POLICY,
    cancel: Optional[Any] = None,
) -> dict:
    """Probe one canonical definition (legacy or v2 shape), stdio or remote.

    ``cancel`` is any object with a falsy-able ``is_set()`` (a
    ``threading.Event`` in practice); cooperative checkpoints sit before the
    spawn, inside the bounded read loop, and between HTTP phases - the child
    process group is reaped on every path, including cancellation.
    """
    if not isinstance(canonical, Mapping):
        raise McpError(MCP_DEFINITION_INVALID, "a probe target is a canonical definition object")
    transport = canonical.get("transport")
    if not isinstance(transport, Mapping) or len(transport) != 1:
        raise McpError(MCP_DEFINITION_INVALID, "transport names exactly one of stdio/remote")
    kind = next(iter(transport))
    if kind == "stdio":
        return probe_stdio(canonical, policy=policy, cancel=cancel)
    if kind == "remote":
        return probe_http(canonical, policy=policy, cancel=cancel)
    raise McpError(MCP_TRANSPORT_UNSUPPORTED, f"unsupported transport {kind!r}")


# -- stdio ----------------------------------------------------------------------


def probe_stdio(
    canonical: Mapping[str, Any], *,
    policy: ProbePolicy = DEFAULT_PROBE_POLICY,
    cancel: Optional[Any] = None,
) -> dict:
    """Start one stdio server, read one initialize answer, kill the group.

    Returns graded facts (see :func:`_handshake_facts`). Failure modes are
    typed: ``PROBE_COMMAND_INVALID`` / ``PROBE_SPAWN_FAILED`` /
    ``PROBE_TIMEOUT`` / ``PROBE_FORMAT_INVALID`` / ``PROBE_RESPONSE_TOO_LARGE``
    / ``PROBE_PROTOCOL_MISMATCH`` / ``PROBE_CANCELLED``.
    """
    body = _transport_body(canonical, "stdio")
    command = body.get("command")
    if not isinstance(command, str) or not command.startswith("/") or "\x00" in command:
        raise McpError(PROBE_COMMAND_INVALID, "the command must be an absolute path")
    args = body.get("args", [])
    if (not isinstance(args, (list, tuple))
            or any(not isinstance(item, str) or "\x00" in item for item in args)):
        raise McpError(PROBE_COMMAND_INVALID, "arguments must be plain strings")
    environment, excluded = unproven_stdio_environment(body.get("env", {}))
    _check_cancel(cancel)

    try:
        process = subprocess.Popen(  # noqa: S603 - the caller stored this command
            [command, *args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=environment, start_new_session=True,
        )
    except OSError as exc:
        raise McpError(PROBE_SPAWN_FAILED, f"the server did not start: {exc}") from exc

    deadline = time.monotonic() + policy.timeout
    try:
        assert process.stdin is not None and process.stdout is not None
        try:
            process.stdin.write(_encode_line(initialize_request(policy)))
            process.stdin.flush()
        except (BrokenPipeError, ValueError, OSError):
            # The child died at startup and closed its stdin: that is a
            # format failure of the handshake, not a spawn failure.
            raise McpError(PROBE_FORMAT_INVALID, "the server closed before answering")
        answer = _read_bounded_line(process.stdout, deadline, policy, cancel)
        response = _json_object(answer, "the first line is not a JSON-RPC object")
        result, negotiation = _checked_initialize_result(response, policy)
        return _handshake_facts("stdio", result, negotiation, excluded)
    finally:
        _shutdown(process, policy.kill_grace)


def _read_bounded_line(
    stream: Any, deadline: float, policy: ProbePolicy, cancel: Optional[Any],
) -> bytes:
    """Legacy selector read, upgraded with cooperative cancel checkpoints."""
    collected = bytearray()
    selector = selectors.DefaultSelector()
    selector.register(stream, selectors.EVENT_READ)
    try:
        while b"\n" not in collected:
            _check_cancel(cancel)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise McpError(PROBE_TIMEOUT, "the server did not answer in time")
            # A short select slice keeps cancellation responsive; the
            # deadline - not the slice - still decides PROBE_TIMEOUT.
            if not selector.select(timeout=min(remaining, 0.05)):
                continue
            chunk = stream.read1(min(4096, max(1, policy.max_bytes + 1 - len(collected))))
            if not chunk:
                raise McpError(PROBE_FORMAT_INVALID, "the server closed before answering")
            collected.extend(chunk)
            if len(collected) > policy.max_bytes:
                raise McpError(
                    PROBE_RESPONSE_TOO_LARGE, "the answer exceeds the read bound")
    finally:
        selector.close()
    return bytes(collected).split(b"\n", 1)[0]


def _shutdown(process: subprocess.Popen, grace: float) -> None:
    """Kill the probe's whole child *session* on every exit path, reap it.

    ``start_new_session=True`` puts grandchildren in the same process group,
    so one killpg reaches the tree; SIGTERM, bounded grace, then SIGKILL.
    The leader is always waited for, so no zombie outlives the probe.
    """
    try:
        if process.poll() is None:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            try:
                process.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                try:
                    process.wait(timeout=grace)
                except subprocess.TimeoutExpired:
                    pass
    except ProcessLookupError:
        pass
    finally:
        for stream in (process.stdin, process.stdout):
            try:
                if stream is not None and not stream.closed:
                    stream.close()
            except OSError:
                pass


# -- HTTP (Streamable) -----------------------------------------------------------


def probe_http(
    canonical: Mapping[str, Any], *,
    policy: ProbePolicy = DEFAULT_PROBE_POLICY,
    cancel: Optional[Any] = None,
) -> dict:
    """POST one initialize to a Streamable-HTTP endpoint; never carry secrets.

    Stdlib only (``http.client``). Bounds: wall-clock timeout, response byte
    bound, TLS certificate verification **on** (the default context - there
    is no opt-out here), redirects **never** followed. Typed refusals:
    ``PROBE_AUTH_REQUIRED`` (401/403), ``PROBE_CONNECTION_FAILED``,
    ``PROBE_REDIRECT_REFUSED``, ``PROBE_TIMEOUT``, ``PROBE_FORMAT_INVALID``,
    ``PROBE_RESPONSE_TOO_LARGE``, ``PROBE_PROTOCOL_MISMATCH``,
    ``PROBE_CANCELLED``. All declared headers are excluded and reported -
    this probe carries zero credentials.
    """
    body = _transport_body(canonical, "remote")
    url = body.get("url")
    if not isinstance(url, str) or not url:
        raise McpError(PROBE_COMMAND_INVALID, "a remote probe target needs a url")
    # Read-only reuse of the storage-side policy (no store import): only
    # https or loopback http definitions may ever be probed.
    canonical_definition_v2({"name": "probe-target", "transport": {"remote": {"url": url}}})
    target = urlsplit(url)
    if target.scheme == "http" and target.hostname != "127.0.0.1":
        # canonical_definition_v2 matches a prefix, which a host like
        # "127.0.0.1.evil.test" would slip through; the probe demands the
        # exact loopback host before touching the network.
        raise McpError(
            PROBE_URL_NOT_ALLOWED, "plain http is allowed only to the exact loopback host")
    if target.hostname is None:
        raise McpError(PROBE_COMMAND_INVALID, "the remote url names no host")

    excluded = unproven_remote_headers(body.get("headers", {}))
    request_body = _encode_line(initialize_request(policy)).rstrip(b"\n")
    deadline = time.monotonic() + policy.timeout
    port = target.port or (443 if target.scheme == "https" else 80)
    path = target.path or "/"
    if target.query:
        path = f"{path}?{target.query}"

    connection: Optional[HTTPConnection] = None
    try:
        _check_cancel(cancel)
        if target.scheme == "https":
            # No ssl context argument: verification of the peer certificate
            # against the trust store is exactly the default.
            connection = HTTPSConnection(
                target.hostname, port,
                timeout=max(0.05, min(policy.timeout, deadline - time.monotonic())))
        else:
            connection = HTTPConnection(
                target.hostname, port,
                timeout=max(0.05, min(policy.timeout, deadline - time.monotonic())))
        try:
            connection.request(
                "POST", path, body=request_body,
                headers={"Content-Type": "application/json",
                         "Accept": "application/json, text/event-stream"},
            )
            response = connection.getresponse()
            _check_cancel(cancel)
            _status_refusal(response.status)
            answer = _read_bounded_http_body(response, deadline, policy, cancel)
        except TimeoutError as exc:
            raise McpError(PROBE_TIMEOUT, "the server did not answer in time") from exc
        except ssl.SSLError as exc:
            raise McpError(
                PROBE_CONNECTION_FAILED, f"the TLS handshake failed: {exc}") from exc
        except (OSError, HTTPException) as exc:
            raise McpError(
                PROBE_CONNECTION_FAILED, f"the endpoint could not be reached: {exc}") from exc
        response_object = _json_object(answer, "the answer is not a JSON-RPC object")
        result, negotiation = _checked_initialize_result(response_object, policy)
        return _handshake_facts("remote", result, negotiation, excluded)
    finally:
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass


def _status_refusal(status: int) -> None:
    if status in (401, 403):
        raise McpError(
            PROBE_AUTH_REQUIRED,
            f"the endpoint demands authorization ({status}) which an "
            "unproven probe never carries")
    if 300 <= status < 400:
        raise McpError(
            PROBE_REDIRECT_REFUSED, f"the endpoint redirected ({status}); probes never follow redirects")
    if not 200 <= status < 300:
        raise McpError(
            PROBE_CONNECTION_FAILED, f"the endpoint answered with status {status}")


def _read_bounded_http_body(
    response: Any, deadline: float, policy: ProbePolicy, cancel: Optional[Any],
) -> bytes:
    declared = response.getheader("Content-Length")
    if declared is not None and declared.strip().isdigit() and int(declared) > policy.max_bytes:
        raise McpError(PROBE_RESPONSE_TOO_LARGE, "the answer exceeds the read bound")
    collected = bytearray()
    while True:
        _check_cancel(cancel)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise McpError(PROBE_TIMEOUT, "the server did not answer in time")
        want = max(1, min(4096, policy.max_bytes + 1 - len(collected)))
        chunk = response.read(want) if not hasattr(response, "read1") else response.read1(want)
        if not chunk:
            break
        collected.extend(chunk)
        if len(collected) > policy.max_bytes:
            raise McpError(PROBE_RESPONSE_TOO_LARGE, "the answer exceeds the read bound")
        if b"\n" in collected:  # stdio-style framing and SSE both end lines
            break
    content_type = (response.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
    if content_type == "text/event-stream":
        for raw_line in bytes(collected).split(b"\n"):
            line = raw_line.strip()
            if line.startswith(b"data:"):
                return line[len(b"data:"):].strip()
        raise McpError(PROBE_FORMAT_INVALID, "the SSE answer carries no data line")
    if content_type and content_type != "application/json":
        raise McpError(
            PROBE_FORMAT_INVALID, f"the answer is not application/json ({content_type})")
    return bytes(collected).split(b"\n", 1)[0]


# -- shared answer checking / graded facts ----------------------------------------


def _transport_body(canonical: Mapping[str, Any], kind: str) -> Mapping[str, Any]:
    body = canonical["transport"][kind]
    if not isinstance(body, Mapping):
        raise McpError(MCP_DEFINITION_INVALID, f"the {kind} transport body must be an object")
    return body


def _encode_line(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")


def _check_cancel(cancel: Optional[Any]) -> None:
    if cancel is not None and cancel.is_set():
        raise McpError(PROBE_CANCELLED, "the probe was cancelled")


def _json_object(raw: bytes, message: str) -> dict:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise McpError(PROBE_FORMAT_INVALID, message) from exc
    if not isinstance(value, dict):
        raise McpError(PROBE_FORMAT_INVALID, message)
    return value


def _checked_initialize_result(response: dict, policy: ProbePolicy) -> tuple:
    """Validate the JSON-RPC envelope and record the *negotiated* version.

    The negotiation result is read off the server's own ``protocolVersion``;
    nothing is inferred from stored fields, and a version outside the
    client's supported list is a typed ``PROBE_PROTOCOL_MISMATCH``.
    """
    if response.get("id") != _REQUEST_ID:
        raise McpError(
            PROBE_FORMAT_INVALID,
            f"the answer carries id {response.get('id')!r}, not the probe request id")
    if "error" in response:
        raise McpError(PROBE_FORMAT_INVALID, "the server refused the initialize request")
    result = response.get("result")
    if not isinstance(result, Mapping):
        raise McpError(PROBE_FORMAT_INVALID, "the answer carries no result object")
    negotiated = result.get("protocolVersion")
    if not isinstance(negotiated, str) or not negotiated:
        raise McpError(PROBE_FORMAT_INVALID, "the answer states no protocolVersion")
    if negotiated not in policy.supported_protocol_versions:
        raise McpError(
            PROBE_PROTOCOL_MISMATCH,
            f"the server negotiated {negotiated!r}, outside the client's supported list")
    negotiation = {
        "requested": policy.supported_protocol_versions[0],
        "supported": list(policy.supported_protocol_versions),
        "negotiated": negotiated,
    }
    return result, negotiation


def _handshake_facts(
    transport: str, result: Mapping[str, Any],
    negotiation: Mapping[str, Any], credentials_excluded: Sequence[str],
) -> dict:
    """The graded FR-02 facts. Note what is NOT here: any catalog.

    ``result``'s other keys (``tools``, ``capabilities`` suggestions, ...)
    are deliberately dropped: an initialize handshake proves the handshake
    and nothing else (FR-02, verification.md counterexample 8).
    """
    info = result.get("serverInfo")
    info = info if isinstance(info, Mapping) else {}
    return {
        "status": "ok",
        "transport": transport,
        "evidence": "initialize-handshake",
        "serverInfo": {"name": info.get("name"), "version": info.get("version")},
        "protocolVersion": negotiation["negotiated"],
        "negotiation": dict(negotiation),
        "credentialScope": "unproven",
        "credentialsExcluded": list(credentials_excluded),
        "proves": ["initialize-handshake"],
        "doesNotProve": [
            "tool-catalog", "credential-usability", "connection-lease", "tool-invocability",
        ],
    }
