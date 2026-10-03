"""EXT-3 — the shell-injection surface checklist.

The checklist exists to make the injection surface DIAGNOSABLE, not to
bless clever commands: any HIGH finding refuses the definition outright
(rewrite it as a clean argv — no approval can bless a shell one-liner),
while MEDIUM findings stay loadable but must be carried into the approval
record's findings digest so the approver signed off on exactly this
surface. This mirrors the classification rule that a shared mechanism is
not a shared guarantee: our approval is over OUR content, never over what
a brand's shell does with it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from .definitions import HookDefinition

#: HIGH — the element is a shell one-liner waiting to happen: it only
#: survives because some brand later joins argv into a shell line.
#: (`$(` command substitution is graded HIGH separately below; a plain
#: `$VAR` expansion face stays MEDIUM.)
# ; | & ` > < ( ) ' " newline, CR — joined into a shell line, each is an
# injection or quoting face (round 10: quotes/parens added, backslash
# demoted to a MEDIUM escape face to stop over-refusing normal args)
_SHELL_METACHARS = re.compile("[;&|`><()'\"\n\r]")
_CMD_SUBSTITUTION = re.compile(r"\$\(")

#: MEDIUM — documented expansion/glob faces: still no shell metachars, but
#: the approver must see that the brand (or its shell word-splitting) may
#: expand these before execution.
_ENV_EXPANSION = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?")
_TILDE = re.compile(r"\A~")
_GLOB = re.compile(r"[*?]")
_ESCAPE = re.compile(r"\\")

#: Interpreters, split by how they appear (round 13: a bare interpreter
#: running a SCRIPT file is approvable — approver-visibility MEDIUM;
#: an interpreter invoked with an inline-eval flag is the one-liner face
#: itself — HIGH):
_INTERPRETERS = ("sh", "bash", "dash", "zsh", "fish", "powershell",
                 "cmd", "python", "perl", "ruby", "node", "eval", "exec")
_EVAL_FLAGS = {"-c", "-lc", "-e", "--eval", "-command", "/c", "--command"}


def _interpreter_base(element: str) -> str:
    """Normalize an argv element to an interpreter name, or "".

    Strips path prefixes, `.exe` suffixes and version digits — `env`,
    `busybox` and versioned names (`python3.11`, `python3`) all resolve
    so the interpreter face cannot be bypassed by wrapper or version
    spelling (review round 14). `env`/`busybox`/`nix` themselves are
    wrappers, not interpreters: they only matter through the element
    AFTER them, which the pairwise scan covers.
    """
    base = element.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
    if base.endswith(".exe"):
        base = base[:-4]
    base = re.sub(r"[0-9.]+$", "", base)
    return base if base in _INTERPRETERS else ""

SEVERITIES = ("high", "medium")


@dataclass(frozen=True)
class Finding:
    severity: str
    rule: str
    index: int | None
    detail: str

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}")


def _finding(severity: str, rule: str, index: int | None,
             detail: str, *, element: str | None = None) -> Finding:
    # The finding carries a short element fingerprint (never the raw
    # element) so a findings digest pins the exact surface without
    # copying possibly-sensitive argv content into diagnostics.
    if element is not None:
        import hashlib
        tag = hashlib.sha256(element.encode("utf-8")).hexdigest()[:12]
        detail = f"{detail} [element:{tag}]"
    return Finding(severity=severity, rule=rule, index=index, detail=detail)


def scan_command(argv: Sequence[str]) -> tuple[Finding, ...]:
    """Grade one argv against the injection checklist (EXT-3)."""
    findings: list[Finding] = []
    # interpreter scan (rounds 14-15): ANY element naming an interpreter
    # (wrapper/version spellings normalized away) followed ANYWHERE later
    # by an eval flag — adjacent or separated, `=`-attached included — is
    # the one-liner face itself: `busybox sh -c ...`, `env python -c ...`,
    # `python -u -c ...`, `python --eval=code` all hit. Wrapper names
    # alone (`env`, `busybox`) never do.
    for index, element in enumerate(argv):
        if not _interpreter_base(str(element)):
            continue
        for later in argv[index + 1:]:
            lowered = str(later).lower()
            # bare flag, `=`-attached AND glue-attached (`-ccmd`,
            # `-c'code'`) all count — the safe direction over-refuses
            # exotic flags (round 16)
            if any(lowered.startswith(f) for f in _EVAL_FLAGS):
                findings.append(_finding(
                    "high", "INTERPRETER_HEADLINE", index,
                    "an interpreter is invoked with an inline-eval flag —"
                    " the shell-one-liner face itself",
                    element=str(element)))
                break
        if has_high(findings):
            break
    if argv and not has_high(findings):
        head = str(argv[0])
        if _interpreter_base(head):
            findings.append(_finding(
                "medium", "INTERPRETER_FACE", 0,
                "argv[0] is an interpreter running file arguments —"
                " approver must confirm the script is the intended"
                " content", element=head))
    for index, element in enumerate(argv):
        if _SHELL_METACHARS.search(element) or _CMD_SUBSTITUTION.search(
                element):
            findings.append(_finding(
                "high", "SHELL_METACHAR", index,
                f"argv[{index}] carries a shell metacharacter or command"
                " substitution; a definition must never need a shell"
                " one-liner", element=element))
            continue
        if (_ENV_EXPANSION.search(element) or _TILDE.match(element)
                or _ESCAPE.search(element)):
            findings.append(_finding(
                "medium", "EXPANSION_FACE", index,
                f"argv[{index}] contains an expansion/escape face"
                " ($var/${{..}}/~ backslash) the executing brand may"
                " interpret before exec",
                element=element))
        if _GLOB.search(element):
            findings.append(_finding(
                "medium", "GLOB_FACE", index,
                f"argv[{index}] carries a glob face the brand may expand",
                element=element))
    return tuple(findings)


def scan_definition(definition: HookDefinition) -> tuple[Finding, ...]:
    """Full checklist for one definition (command actions only)."""
    if definition.action_kind != "command" or definition.command is None:
        return ()
    return scan_command(definition.command)


def findings_digest(findings: Sequence[Finding]) -> str:
    """A stable digest so the approval record pins the scanned surface."""
    import hashlib
    import json
    canonical = json.dumps(
        [[f.severity, f.rule, f.index, f.detail] for f in findings],
        ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def has_high(findings: Sequence[Finding]) -> bool:
    return any(f.severity == "high" for f in findings)


__all__ = ["Finding", "findings_digest", "has_high", "scan_command",
           "scan_definition"]
