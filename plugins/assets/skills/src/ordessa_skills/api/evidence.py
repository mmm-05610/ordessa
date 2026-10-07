"""Effect levels: the honest ladder between stored and used.

Authoritative text: docs/design/skills-v2/contracts.md §Harness 配置贡献 and
docs/design/skills-v2/verification.md G16.

The ladder keeps six DISTINCT levels: ``stored``, ``selected``, ``projected``,
``loaded``, ``used`` and ``unknown``. The legacy assets domain aliased
``USED = UNKNOWN`` because it had no independent call-evidence source; that
alias is retired here — conflating the two let a projection look like a
"learned" skill (verification.md G16, contracts.md "没有独立调用事件不得标
used").

Grading rules this module makes enforceable:

* ``stored``/``selected``/``projected`` each carry their own evidence; a
  configuration-projection digest match satisfies ``projection_digest`` and
  therefore proves **at most** ``projected`` — never ``loaded``, never ``used``.
* ``loaded`` requires an independent load observation.
* ``used`` requires an explicit invocation-event proof; no other evidence can
  promote a claim into it.
"""
from __future__ import annotations

from typing import Iterable

STORED = "stored"
SELECTED = "selected"
PROJECTED = "projected"
LOADED = "loaded"
USED = "used"
UNKNOWN = "unknown"

#: The six distinct levels, ordered strongest-first. A view reports the
#: highest level it can *prove*.
LADDER = (USED, LOADED, PROJECTED, SELECTED, STORED)

#: Every level name in the domain, strongest-first, `unknown` last.
LEVELS = LADDER + (UNKNOWN,)

#: A harness without a capability statement never displays above this.
UNCONFIRMED = "unconfirmed"

#: The minimum independent proof each level needs before a view may report it
#: (contracts.md: "前四有各自证据；没有独立调用事件不得标 used"). A digest
#: match of a projected tree is `projection_digest` — it is not a load
#: observation and never an invocation event.
PROOF_REQUIREMENTS: dict[str, str] = {
    STORED: "content_digest",
    SELECTED: "assignment_decision",
    PROJECTED: "projection_digest",
    LOADED: "load_observation",
    USED: "invocation_event",
}


def highest(*levels: str) -> str:
    """The strongest provable level among `levels`, or `unknown`."""
    known = {level for level in levels if level in LADDER}
    for candidate in LADDER:
        if candidate in known:
            return candidate
    return UNKNOWN


def attest(level: str, *, proofs: Iterable[str] = ()) -> str:
    """Grade one claimed effect level against the proofs actually held.

    A level stands only while its own minimum proof is present; anything
    else degrades to ``unknown`` — the ladder never moves on implied or
    borrowed evidence.
    """
    if level not in PROOF_REQUIREMENTS:
        return UNKNOWN
    required = PROOF_REQUIREMENTS[level]
    return level if required in frozenset(proofs) else UNKNOWN
