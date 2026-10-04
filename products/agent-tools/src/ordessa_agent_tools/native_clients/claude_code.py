"""Claude Code consumer client (family ``claude``, protocol ``claude-stream-json/1``).

Pinned facts (N005, official docs read 2026-10-04):

- Channel: the Claude Code binary in headless mode, stdout
  ``--output-format stream-json`` (JSONL). The Agent SDK is the supported
  embedding ("runs the Claude Code binary"); it is NOT the Anthropic Client
  SDK (API client) and NOT Managed Agents (hosted). ``--input-format
  stream-json`` (bidirectional) exists only in the SDK surface; the headless
  doc does not pin it, so this client records that gap rather than inventing
  stdin shapes.
- stdout message types (documented): ``system/init`` (first event; carries a
  ``capabilities`` array such as ``interrupt_receipt_v1``),
  ``system/api_retry``, ``system/plugin_install``, ``assistant``/``user``
  (``parent_tool_use_id``), ``stream_event`` (text deltas), ``result`` (final
  line: response text, ``session_id``, cost, ``permission_denials``),
  ``permission_denied``. Unknown types/fields surface verbatim (G4).
- **The receipt is not completion**: ``result`` is the terminal stream record
  for one run; upstream also reports its own API-level retries
  (``system/api_retry``) — this client never ADDS retries (G11) and treats
  upstream retry events as facts to surface, not failures to hide.
- Sessions: capture ``session_id`` from ``result``; ``--resume <id|jsonl>``
  and ``--continue``. Cancel: SIGINT ends the turn; the SDK exposes
  ``interrupt()`` (``interrupt_receipt_v1`` capability).
- Permissions: ``canUseTool`` is an SDK callback; the CLI surface uses
  ``--permission-mode``/``--permission-prompts``. This client never
  auto-approves anything (SAFETY).
- Auth: API key is the sanctioned path; claude.ai OAuth/subscription login
  must not be used for third-party offerings without Anthropic approval
  (docs note). Commercial use is under Anthropic's Commercial Terms of
  Service. No user subscription token is ever read here (G12).
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from ._transport import (
    ChannelClosed,
    ChannelFailure,
    FramingError,
    LostReceipt,
    Message,
    ProcessChannel,
    RequestTimeout,
)

FAMILY_ID = "claude"
COMMAND_CATALOG_ID = "claude-code"
PROTOCOL = "claude-stream-json/1"


class ClaudeStreamFailure(ChannelFailure):
    """Typed failure for stream-json run boundaries (``result`` with failure
    semantics). Raw record preserved."""

    def __init__(self, detail: str, raw: Mapping[str, Any]):
        super().__init__("CLAUDE_RUN_FAILED", detail)
        self.raw = dict(raw)


def describe() -> dict[str, Any]:
    return {
        "familyId": FAMILY_ID,
        "commandCatalogId": COMMAND_CATALOG_ID,
        "channel": "stdio-stream-json",
        "protocol": PROTOCOL,
        "knownMessageTypes": [
            "system/init",
            "system/api_retry",
            "system/plugin_install",
            "assistant",
            "user",
            "stream_event",
            "permission_denied",
            "result",
        ],
    }


class ClaudeCodeClient:
    """Consumer of one owned Claude Code headless run (stdio).

    One run = one turn: ``prompt`` to ``result``. The stdin side of the
    stream-json protocol is not pinned by the headless doc; extension there
    is registered as unknown instead of fabricated.
    """

    def __init__(self, channel: ProcessChannel, *, name: str = "claude-stream"):
        self._channel = channel
        self._records: list[Mapping[str, Any]] = []
        self._init: Mapping[str, Any] | None = None

    @classmethod
    def launch(cls, spec: Any, *, name: str = "claude-stream") -> "ClaudeCodeClient":
        return cls(ProcessChannel.launch(spec, name=name), name=name)

    # -- handshake ------------------------------------------------------------
    def initialize(self, *, timeout: float = 30.0) -> Mapping[str, Any]:
        """Wait for the ``system/init`` record — the real handshake (model,
        tools, MCP servers, plugins, capabilities array)."""
        record = self._wait_for(lambda r: r.get("type") == "system" and r.get("subtype") == "init", timeout=timeout)
        self._init = record
        return record

    @property
    def capabilities(self) -> tuple[str, ...]:
        if self._init is None:
            return ()
        return tuple(self._init.get("capabilities") or ())

    # -- run lifecycle ---------------------------------------------------------
    def wait_result(self, *, timeout: float = 60.0) -> Mapping[str, Any]:
        """Collect records until the terminal ``result`` record.

        Returns it verbatim. A timeout raises :class:`RequestTimeout` with the
        run outcome unknown (never re-sent, G11). ``system/api_retry`` events
        are surfaced as records — upstream retries are facts, not something
        this client triggers or suppresses.
        """
        record = self._wait_for(lambda r: r.get("type") == "result", timeout=timeout)
        return record

    def next_record(self, *, timeout: float = 10.0) -> Mapping[str, Any]:
        raw = self._channel.next_message(timeout=timeout).raw
        self._records.append(raw)
        return raw

    def records(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._records)

    # -- cancellation -----------------------------------------------------------
    def cancel(self) -> None:
        """End the turn: send SIGINT to the owned process (documented
        semantics). Cancellation evidence is the process boundary, never a
        fake ``completed`` (G6)."""
        self._channel.sigint()

    def close(self) -> int:
        """Release only this owned process (G6/G8)."""
        return self._channel.close()

    # -- internals ---------------------------------------------------------------
    def _wait_for(self, predicate, *, timeout: float) -> Mapping[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RequestTimeout("claude-stream", None, timeout)
            try:
                message: Message = self._channel.next_message(timeout=remaining)
            except RequestTimeout:
                continue
            except (ChannelClosed, FramingError) as exc:
                raise LostReceipt("claude-stream", None, f"transport failure: {exc}") from exc
            raw = message.raw
            self._records.append(raw)
            if predicate(raw):
                return raw
