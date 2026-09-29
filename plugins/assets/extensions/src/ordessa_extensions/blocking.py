"""EXT-6 — blocking semantics, stated honestly.

The projection this domain performs is OBSERVATIONAL PLACEMENT. It must
never promise that a hook blocks, gates or enforces anything at brand
runtime: the in-repo counterexample is the pinned Codex hook face — a
failing or missing hook does not block the operation it decorates
(`docs/design/harness-configuration/classification.md` §四.4, citing
https://learn.chatgpt.com/docs/hooks). A security check carried by such a
hook would be an incorrect promise, so the promise is structurally
inexpressible here: the projection payload schema admits only
`semantics: "observational"`, and this module owns the constant and the
validator every adapter reuses.
"""
from __future__ import annotations

OBSERVATIONAL = "observational"

#: The only semantics value the projection vocabulary admits.
ALLOWED_SEMANTICS = (OBSERVATIONAL,)

COUNTEREXAMPLE = (
    "Codex MCP hook: an error or missing hook service does NOT block the"
    " operation (共同处理不代表相同语义 §四.4,"
    " docs/design/harness-configuration/classification.md:52,"
    " https://learn.chatgpt.com/docs/hooks)。Codex hook 失败不阻断 —"
    " same-name hooks across brands are therefore NOT evidence of equal"
    " blocking ABI; projection claims placement only.")

#: Projection-facing one-line statement embedded in descriptors/tests.
STATEMENT = (
    "Observational placement only — no block/enforce guarantee is made or"
    " supportable on the evidenced hook faces.")


class BlockingSemanticsError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def require_observational(semantics: object) -> None:
    """Refuse any payload that tries to claim more than observation."""
    if semantics != OBSERVATIONAL:
        raise BlockingSemanticsError(
            "BLOCKING_CLAIM_REFUSED",
            f"semantics must be {OBSERVATIONAL!r}; got {semantics!r}. "
            + COUNTEREXAMPLE)


__all__ = ["ALLOWED_SEMANTICS", "BlockingSemanticsError", "COUNTEREXAMPLE",
           "OBSERVATIONAL", "STATEMENT", "require_observational"]
