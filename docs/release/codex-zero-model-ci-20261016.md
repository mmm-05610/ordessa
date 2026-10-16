# Fixed Codex dependency for zero-model process tests

The Codex runtime-process suite previously depended on a desktop installation at a machine-specific path. A clean CI runner has no such file. The suite now requires an explicitly selected `ORDESSA_TEST_CODEX_EXECUTABLE` and checks the original official Codex 0.159.0 binary SHA-256 before any test runs.

CI downloads `@openai/codex@0.159.0-linux-x64` from the official npm registry into its temporary directory, verifies the fixed archive SHA-512, extracts only the native executable and checks its original SHA-256. It exports that temporary path to the existing suite. No global installation, product executable default, alias or fallback is added; no binary enters Git.

All original test functions, fixtures and classes retain their exact AST. The existing initialize/thread-start/thread-read sequence, empty turn ledger, isolated HOME/CODEX_HOME, dropped credentials, permission/refusal cases and owned-process cleanup assertions remain. The added dependency preflight refuses absent or different binaries. These are the existing isolated zero-model tests; they issue no model turn.

Validation on the exact PR source: all 36 original runtime-process cases pass with the verified official 0.159.0 executable. The actual YAML installer script passes using its pinned archive, and exports the expected temporary path. YAML/shell validation and unchanged original test/helper/class AST checks pass. No real model turn or existing user service is used.
