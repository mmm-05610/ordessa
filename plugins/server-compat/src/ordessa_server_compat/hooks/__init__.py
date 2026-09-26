"""Order 59: managed hooks - per-family models, one ledger, zero writeback.

Stage A pinned two declarative families (Claude Code and Codex) to one shape
and OpenCode to a code-asset shape; this package owns the declarative half:
the per-family schema (`model.py`) and the records (`records.py`). Nothing
here writes a user's native configuration - hooks reach an execution only as a
read-only projection of our own store.
"""
