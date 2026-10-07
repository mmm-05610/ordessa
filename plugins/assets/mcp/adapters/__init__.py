"""Native-lane brand adapters for the MCP domain (Q4 T04).

Pure assess/compile/verify implementations for Codex and Claude Code with
their own intent DTOs (``backend.native_intents``). When harness-api is
published, C2 binds these through thin name-mapping adapters
(``docs/design/mcp/contracts.md:70``); until then nothing here imports host
internals, and nothing here touches the file system, HOME, secrets plaintext,
subprocesses or the network.
"""
