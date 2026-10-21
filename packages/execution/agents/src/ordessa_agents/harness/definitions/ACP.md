Shared Agent Client Protocol (ACP v1) consumer seam.

Frozen mid-batch (N008) because three families (gemini-cli, goose, vibe)
consume the same upstream protocol; extraction rule from design §3: share
only what is actually reused. Family clients subclass :class:`AcpClient` and
keep their own capability differences.

Protocol facts (https://agentclientprotocol.com/protocol, read 2026-10-04):

- JSON-RPC 2.0. Client→Agent: ``initialize`` (version negotiation),
  ``authenticate``, ``session/new``, ``session/prompt``, ``session/load``
  (optional), ``session/cancel`` (notification), ``session/set_mode``,
  ``logout``. Agent→Client: ``session/request_permission``,
  ``fs/read_text_file``, ``fs/write_text_file``, ``terminal/create``,
  ``terminal/output``, ``terminal/release``, ``terminal/wait_for_exit``,
  ``terminal/kill``, ``elicitation/create``, ``elicitation/complete``,
  ``session/update`` (notification).
- Custom methods are prefixed ``_``; custom data lives in ``_meta`` — the
  unknown-extension contract (G4): both are preserved verbatim and must not
  be dropped or rewritten.
- ``session/cancel`` is a notification (no response expected). A
  ``session/prompt`` response is a receipt boundary for one prompt turn;
  completion facts arrive via ``session/update`` records (G6: never invent
  completion).
- ``session/request_permission`` is a server→client request correlated by
  JSON-RPC id. This seam never answers it by itself (no auto-approve).

