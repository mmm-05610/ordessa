"""Loopback HTTP/SSE transport seam for harness native channels.

Frozen in N001 alongside ``_transport``; families whose upstream channel is a
local HTTP server (event streams included) build on this. It is deliberately
narrow: loopback only, no redirects, no retries, no auth inheritance.

Invariants (docs/implementation/specifications/030-native-harness-expansion/acceptance.md):

- G4: SSE events keep their native ``event``/``id``/``data`` identity; unknown
  event types surface verbatim.
- G5: SSE framing follows the wire format (``\\n\\n`` event terminator,
  ``data:`` aggregation); a broken stream raises a typed failure and stops
  parsing.
- G9/G12: only loopback destinations (127.0.0.1 / ::1 / localhost) are
  accepted; no public bind, no credential inheritance, no auto-retry (G11).
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import socket
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping
from urllib.parse import urlparse

from .channel import ChannelClosed, LostReceipt
from ordessa_infrastructure.process.framing import ChannelFailure, FramingError

MAX_EVENT_BYTES = 8 * 1024 * 1024


class HttpChannelFailure(ChannelFailure):
    """Typed HTTP-channel failure (never a bare urllib error)."""

    def __init__(self, code: str, detail: str):
        super().__init__(code, detail)


class NonLoopbackRefused(HttpChannelFailure):
    """Destination is not a loopback address; the channel refuses it (G9)."""

    def __init__(self, detail: str):
        super().__init__("NON_LOOPBACK_REFUSED", detail)


@dataclass(frozen=True)
class SseEvent:
    """One SSE event with native identity preserved (G4)."""

    event: str
    data: str
    id: str | None = None
    retry: int | None = None


def _require_loopback(host: str) -> None:
    if host in {"localhost", "localhost.localdomain"}:
        return
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise NonLoopbackRefused(f"host is not an IP literal: {host!r}") from exc
    if not address.is_loopback:
        raise NonLoopbackRefused(f"host is not loopback: {host}")


class LoopbackHttpChannel:
    """Minimal JSON-over-HTTP plus SSE consumption against a local harness
    server. One instance owns one connection; close() releases only that."""

    def __init__(self, base_url: str, *, timeout: float = 10.0):
        parsed = urlparse(base_url)
        if parsed.scheme != "http":
            raise NonLoopbackRefused(f"only plain http loopback is allowed, got {parsed.scheme!r}")
        host = parsed.hostname or ""
        _require_loopback(host)
        self._host = host
        self._port = parsed.port or 80
        self._base_path = parsed.path.rstrip("/")
        self._timeout = timeout
        self._closed = False

    # -- request/response -------------------------------------------------
    def request_json(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, Any]:
        """One HTTP round trip. JSON body in, status + decoded JSON out.

        No retry on any outcome (G11); the caller owns reconciliation.
        """
        self._ensure_open()
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        request_headers = {"Content-Type": "application/json"}
        if headers:
            request_headers.update(headers)
        connection = http.client.HTTPConnection(
            self._host, self._port, timeout=timeout or self._timeout
        )
        sent = False
        try:
            connection.request(
                method, f"{self._base_path}{path}", body=payload, headers=request_headers
            )
            sent = True
            response = connection.getresponse()
            raw = response.read()
        except (OSError, socket.timeout) as exc:
            if sent:
                # bytes left this side and no receipt arrived: outcome unknown
                # (G11) — callers must not treat this as "safe to resend".
                raise LostReceipt(
                    f"http {method} {path}", None, f"sent but no receipt: {exc}"
                ) from exc
            raise HttpChannelFailure("HTTP_IO_ERROR", f"{method} {path}: {exc}") from exc
        finally:
            connection.close()
        if not raw:
            return response.status, None
        try:
            return response.status, json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise FramingError(f"response body is not valid UTF-8 JSON: {exc}") from exc

    # NOTE: request_json distinguishes "never sent" from "sent, receipt lost"
    # below: a transport failure after the request bytes were written is a
    # LostReceipt (outcome unknown, never silently retried, G11).

    # -- SSE ---------------------------------------------------------------
    def stream_events(
        self,
        path: str,
        *,
        method: str = "GET",
        body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        max_events: int | None = None,
    ) -> Iterator[SseEvent]:
        """Consume an SSE stream. The iterator ends when the server closes the
        stream; closing the stream is NOT task completion (OpenCode G-counter:
        断开SSE不是任务结束) — callers must confirm via protocol state."""
        self._ensure_open()
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        request_headers = {"Accept": "text/event-stream"}
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        if headers:
            request_headers.update(headers)
        connection = http.client.HTTPConnection(self._host, self._port, timeout=self._timeout)
        try:
            connection.request(method, f"{self._base_path}{path}", body=payload, headers=request_headers)
            response = connection.getresponse()
            if response.status >= 400:
                raise HttpChannelFailure("HTTP_STATUS", f"{method} {path} -> {response.status}")
            count = 0
            for event in _iter_sse(response):
                yield event
                count += 1
                if max_events is not None and count >= max_events:
                    break
        except (OSError, socket.timeout) as exc:
            raise HttpChannelFailure("HTTP_IO_ERROR", f"{method} {path}: {exc}") from exc
        finally:
            connection.close()

    def close(self) -> None:
        self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise ChannelClosed("http channel closed")


def _iter_sse(response: Any) -> Iterator[SseEvent]:
    event_name = "message"
    data_lines: list[str] = []
    event_id: str | None = None
    retry: int | None = None
    size = 0
    while True:
        try:
            line = response.readline()
        except (OSError, socket.timeout) as exc:
            raise HttpChannelFailure("HTTP_IO_ERROR", f"SSE read failed: {exc}") from exc
        if not line:
            if data_lines:
                yield SseEvent(event=event_name, data="\n".join(data_lines), id=event_id, retry=retry)
            return
        size += len(line)
        if size > MAX_EVENT_BYTES:
            raise FramingError(f"SSE event exceeded {MAX_EVENT_BYTES} bytes")
        # note: size resets at each event boundary below — one oversized event
        # is a framing breach; a long healthy stream is not.
        if line in (b"\n", b"\r\n"):
            if data_lines:
                yield SseEvent(event=event_name, data="\n".join(data_lines), id=event_id, retry=retry)
            event_name = "message"
            data_lines = []
            event_id = None
            retry = None
            size = 0  # the cap bounds ONE event, not the whole stream (G5)
            continue
        try:
            decoded = line.decode("utf-8", errors="strict").rstrip("\r\n")
        except UnicodeDecodeError as exc:
            raise FramingError(f"invalid UTF-8 in SSE stream: {exc.reason}") from exc
        if decoded.startswith(":"):
            continue  # comment
        field_name, _, value = decoded.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field_name == "data":
            data_lines.append(value)
        elif field_name == "event":
            event_name = value
        elif field_name == "id":
            event_id = value
        elif field_name == "retry":
            try:
                retry = int(value)
            except ValueError:
                pass
        # unknown SSE fields are ignored per the SSE wire format itself
