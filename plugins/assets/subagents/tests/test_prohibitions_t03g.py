"""T03g — prohibition counter-example suite for `plugins/assets/subagents`.

Requirement rows: `specs/011-q3-subagents/tasks.md` **T03g** ("one test per
negated requirement, each red the moment its guard is deleted"): FR08 (business
code writes no native file, spawns nothing, calls no model), FR09 (managed
content may address only the host-issued instance-private generation, through
an opaque `TargetHandle`; a user's or project's native path stays unreachable),
FR11 (an absent Settings/Profile/Chat contribution must not break this domain),
FR12 (no second dispatcher: the legacy `run_subagent` vocabulary and grant table
stay unreachable), FR04 (an invalid or stale snapshot is refused before any
side effect), FR14 (importing content never executes it, never follows an
include or a URL) and the G24 zero-side-effect rule on the user HOME.
Also contracts.md §C1 ("no arbitrary host path read, no spawn, no model call,
no native-dir write from the service") and §C5.

Contract change this file now reflects (SR-1b, `api-requests.md` §"SR-1b FINAL
answers"): the Q3-local intent vocabulary (`TargetSlot`, a local `MountContent`,
`SetRebuildClassOption`, `InvokeSubagent`, a local `IntentSet`) was **deleted**
once `harness-api` was published and consumed, so every prohibition below is
re-expressed against the real `ordessa_harness_api` types — same prohibition,
new symbol. Nothing was dropped to make a row pass: where the published
constructor is *laxer* than the deleted local enum (a `TargetHandle.handle_id`
or a `FieldPath` segment only police separators and traversal, so `"~/.claude"`
is legal upstream), Q3's own stricter token layer
(`adapters.intents._check_token` via `validate_source` /
`select_content_target` / `safe_field_path` / `mount_relative_name`) is what the
guard pins, and each such guard proves that the lax upstream shape is refused
*here* before any intent object exists.

Evidence level: L1. These guards prove the *absence* of a capability; they
never claim a brand works (verification.md: file/format tests are not L3).

Every prohibition ships with a capability probe that shows the instrument would
have caught the defect, so a green run means "the guard was watching", not
"nothing was looked at". Fixtures use `tmp_path` only: the real `~/.claude`,
`~/.codex` and `~/.pi` are never read, written or created (AGENTS.md rule 7,
verification.md G24).
"""
from __future__ import annotations

import ast
import builtins
import dataclasses
import hashlib
import http.client
import inspect
import os
import pathlib
import re
import socket
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import pytest

TESTS_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = TESTS_DIR.parent
SRC_DIR = PACKAGE_DIR / "src"
PKG_DIR = SRC_DIR / "ordessa_assets_subagents"
PACKAGE_NAME = "ordessa_assets_subagents"

if str(SRC_DIR) not in sys.path:  # this file owns no conftest.py
    sys.path.insert(0, str(SRC_DIR))

#: The published contract vocabulary every FR09 guard below is driven through
#: (SR-1b: this package emits C0's intents and nothing else).
from ordessa_harness_api import (  # noqa: E402  (path set just above)
    AdapterContext, BindSecret, ContentRef, ContractError, FieldClaim,
    FieldPath, Installation, IntentSet, IntentSource, InvokeAction,
    MountContent, RemoveOwnedContent, ResetField, SetField, TargetDescriptor,
    TargetHandle,
)

#: `specs/011-q3-subagents/legacy-inventory-matrix.md` §1 — the legacy dispatch
#: vocabulary that must never be reachable from this domain (FR12 / G10).
LEGACY_FORBIDDEN_SYMBOLS: tuple[str, ...] = (
    "grant_edges",
    "resolve_roster",
    "has_delegation",
    "check_cycle",
    "tool_definitions",
    "validate_run_arguments",
    "run_subagent",
    "list_subagents",
    "server_subagent_grants",
    "agentbox-subagents",
)

#: FR12: a domain that owns no dispatcher has no reason to *define* one. This
#: applies to definitions (functions / classes), not to the labels the legacy
#: inventory matrix uses while refusing the old artifacts — those are covered by
#: `LEGACY_NEAR_MISS` below.
DISPATCH_NAME_RE = re.compile(
    r"roster|grant_edge|grant_edges|cycle|run_subagent|list_subagents|"
    r"turn_limit|timeout|delegat|dispatch",
    re.I,
)

#: FR08: this service never spawns, connects or calls a model.
FORBIDDEN_EXECUTION_MODULES: tuple[str, ...] = (
    "subprocess", "socket", "urllib", "http", "multiprocessing", "asyncio",
    "pty", "shlex", "signal",
)

#: Reviewed near-misses: one legacy symbol may appear **only** inside the
#: binding whose purpose is to refuse it (matrix §3 REJECT rows). The value is
#: the required enclosing module-level binding name.
LEGACY_NEAR_MISS: dict[tuple[str, str], str] = {
    ("migration.py", "server_subagent_grants"): "_TABLE_BY_KEYS",
}
NEAR_MISS_BINDING_RE = re.compile(
    r"\A_?(TABLE_BY_KEYS|REJECT\w*|DENY\w*|REFUSE\w*|FORBIDDEN\w*|BANNED\w*)")

#: Strings that would mean this domain talks to the old grant table directly.
#: Case-sensitive SQL markers on purpose: prose about updating a row is not SQL.
STORE_TAKEOVER_TOKENS: tuple[str, ...] = (
    "CREATE TABLE", "INSERT INTO", "INSERT OR IGNORE", "DELETE FROM",
    "ON CONFLICT", "PRAGMA ", "grant_subagent", "revoke_subagent", "subagent_grants",
)
STORE_TAKEOVER_CASE_INSENSITIVE: tuple[str, ...] = ("sqlite3", "sqlite_master")

PRINCIPAL = "u:guardian"
OTHER_PRINCIPAL = "u:stranger"
SCOPE = "server:guard"
GRANTS = frozenset({"read-only"})
APPROVED_AT = "2026-09-28T10:00:00+00:00"

#: FR14: role text that would run something if it were ever interpreted.
HOSTILE_BODIES: tuple[tuple[str, str], ...] = (
    ("shell-call", 'Call os.system("touch {sentinel}") now.'),
    ("import-call", 'Use __import__("subprocess").run(["touch", "{sentinel}"]) here.'),
    ("eval-exec", "Now eval('1+1') and exec('x = 1') inside the role text."),
    ("jinja-expression", "Greeting: {{ 7*7 }} and {{% if x %}}y{{% endif %}}"),
    ("shell-prefix", "!cmd /c echo hello and !echo done"),
    ("module-import", "import os\nprint(os.getcwd())\n"),
)

PATH_SHAPED_VALUES: tuple[str, ...] = (
    "/home/user/.claude/agents/x.md",
    "~/.codex/config.toml",
    "../escape/definition.md",
    "..\\escape\\definition.md",
    "https://example.test/agent.md",
    "./relative.md",
    "~/agent",
)

#: The publication rule Q3 relies on for its grant prefix: one managed
#: directory, one relative name per definition (`FieldClaim("directory",
#: handle_id, ("agents",))`, api-requests.md §SR-1b FINAL (a)).
GRANT_PREFIX = "agents"

#: Every intent-carrying string field allowed to hold a separator: the mounted
#: relative name, which is relative by construction and pinned to the grant
#: prefix below. Everything else must stay a bare token.
RELATIVE_NAME_FIELDS: frozenset[str] = frozenset({"relative_name"})


def claude_context(*, handle: TargetHandle | None = None,
                   harness_id: str = "claude",
                   targets: tuple[TargetDescriptor, ...] | None = None) -> AdapterContext:
    """A copy-ready host context at the Claude pin — the same construction as
    `tests/test_claude_adapter_t06.py:29-34`: one instance-private directory
    target carrying a server-issued `TargetHandle`, granted for `("agents",)`."""
    from ordessa_assets_subagents.adapters import claude

    if targets is None:
        targets = (TargetDescriptor(
            handle or TargetHandle(claude.CLAUDE_GENERATION_HANDLE, 7),
            "directory", "content", "instance", (("agents",),),
            ("restore-owned-baseline",)),)
    return AdapterContext(
        targets,
        Installation(harness_id, None, claude.CLAUDE_ADAPTER_SEMVER,
                     "fixture:prohibition-guards"),
        "acp", "instance", "fixture:capability",
    )


def codex_context(*, handle: TargetHandle | None = None) -> AdapterContext:
    """The same shape for the codex pin (used to prove a *second* brand target
    is still only ever the injected handle, never a name this domain invented).
    """
    from ordessa_assets_subagents.adapters import codex

    return AdapterContext(
        (TargetDescriptor(
            handle or TargetHandle("assets-native-subagents-codex-generation", 7),
            "directory", "content", "instance", (("agents",),)),),
        Installation("codex", codex.CODEX_CLI_SEMVER, codex.CODEX_ADAPTER_SEMVER,
                     "fixture:prohibition-guards"),
        "acp", "instance", "fixture:capability",
    )


def host_source(item_id: str = "def-guardian", *, facet_id: str | None = None,
                contribution_version: str = "v1") -> IntentSource:
    """An `IntentSource` shaped like the one a carrier grants: the facet defaults
    to this domain's own, and every refusal test overrides it explicitly."""
    from ordessa_assets_subagents.adapters import intents

    # `None` means "this domain's facet"; an explicit "" is passed through,
    # because "empty facet" is one of the shapes a forgery probe needs.
    return IntentSource(intents.FACET_ID if facet_id is None else facet_id,
                        item_id, contribution_version)


def strings_under(value: Any, location: str = "") -> list[tuple[str, str]]:
    """Every string inside one intent, with its dotted location.

    The old guard walked `dataclasses.fields` of the local vocabulary; the real
    intents nest (`IntentSource`, `TargetHandle`, `ContentRef`), so the walk is
    recursive — a host path hidden inside a nested contract object is exactly
    the FR09 defect.
    """
    found: list[tuple[str, str]] = []
    if isinstance(value, str):
        found.append((location, value))
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for field in dataclasses.fields(value):
            found.extend(strings_under(getattr(value, field.name, None),
                                       f"{location}.{field.name}"))
    elif isinstance(value, (tuple, list)):
        for index, entry in enumerate(value):
            found.extend(strings_under(entry, f"{location}[{index}]"))
    elif isinstance(value, dict):
        for key, entry in value.items():
            found.extend(strings_under(entry, f"{location}.{key}"))
    return found


def field_leaf(location: str) -> str:
    """`target.handle_id` -> `handle_id`; `.relative_name` -> `relative_name`."""
    tail = location.rsplit(".", 1)[-1]
    return tail.split("[", 1)[0]


class Tripwire(RuntimeError):
    """Raised instead of letting the domain spawn / connect / call a model."""


# -- instrumentation: tripwires, write recorder, tree snapshots --------------


class _Tripwires:
    """Patch every process / network entry point to raise and be logged."""

    TARGETS: tuple[tuple[str, str], ...] = (
        ("subprocess", "Popen"), ("subprocess", "run"), ("subprocess", "call"),
        ("subprocess", "check_call"), ("subprocess", "check_output"),
        ("subprocess", "getoutput"), ("subprocess", "getstatusoutput"),
        ("os", "system"), ("os", "popen"), ("os", "fork"), ("os", "kill"),
        ("os", "killpg"), ("os", "posix_spawn"), ("os", "posix_spawnp"),
        ("os", "execv"), ("os", "execve"), ("os", "execvp"), ("os", "execvpe"),
        ("os", "execl"), ("os", "execle"), ("os", "execlp"),
        ("os", "spawnl"), ("os", "spawnle"), ("os", "spawnlp"), ("os", "spawnlpe"),
        ("os", "spawnv"), ("os", "spawnve"), ("os", "spawnvp"), ("os", "spawnvpe"),
        ("socket", "socket"), ("socket", "create_connection"),
        ("urllib.request", "urlopen"),
        ("http.client", "HTTPConnection"), ("http.client", "HTTPSConnection"),
    )

    #: labels a capability probe can actually invoke
    PROBES: dict[str, Any] = {
        "subprocess.Popen": lambda: subprocess.Popen(["true"]),
        "subprocess.run": lambda: subprocess.run(["true"]),
        "subprocess.call": lambda: subprocess.call(["true"]),
        "os.system": lambda: os.system("true"),
        "os.kill": lambda: os.kill(os.getpid(), 0),
        "socket.socket": lambda: socket.socket(),
        "socket.create_connection": lambda: socket.create_connection(("127.0.0.1", 1)),
        "urllib.request.urlopen": lambda: urllib.request.urlopen("http://127.0.0.1:1"),
        "http.client.HTTPConnection": lambda: http.client.HTTPConnection("x"),
        "http.client.HTTPSConnection": lambda: http.client.HTTPSConnection("x"),
    }

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.fired: list[str] = []
        self.installed: dict[str, tuple[Any, str]] = {}
        modules = {
            "subprocess": subprocess, "os": os, "socket": socket,
            "urllib.request": urllib.request, "http.client": http.client,
        }
        for module_name, attribute in self.TARGETS:
            module = modules[module_name]
            if not hasattr(module, attribute):
                continue
            label = f"{module_name}.{attribute}"

            def boom(*_args, _label=label, **_kwargs):
                self.fired.append(_label)
                raise Tripwire(_label)

            boom.__name__ = f"tripwire_{attribute}"
            monkeypatch.setattr(module, attribute, boom)
            self.installed[label] = (module, attribute)

    def call(self, label: str) -> None:
        self.PROBES[label]()

    def is_tripwire(self, label: str) -> bool:
        module, attribute = self.installed[label]
        return getattr(module, attribute).__name__.startswith("tripwire_")


def _install_tripwires(monkeypatch: pytest.MonkeyPatch) -> _Tripwires:
    return _Tripwires(monkeypatch)


def _is_write_mode(mode: str) -> bool:
    return any(char in mode for char in "wax+")


def _is_under(candidate: str, root: str) -> bool:
    return candidate == root or candidate.startswith(root + os.sep)


class _Recorder:
    """Records every write *attempt*, then performs it (pass-through).

    Recording the attempt rather than the resulting file is what makes FR04's
    "refused before any side effect" provable: a write that never lands but was
    still attempted shows up here.
    """

    def __init__(self) -> None:
        self.attempts: list[tuple[str, str]] = []

    def note(self, kind: str, target: Any) -> None:
        try:
            text = os.fspath(target)
        except TypeError:
            return
        if not isinstance(text, (str, bytes)):
            return
        text = os.fsdecode(text)
        if not os.path.isabs(text):
            text = os.path.join(os.getcwd(), text)
        self.attempts.append((kind, os.path.normpath(text)))

    def reset(self) -> None:
        self.attempts.clear()

    def writes(self) -> list[tuple[str, str]]:
        return list(self.attempts)

    def outside(self, root: Path) -> list[tuple[str, str]]:
        resolved = os.path.realpath(root)
        return [entry for entry in self.attempts
                if not _is_under(os.path.realpath(entry[1]), resolved)]

    def under(self, root: Path) -> list[tuple[str, str]]:
        resolved = os.path.realpath(root)
        return [entry for entry in self.attempts
                if _is_under(os.path.realpath(entry[1]), resolved)]

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real_open = builtins.open
        real_path_open = pathlib.Path.open
        real_os_open = os.open

        def probe_open(file, *args, **kwargs):  # noqa: ANN001
            if _is_write_mode(str(args[0] if args else kwargs.get("mode", "r"))):
                self.note("open", file)
            return real_open(file, *args, **kwargs)

        def probe_path_open(instance, *args, **kwargs):  # noqa: ANN001
            if _is_write_mode(str(args[0] if args else kwargs.get("mode", "r"))):
                self.note("Path.open", instance)
            return real_path_open(instance, *args, **kwargs)

        def probe_os_open(path, flags, *args, **kwargs):  # noqa: ANN001
            if flags & (os.O_CREAT | os.O_WRONLY | os.O_RDWR | os.O_TRUNC):
                self.note("os.open", path)
            return real_os_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", probe_open)
        monkeypatch.setattr(pathlib.Path, "open", probe_path_open)
        monkeypatch.setattr(os, "open", probe_os_open)

        for name in ("mkdir", "makedirs", "replace", "rename", "remove", "unlink",
                     "rmdir", "link", "symlink", "chmod", "symlink"):
            if not hasattr(os, name):
                continue
            real = getattr(os, name)

            def wrapper(*args, _real=real, _name=name, **kwargs):
                for position in args[:2]:
                    if isinstance(position, (str, bytes, os.PathLike)):
                        self.note(f"os.{_name}", position)
                return _real(*args, **kwargs)

            monkeypatch.setattr(os, name, wrapper)

        real_mkstemp = tempfile.mkstemp

        def probe_mkstemp(*args, **kwargs):
            fd, name = real_mkstemp(*args, **kwargs)
            self.note("mkstemp", name)
            return fd, name

        monkeypatch.setattr(tempfile, "mkstemp", probe_mkstemp)


def _snapshot(root: Path) -> dict[str, str]:
    """Content-addressed tree snapshot (path -> kind + byte digest)."""
    entries: dict[str, str] = {}
    root = Path(root)
    if not root.exists():
        return entries
    for path in sorted(root.rglob("*")):
        key = str(path.relative_to(root))
        if path.is_symlink():
            entries[key] = "symlink"
        elif path.is_dir():
            entries[key] = "dir"
        else:
            with real_open(path, "rb") as handle:
                entries[key] = "file:" + hashlib.sha256(handle.read()).hexdigest()
    return entries


real_open = builtins.open


# -- source scanners --------------------------------------------------------


def _src_files() -> list[Path]:
    return sorted(path for path in PKG_DIR.rglob("*.py") if "__pycache__" not in path.parts)


def _parse(path: Path) -> tuple[ast.Module | None, str | None]:
    try:
        return ast.parse(path.read_text(encoding="utf-8")), None
    except SyntaxError as exc:
        return None, (f"{path.relative_to(PACKAGE_DIR)}: SyntaxError at line "
                      f"{exc.lineno} ({exc.msg}) — unparsable source is a red")


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """Docstrings are how a documented *absence* is written; they are not use."""
    docs: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docs.add(id(body[0].value))
    return docs


def _binding_targets(statement: ast.stmt) -> list[str]:
    if isinstance(statement, ast.Assign):
        return [getattr(target, "id", "") for target in statement.targets]
    if isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
        return [getattr(statement.target, "id", "")]
    if isinstance(statement, ast.ClassDef):
        return [statement.name]
    return []


def _legacy_symbol_findings(files: list[Path]) -> tuple[list[str], list[str]]:
    """(hard violations, tolerated near-misses) for the legacy vocabulary."""
    hard: list[str] = []
    tolerated: list[str] = []
    for path in files:
        tree, error = _parse(path)
        if error:
            hard.append(error)
            continue
        docs = _docstring_nodes(tree)
        owners = _module_binding_map(tree)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if any(symbol in node.name for symbol in LEGACY_FORBIDDEN_SYMBOLS):
                    hard.append(f"{path.name}: defines '{node.name}'")
            elif isinstance(node, ast.Name):
                if any(symbol in node.id for symbol in LEGACY_FORBIDDEN_SYMBOLS):
                    hard.append(f"{path.name}: identifier '{node.id}'")
            elif isinstance(node, ast.Attribute):
                if any(symbol in node.attr for symbol in LEGACY_FORBIDDEN_SYMBOLS):
                    hard.append(f"{path.name}: attribute '.{node.attr}'")
            elif isinstance(node, ast.keyword) and node.arg:
                if any(symbol in node.arg for symbol in LEGACY_FORBIDDEN_SYMBOLS):
                    hard.append(f"{path.name}: keyword '{node.arg}'")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docs:
                    continue
                for symbol in LEGACY_FORBIDDEN_SYMBOLS:
                    if symbol not in node.value:
                        continue
                    binding = owners.get(id(node), "")
                    expected = LEGACY_NEAR_MISS.get((path.name, symbol))
                    if (expected is not None and binding == expected
                            and NEAR_MISS_BINDING_RE.match(binding or "")):
                        tolerated.append(
                            f"{path.name}: '{symbol}' inside refusal binding {binding}")
                    else:
                        hard.append(
                            f"{path.name}: string '{symbol}' in binding {binding!r}, "
                            "outside a reviewed refusal table")
    return hard, tolerated


def _dispatch_definitions(files: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in files:
        tree, error = _parse(path)
        if error:
            findings.append(error)
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                    and DISPATCH_NAME_RE.search(node.name):
                findings.append(f"{path.name}: {node.name}")
    return findings


def _execution_module_hits(source: str) -> list[str]:
    tree = ast.parse(source)
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            hits.extend(alias.name for alias in node.names
                        if alias.name.split(".")[0] in FORBIDDEN_EXECUTION_MODULES)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module.split(".")[0] in FORBIDDEN_EXECUTION_MODULES:
                hits.append(node.module)
    return sorted(set(hits))


WRITEISH_NAMES = frozenset({
    "open", "write_text", "write_bytes", "mkdir", "makedirs", "replace", "rename",
    "remove", "unlink", "rmdir", "link", "symlink", "copy", "copyfile", "copytree",
    "rmtree", "truncate", "touch", "joinpath", "chmod",
})


def _literals_of(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    return [sub.value for sub in ast.walk(node)
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str)]


def _native_write_literal(source: str) -> list[str]:
    """A write-ish call whose path region names a host / native location.

    The path region of `Path("~/.claude/x").write_text(..)` is the receiver as
    well as the argument, so both are scanned.
    """
    native = re.compile(r"\.claude|\.codex|\.pi(?=[/.]|$)|~|\$\{?HOME\}?|\A/[^\s]*\Z")
    tree = ast.parse(source)
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", "")
        if name not in WRITEISH_NAMES:
            continue
        receiver = node.func.value if isinstance(node.func, ast.Attribute) else None
        for text in _literals_of(receiver) + _literals_of_nodes(node.args[:2]):
            if native.search(text):
                findings.append(f"{name}({text!r})")
        for keyword in node.keywords:
            if keyword.arg in {"src", "dst", "path", "file", "dir", "prefix", "suffix"}:
                for text in _literals_of(keyword.value):
                    if native.search(text):
                        findings.append(f"{name}({keyword.arg}={text!r})")
    return findings


def _literals_of_nodes(nodes: list[ast.expr]) -> list[str]:
    out: list[str] = []
    for node in nodes:
        out.extend(_literals_of(node))
    return out


def _touches_home(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            attribute = getattr(sub.func, "attr", None)
            function = getattr(sub.func, "id", None)
            if attribute in {"home", "expanduser"} or function == "expanduser":
                return True
    return False


def _home_target_findings(source: str) -> list[str]:
    """HOME may be *compared* (a refusal guard), never used as a path source.

    A value derived from `Path.home()` / `expanduser()`, or a `~` literal, that
    reaches an open / write primitive or is joined with `/` is exactly the §C1
    "arbitrary host path read" and G24 "user HOME touched" defect.
    """
    tree = ast.parse(source)
    home_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _touches_home(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    home_names.add(target.id)

    def is_home_expression(node: ast.AST) -> bool:
        if _touches_home(node):
            return True
        if isinstance(node, ast.Name) and node.id in home_names:
            return True
        for text in _literals_of(node):
            if text == "~" or text.startswith("~") or "~/" in text:
                return True
        return False

    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) \
                and is_home_expression(node.left):
            findings.append("a HOME-derived path is joined with '/'")
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", "")
            if name not in WRITEISH_NAMES and name not in {"read_text", "read_bytes",
                                                           "glob", "iterdir", "walk"}:
                continue
            arguments = list(node.args[:2])
            arguments += [kw.value for kw in node.keywords
                          if kw.arg in {"src", "dst", "path", "file", "dir", "root"}]
            receiver = node.func.value if isinstance(node.func, ast.Attribute) else None
            if receiver is not None:
                arguments.append(receiver)
            for argument in arguments:
                if is_home_expression(argument):
                    findings.append(f"{name}() receives a HOME-derived path")
    return sorted(set(findings))


def _module_binding_map(tree: ast.Module) -> dict[int, str]:
    """node id -> the module-level binding name it sits inside (if any)."""
    owners: dict[int, str] = {}
    for statement in tree.body:
        for node in ast.walk(statement):
            for name in _binding_targets(statement):
                owners[id(node)] = name
    return owners


def _store_takeover_findings(files: list[Path]) -> list[str]:
    """Anything that would make this domain the owner of the old grant table.

    A reviewed refusal binding (`_TABLE_BY_KEYS`) is exempt: naming the legacy
    table is how the importer classifies a row as REJECT (matrix §3).
    """
    findings: list[str] = []
    for path in files:
        tree, error = _parse(path)
        if error:
            findings.append(error)
            continue
        owners = _module_binding_map(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in {"sqlite3", "pacthold"}:
                        findings.append(f"{path.name}: imports {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                if node.module.split(".")[0] in {"sqlite3", "pacthold"}:
                    findings.append(f"{path.name}: imports {node.module}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for token in ("grant_subagent", "revoke_subagent"):
                    if token in node.name:
                        findings.append(f"{path.name}: defines {node.name}")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if NEAR_MISS_BINDING_RE.match(owners.get(id(node), "")):
                    continue
                for token in STORE_TAKEOVER_TOKENS:
                    if token in node.value:
                        findings.append(f"{path.name}: SQL/table token {token!r}")
                for token in STORE_TAKEOVER_CASE_INSENSITIVE:
                    if token in node.value.lower():
                        findings.append(f"{path.name}: db handle {token!r}")
    return findings


# -- domain fixtures --------------------------------------------------------


class _Authority:
    def verify_principal(self, principal: str, *, server_scope: str) -> bool:
        return principal == PRINCIPAL

    def permission_ceiling(self, principal: str, server_scope: str) -> frozenset[str]:
        return GRANTS if principal == PRINCIPAL else frozenset()


class _Approvals:
    def __init__(self, approved: tuple[tuple[str, int], ...] = ()) -> None:
        self.approved = set(approved)

    def has_approved_revision(self, definition_id: str, revision: int) -> bool:
        return (definition_id, revision) in self.approved


class _ModelResolver:
    def resolve_model(self, ref):  # noqa: ANN001
        return {"family": "test-family"}


class _ToolResolver:
    def resolve_tool(self, ref):  # noqa: ANN001
        return {"label": "read only"}


class _Surface:
    """Every public entry point this domain has today, reachable from one object."""

    def __init__(self, tmp_path: Path) -> None:
        from ordessa_assets_subagents.store import DefinitionStore

        self.tmp = tmp_path
        self.private = tmp_path / "instance-private"
        self.private.mkdir(parents=True, exist_ok=True)
        self.store_root = self.private / "store"
        self.store = DefinitionStore(self.store_root)
        self.upload = self.private / "upload"
        self.upload.mkdir(exist_ok=True)
        (self.upload / "guard-reviewer.md").write_text(
            "---\nname: guard-reviewer\ndescription: Reviews diffs read-only.\n---\n\n"
            "Cite file and line for every finding.\n",
            encoding="utf-8",
        )
        # Decoys standing where a user / project native entry would live.
        self.decoy_home = tmp_path / "decoy-home"
        (self.decoy_home / ".claude" / "agents").mkdir(parents=True)
        (self.decoy_home / ".claude" / "agents" / "mine.md").write_text(
            "the user's own agent\n", encoding="utf-8")
        self.decoy_project = tmp_path / "decoy-project"
        (self.decoy_project / ".codex").mkdir(parents=True)
        (self.decoy_project / ".codex" / "config.toml").write_text(
            "[agents]\nkeep = true\n", encoding="utf-8")
        self.outside = tmp_path / "outside"
        self.outside.mkdir()
        (self.outside / "note.txt").write_text("untouched\n", encoding="utf-8")

    def service(self):
        from ordessa_assets_subagents.service import DefinitionService

        return DefinitionService(self.store, authority=_Authority())

    def revision(self, definition_id: str, body: str, *, revision: int = 1,
                 tools: tuple[str, ...] = (), permission: str | None = None,
                 retained: dict[str, Any] | None = None,
                 principal: str = PRINCIPAL):
        from ordessa_assets_subagents import dto
        from ordessa_assets_subagents.digest import bytes_digest, revision_digest

        fields: dict[str, Any] = {
            "definition_id": definition_id,
            "revision": revision,
            "content_digest": "sha256:" + "0" * 64,
            "role_body": body,
            "declared_model_ref": None,
            "tool_refs": tuple(dto.ToolRef(owner_id=name) for name in tools),
            "mcp_refs": (),
            "skill_refs": (),
            "requested_permission": permission,
            "isolation": {},
            "limits": {},
            "source": dto.SourceApproval(
                origin="user-upload", origin_ref=f"upload/{definition_id}",
                content_digest=bytes_digest(body.encode("utf-8")),
                approved_by_principal=principal, approved_at=APPROVED_AT,
            ),
            "retained_native_fields": dict(retained or {}),
        }
        provisional = dto.DefinitionRevision(**fields)
        return dto.DefinitionRevision(
            **{**fields, "content_digest": revision_digest(provisional)})

    def ceiling(self, *, tools: frozenset[str] = frozenset()):
        from ordessa_assets_subagents import ceiling as ceiling_mod
        from ordessa_assets_subagents.scopes import Principal, ServerScope

        return ceiling_mod.Ceiling(
            principal=Principal(PRINCIPAL), server_scope=ServerScope(SCOPE),
            harness_id="any", allowed_tools=GRANTS | tools,
            allowed_models=frozenset(), allowed_mcp=frozenset(),
            allowed_skills=frozenset(),
            allowed_permission_modes=frozenset({"default"}),
            allowed_isolation_keys=frozenset(),
        )

    def resolution_request(self, definition, revision, *, ceiling=None):  # noqa: ANN001
        from ordessa_assets_subagents import resolution
        from ordessa_assets_subagents.assignments import Assignment, AssignmentDecision
        from ordessa_assets_subagents.scopes import (
            DefinitionOwnership, Principal, ScopeKind, ServerScope,
        )

        ownership = DefinitionOwnership(
            definition_id=definition.definition_id,
            server_scope=ServerScope(SCOPE),
            owner_principal=Principal(PRINCIPAL),
            origin_scope=definition.origin_scope,
            origin_owner=definition.origin_owner,
        )
        assignment = Assignment(
            server_scope=ServerScope(SCOPE), principal=Principal(PRINCIPAL),
            scope_kind=ScopeKind.USER_GLOBAL, scope_id=None, harness_id="any",
            definition_id=definition.definition_id,
            decision=AssignmentDecision.ENABLE, revision=revision.revision,
        )
        return resolution.ResolutionRequest(
            server_scope=ServerScope(SCOPE), principal=Principal(PRINCIPAL),
            harness_id="claude", project_id=None, profile_id=None, session_id=None,
            session_profile_id=None, session_harness_id=None,
            definitions={definition.definition_id: definition},
            ownership={definition.definition_id: ownership},
            revisions={(definition.definition_id, revision.revision): revision},
            assignments=[assignment],
            managed_definition_ids=frozenset({definition.definition_id}),
            ceiling=ceiling,
        )

    def resolve(self, definition, revision, *, ceiling=None):  # noqa: ANN001
        from ordessa_assets_subagents import resolution

        request = self.resolution_request(definition, revision, ceiling=ceiling)
        return resolution.resolve_preview(
            request,
            approvals=_Approvals(approved=((definition.definition_id, revision.revision),)),
        )

    def drive(self) -> dict[str, Any]:
        """Run the whole public surface once and return what it produced.

        No assertions live here: a probe must be able to reuse this driver to
        show that its instruments *do* react.
        """
        from ordessa_assets_subagents import ceiling as ceiling_mod
        from ordessa_assets_subagents import decoder, references, resolution, store
        from ordessa_assets_subagents.adapters import (
            ClaudeAdapter, CodexAdapter, ManagedItem, compile_all,
        )
        from ordessa_assets_subagents.assignments import (
            Assignment, AssignmentDecision, disable_effect, pinned_revision,
            validate_assignment,
        )
        from ordessa_assets_subagents.scopes import (
            NOT_FOUND, Principal, ScopeKind, ServerScope, ViewerScope, scoped_read,
        )

        service = self.service()
        out: dict[str, Any] = {"service": service, "not_found": NOT_FOUND}
        definition = service.create_definition(
            PRINCIPAL, server_scope=SCOPE, slug="guard-reviewer",
            display_name="Guard reviewer", description="Read-only reviewer.",
            origin_scope="public", origin_owner="local", operation_key="u:create",
        )
        out["definition"] = definition
        revision = self.revision(definition.definition_id, "Cite file and line.\n")
        out["revision"] = service.save_revision(
            PRINCIPAL, revision, server_scope=SCOPE, operation_key="u:publish",
            expected_row_version=self.store.get_definition(definition.definition_id).row_version,
        )
        service.archive(
            PRINCIPAL, definition.definition_id, server_scope=SCOPE,
            operation_key="u:archive",
            expected_row_version=self.store.get_definition(definition.definition_id).row_version)
        service.restore(
            PRINCIPAL, definition.definition_id, server_scope=SCOPE,
            operation_key="u:restore",
            expected_row_version=self.store.get_definition(definition.definition_id).row_version)
        out["clone"] = service.clone(
            PRINCIPAL, definition.definition_id, server_scope=SCOPE,
            operation_key="u:clone",
            expected_row_version=self.store.get_definition(definition.definition_id).row_version,
            slug="guard-reviewer-copy", display_name="Guard reviewer copy",
        )
        preview = service.import_preview("upload", import_root=self.private)
        out["preview"] = preview
        out["plans"] = service.import_plan(
            PRINCIPAL, preview.preview_id, server_scope=SCOPE,
            selects=["guard-reviewer.md"])
        out["imported"] = service.approve_import(
            preview.preview_id, principal=PRINCIPAL, server_scope=SCOPE,
            selects=["guard-reviewer.md"], operation_key="u:approve-import")
        out["documents"] = service.list_definitions(include_archived=True)
        out["enabled"] = self.store.enabled_definitions()
        out["walk"] = store.walk_bounded(self.upload)
        out["decoded"] = decoder.decode_import_document(
            (self.upload / "guard-reviewer.md").read_text(encoding="utf-8"))

        item = ManagedItem(definition=definition, revision=out["revision"])
        claude = ClaudeAdapter()
        # Targets and ownership are INJECTED, exactly as a carrier grants them:
        # one host-issued private-generation TargetHandle per brand, one
        # host-issued IntentSource for this facet (SR-1b FINAL answers).
        claude_ctx = claude_context()
        codex_ctx = codex_context()
        source = host_source(definition.definition_id)
        out["claude_context"], out["claude_source"] = claude_ctx, source
        staged: dict[str, bytes] = {}
        out["staged"] = staged
        out["claude_intents"] = claude.compile(
            claude_ctx, [item], source,
            stage_content=lambda reference, data: staged.__setitem__(reference, data))
        out["claude_assessment"] = claude.assess(claude_ctx)
        out["compile_all"] = compile_all(
            [item], codex_ctx, source,
            render=lambda one: f"# {one.native_name}\n", native_names=frozenset())
        try:
            out["codex_intents"] = CodexAdapter().compile(
                codex_ctx, [item], host_source("def-codex"))
        except Exception as exc:  # noqa: BLE001 - a documented refusal is expected
            out["codex_refusal"] = exc

        out["references"] = references.resolve_references(
            out["revision"], models=_ModelResolver(), tools=_ToolResolver())
        out["admitted"] = ceiling_mod.admit(out["revision"], self.ceiling())

        assignment = Assignment(
            server_scope=ServerScope(SCOPE), principal=Principal(PRINCIPAL),
            scope_kind=ScopeKind.PROJECT, scope_id="project-a", harness_id="any",
            definition_id=definition.definition_id, decision=AssignmentDecision.ENABLE,
            revision=out["revision"].revision,
        )
        approvals = _Approvals(approved=((definition.definition_id, 1),))
        out["validated"] = validate_assignment(assignment, approvals)
        out["pinned"] = pinned_revision(assignment, definition)
        out["disabled"] = disable_effect(
            Assignment(
                server_scope=ServerScope(SCOPE), principal=Principal(PRINCIPAL),
                scope_kind=ScopeKind.USER_GLOBAL, scope_id=None, harness_id="any",
                definition_id="def_nativeonly0000000000",
                decision=AssignmentDecision.DISABLE,
            ),
            managed_definition_ids=frozenset({definition.definition_id}))
        effective = self.resolve(definition, out["revision"], ceiling=self.ceiling())
        out["effective"] = effective
        out["snapshot"] = resolution.build_snapshot(
            self.resolution_request(definition, out["revision"], ceiling=self.ceiling()),
            effective, approvals=approvals, runtime_generation="gen-0001",
            profile_revision=1, adapter_generation="claude:gen-0001")
        viewer = ViewerScope(
            principal=Principal(OTHER_PRINCIPAL), server_scope=ServerScope(SCOPE),
            project=None, profile_id=None, session_id=None, session_profile_id=None,
            session_harness_id=None, harness_id="claude")
        out["foreign_read"] = scoped_read(None, viewer)
        return out


@pytest.fixture
def surface(tmp_path: Path) -> _Surface:
    return _Surface(tmp_path)


@pytest.fixture
def writes(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    recorder = _Recorder()
    recorder.install(monkeypatch)
    return recorder


# -- FR08: no spawn, no network, no model call ------------------------------


def test_fr08_the_domain_surface_never_spawns_connects_or_calls_a_model(
        surface, monkeypatch):
    tripwires = _install_tripwires(monkeypatch)
    results = surface.drive()
    assert tripwires.installed, "no entry point was actually wired to a tripwire"
    assert tripwires.fired == [], (
        "FR08: the business surface reached a process / socket / HTTP entry "
        "point: " + str(tripwires.fired))
    # the drive really did work — otherwise "no call happened" proves nothing
    assert results["definition"].definition_id
    assert results["revision"].content_digest.startswith("sha256:")
    assert results["claude_intents"].intents, results["claude_intents"]
    assert results["effective"].resolved, results["effective"]
    assert results["imported"], results["imported"]
    assert (surface.store_root / "definitions").is_dir()


def test_fr08_the_tripwires_are_live(monkeypatch):
    tripwires = _install_tripwires(monkeypatch)
    assert tripwires.installed, "nothing was installed"
    blind = [label for label in tripwires.installed if not tripwires.is_tripwire(label)]
    assert blind == [], f"not actually replaced: {blind}"
    for label in sorted(tripwires.PROBES):
        if label not in tripwires.installed:
            continue
        with pytest.raises(Tripwire):
            tripwires.call(label)
    assert tripwires.fired, "the probes ran but nothing was recorded"


def test_fr08_no_source_module_imports_spawn_or_network_support():
    offenders: list[str] = []
    files = _src_files()
    assert files, "no source found — the guard would be blind"
    for path in files:
        tree, error = _parse(path)
        if error:
            offenders.append(error)
            continue
        offenders.extend(
            f"{path.name}: {name}"
            for name in _execution_module_hits(path.read_text(encoding="utf-8")))
    assert offenders == [], (
        "FR08: adapters and the resolver are pure — a spawn or socket import "
        "here would put process control inside the definition domain:\n"
        + "\n".join(offenders))
    assert [p for p in files if "adapters" in p.parts], (
        "adapters/** is missing; the FR08 wording would be unverifiable")


def test_fr08_the_execution_module_scan_is_capable():
    for source, prefix in (
        ("import subprocess\n", "subprocess"),
        ("from subprocess import run\n", "subprocess"),
        ("import socket\n", "socket"),
        ("import urllib.request\n", "urllib"),
        ("from http.client import HTTPConnection\n", "http"),
        ("import asyncio\n", "asyncio"),
        ("import shlex\n", "shlex"),
    ):
        assert any(hit.startswith(prefix) for hit in _execution_module_hits(source)), source
    assert _execution_module_hits("import re\nfrom .. import errors\n") == []


def test_fr08_the_service_owns_no_native_writer():
    """contracts.md §C1: the definition service never writes a native file."""
    files = _src_files()
    assert files, "no source found — the guard would be blind"
    findings: list[str] = []
    for path in files:
        tree, error = _parse(path)
        if error:
            findings.append(error)
            continue
        findings.extend(f"{path.name}: {hit}" for hit in
                        _native_write_literal(path.read_text(encoding="utf-8")))
    assert findings == [], "\n".join(findings)


def test_fr08_the_native_write_scan_is_capable():
    assert _native_write_literal('Path("~/.claude/agents/x.md").write_text("y")')
    assert _native_write_literal('open("/home/u/.codex/agents/x.toml", "w")')
    assert _native_write_literal("os.replace('a', '/home/u/.claude/settings.json')")
    assert _native_write_literal("shutil.rmtree('/home/u/.codex')")
    assert _native_write_literal("p.mkdir('/home/u/.pi/agents')")
    assert _native_write_literal("shutil.copy(src, '/etc/passwd')")
    assert _native_write_literal("shutil.rmtree(staging_dir)") == []
    assert _native_write_literal("path.parent.mkdir(parents=True, exist_ok=True)") == []
    assert _native_write_literal("os.chmod(staged, 0o644)") == []


# -- FR09: managed content never addresses a native location ----------------


def test_fr09_no_path_shape_reaches_a_contract_target_or_field():
    """FR09 re-expressed on the real vocabulary (was: `TargetSlot` members had
    to be `private-generation-*` tokens).

    The old enum made a native location *unrepresentable by construction*. The
    published contract is laxer — `TargetHandle`/`FieldPath` police only
    blankness, `""`, `.`/`..` and separators — so the same prohibition is now
    pinned on three layers, all of them real:

    1. C0's own constructors refuse the shapes they do refuse (opaque handles
       are not blank/padded ids; field paths are not `""`/`.`/`..`/`/`/`\\`;
       a content name is relative and normalized);
    2. Q3's token layer refuses what C0 accepts but this domain must never
       accept (`~…`, absolute paths, URLs, shell bytes, control bytes), so a
       host path cannot ride in as a single dot-containing segment;
    3. the compile seam only ever *copies* a granted handle, so nothing here
       can name a target at all.
    """
    from ordessa_assets_subagents import errors
    from ordessa_assets_subagents.adapters import intents

    # -- (1) the published constructors' own refusals -------------------------
    for blank in ("", "  ", " x", "x "):
        with pytest.raises(ContractError):
            TargetHandle(blank, 1)
        with pytest.raises(ContractError):
            IntentSource("", "item", "v1")
    with pytest.raises(ContractError):
        TargetHandle("valid-handle", -1)          # a generation is never negative
    for bad in ("", ".", "..", "a/b", "a\\b", "/abs", "~/.claude/agents"):
        with pytest.raises(ContractError):
            FieldPath((bad,))
    with pytest.raises(ContractError):
        FieldPath(())                             # an empty path is not a field
    with pytest.raises(ContractError):
        FieldPath(("ok", "", "also-ok"))          # one bad segment poisons it
    for bad_name in ("/etc/passwd", "agents//x.md", "agents/./x.md",
                     "agents/../escape.md", "agents\\x.md", ""):
        with pytest.raises(ContractError):
            MountContent(source=host_source(), target=TargetHandle("h", 1),
                         relative_name=bad_name,
                         immutable_content_ref=_content_ref(b"x"),
                         mode="read-only")
        with pytest.raises(ContractError):
            RemoveOwnedContent(source=host_source(), target=TargetHandle("h", 1),
                               relative_name=bad_name)

    # -- (2) Q3's stricter token layer over the same shapes -------------------
    blind: list[str] = []
    for value in PATH_SHAPED_VALUES + ("~claude", "agents/../../etc", "a b",
                                       "a;b", "$(x)", "--flag", "x\ny"):
        try:
            intents.safe_field_path((value,))
        except (errors.DomainError, ContractError):
            pass
        else:
            blind.append(f"safe_field_path accepted {value!r}")
        try:
            intents.mount_relative_name(value)
        except (errors.DomainError, ContractError):
            pass
        else:
            blind.append(f"mount_relative_name accepted native_name {value!r}")
    assert blind == [], "the intent-token guard is blind: " + "; ".join(blind)
    # capability: the same helpers accept the legal shapes they exist to allow
    assert intents.safe_field_path(("agents", "model")).segments == ("agents", "model")
    assert intents.mount_relative_name("guard-reviewer") == "agents/guard-reviewer.md"

    # -- (3) the grant prefix is fixed, and only one prefix -------------------
    from ordessa_assets_subagents.adapters import ClaudeAdapter
    from ordessa_assets_subagents.adapters import claude as claude_mod

    assert intents.MOUNT_DIRECTORY == GRANT_PREFIX, intents.MOUNT_DIRECTORY
    handle_id = claude_mod.CLAUDE_GENERATION_HANDLE
    assert not os.path.isabs(handle_id)
    for banned in ("~", "/", "\\", ".claude", ".codex", ".pi", "HOME"):
        assert banned not in handle_id, (handle_id, banned)
    assert handle_id.startswith("assets-native-subagents-"), handle_id
    # the one grant this domain holds: a directory claim under `agents` on its
    # own generation handle — no file claim, no absolute path, no second prefix
    assert ClaudeAdapter().descriptor.claims == (
        FieldClaim("directory", handle_id, (GRANT_PREFIX,)),
    ), ClaudeAdapter().descriptor.claims


def _content_ref(data: bytes) -> ContentRef:
    return ContentRef(reference=hashlib.sha256(data).hexdigest(),
                      sha256=hashlib.sha256(data).hexdigest(), size=len(data))


def test_fr09_every_produced_intent_carries_the_injected_handle_unchanged(
        surface):
    """FR09 + the anti-forgery rule, on real intents.

    Before: every emittable intent had to carry a `TargetSlot` from a closed
    private-generation enum, and a path-shaped value could not be a target.
    Now: (a) each produced intent carries the *injected* `TargetHandle`
    unchanged (identity, not a copy with a re-pointed id), (b) no intent can be
    built from an absolute or home-relative path — the refusal happens before
    any intent object exists, (c) an `IntentSource` naming a foreign facet is
    refused, because ownership is granted by the carrier and this domain emits
    `assets.native-subagents` intents only (§C3 「注册 owner 由宿主授予」).
    """
    from ordessa_assets_subagents import errors
    from ordessa_assets_subagents.adapters import ClaudeAdapter, ManagedItem, intents

    handle = TargetHandle(ClaudeAdapter().descriptor.claims[0].target_id, 11)
    context = claude_context(handle=handle)
    source = host_source("def-prohibition")
    results = surface.drive()
    item = ManagedItem(definition=results["definition"], revision=results["revision"])

    produced = [ClaudeAdapter().compile(context, [item], source),
                compile_all_probe([item], context, source)]
    # The other intents this domain can legitimately emit, built through its own
    # builders with the same injected source and handles: the closedness scan
    # below covers all four kinds, not just the mount (the old suite pinned
    # MountContent / RemoveOwnedContent / rebuild-class / InvokeSubagent alike).
    env_handle = TargetHandle("assets-native-subagents-claude-environment", 11)
    extras = (
        intents.build_remove(source, handle, native_name="guard-reviewer"),
        intents.build_secret_binding(source, env_handle, slot="model-api-key",
                                     secret_ref="secret-ref-1"),
        intents.build_invoke_action(source, native_name="guard-reviewer",
                                    action_id="native-subagent.invoke",
                                    schema_version="v1",
                                    invokable_evidence=("acp-control-observation-1",)),
    )
    emitted = [intent for one in produced for intent in one.intents] + list(extras)
    assert emitted, "compile produced no intent — every closedness claim below is blind"

    for intent in emitted:
        # (a) ownership and target are the injected objects, unchanged. The
        # carrier-granted source is stamped on every intent; `InvokeAction` is
        # the one kind with no target, so the target check is by attribute.
        assert intent.source is source, intent
        if getattr(intent, "target", None) is not None:
            expected = env_handle if isinstance(intent, BindSecret) else handle
            assert intent.target is expected, intent
            assert intent.target.generation == expected.generation, intent
        # every string inside it is either a clean token or the one managed
        # relative name, and nothing at all is a host location
        for location, text in strings_under(intent):
            leaf = field_leaf(location)
            assert not os.path.isabs(text), (intent, location, text)
            assert not text.startswith("~"), (intent, location, text)
            assert "\\" not in text, (intent, location, text)
            assert ".." not in text.split("/"), (intent, location, text)
            assert not any(ord(ch) < 0x20 or ch.isspace() for ch in text), \
                (intent, location, text)
            if leaf in RELATIVE_NAME_FIELDS:
                assert text.startswith(f"{GRANT_PREFIX}/"), (intent, location, text)
                assert len(text.split("/")) == 2, (intent, location, text)
            else:
                assert "/" not in text, (intent, location, text)
        # a produced mount is content, never code (see the mode guard below)
        if isinstance(intent, MountContent):
            assert intent.mode == "read-only", intent
            assert intents.mount_native_name(intent) == item.native_name

    # (b) no intent can be *built* from an absolute or home-relative path
    hostile = list(PATH_SHAPED_VALUES) + ["agents/../../.claude", "agents/ x.md"]
    caught = 0
    for hostile_index, value in enumerate(hostile):
        for attempt in (
            # a path-shaped handle cannot be selected, even when the host hands
            # it over: the adapter copies a granted handle, it does not trust a name
            lambda v=value: intents.select_content_target(
                claude_context(handle=TargetHandle(v, 1)), harness_id="claude"),
            lambda v=value: intents.build_mount(source, handle,
                                                native_name=v, content="x"),
            lambda v=value: intents.build_remove(source, handle, native_name=v),
            lambda v=value: intents.build_secret_binding(source, env_handle,
                                                         slot=v, secret_ref="ref"),
            lambda v=value: intents.build_secret_binding(source, env_handle,
                                                         slot="slot", secret_ref=v),
            lambda v=value: intents.build_invoke_action(source, native_name=v,
                                                        action_id="a", schema_version="v1",
                                                        invokable_evidence=("ev",)),
            lambda v=value: intents.build_invoke_action(source, native_name="x",
                                                        action_id=v, schema_version="v1",
                                                        invokable_evidence=("ev",)),
            lambda v=value: intents.safe_field_path((v,)),
            # ... and the whole collection refuses before the first intent exists
            lambda v=value: compile_all_probe(
                [ManagedItem(dto_probe(f"slug-{hostile_index}", v),
                             results["revision"])],
                context, source),
        ):
            with pytest.raises((errors.DomainError, ContractError, TypeError)):
                attempt()
            caught += 1
    assert caught == len(hostile) * 9, caught

    # the owner question is structural, not conventional: `IntentSet` has no
    # target and no owner field at all, so the old `IntentSet(target=…)`
    # forgery has no shape left to take.
    assert {f.name for f in dataclasses.fields(IntentSet)} == {"intents"}
    with pytest.raises(ContractError):
        IntentSet((host_source(),))               # not an intent kind
    with pytest.raises(ContractError):
        IntentSet(("agents/guard-reviewer.md",))  # a path is not an intent

    # the old typed refusal — "a path cannot be the target", TARGET_CONFLICT —
    # now belongs to the admission seam, and it still names the same code: a
    # raw path is not a context, and no context may be invented from a name.
    for raw in ("/home/u/.claude/agents", "~/.codex", "../escape", "https://x.test/a"):
        with pytest.raises(errors.DomainError) as not_a_context:
            intents.validate_context(raw)
        assert not_a_context.value.code == errors.TARGET_CONFLICT, raw
        with pytest.raises(errors.DomainError) as bad_compile:
            compile_all_probe([item], raw, source)
        assert bad_compile.value.code == errors.TARGET_CONFLICT, raw

    # and the deleted `SetRebuildClassOption` keeps its own refusal: the
    # published vocabulary has no rebuild-class intent, so asking for one —
    # with a clean key, a path-shaped key or a nested path value — is refused
    # rather than mapped onto an in-place `SetField` (SR-12 G-2).
    for key in ("agents", "setting_sources", "/home/u/.claude", "~/.codex",
                "x; rm -rf", 7, None):
        with pytest.raises(errors.DomainError):
            intents.build_rebuild_class_option(key, True)
    with pytest.raises(errors.DomainError):
        intents.build_rebuild_class_option("agents", ("x", "/home/u/.claude/agents"))

    # (c) anti-forgery: a foreign facet_id never passes, whatever the item id.
    # The choke point is `validate_source`, which every compile face calls; the
    # per-item builders are dumb constructors, so the face is what is probed.
    with pytest.raises(ContractError):
        host_source("def-victim", facet_id="")   # not even a legal source shape
    for foreign in ("assets.skills", "profile.editor", "chat.input", "harness.runtime",
                    "assets.native-subagents.extra", "assets_native_subagents",
                    "ASSETS.NATIVE-SUBAGENTS"):
        forged = host_source("def-victim", facet_id=foreign)
        assert forged.facet_id == foreign        # the shape is legal in the DTO…
        with pytest.raises(errors.DomainError) as info:
            intents.validate_source(forged)
        assert info.value.code == errors.TARGET_CONFLICT, foreign
        with pytest.raises(errors.DomainError):
            compile_all_probe([item], context, forged)
        with pytest.raises(errors.DomainError):
            ClaudeAdapter().compile(context, [item], forged)

    # Why the face is the choke point: a *direct* constructor call with a
    # foreign source is legal upstream (the DTO has no facet whitelist), so the
    # refusal must happen before an intent object exists. Pinned both ways:
    # the contract accepts it, this domain's compile path never emits it.
    smuggled = RemoveOwnedContent(source=host_source("def-victim",
                                                      facet_id="assets.skills"),
                                  target=handle, relative_name="agents/x.md")
    assert smuggled.source.facet_id == "assets.skills"
    for one in produced:
        assert all(i.source.facet_id == source.facet_id for i in one.intents), one

    # a look-alike source is refused too: ownership is by type identity
    class LookAlikeSource:
        facet_id = intents.FACET_ID
        item_id = "def-victim"
        contribution_version = "v1"

    with pytest.raises(errors.DomainError) as lookalike:
        intents.validate_source(LookAlikeSource())
    assert lookalike.value.code == errors.TARGET_CONFLICT

    # and a target that was never granted cannot be invented either
    with pytest.raises(errors.DomainError) as no_target:
        intents.select_content_target(claude_context(targets=()), harness_id="claude")
    assert no_target.value.code == errors.TARGET_CONFLICT
    with pytest.raises(errors.DomainError) as two_targets:
        intents.select_content_target(
            claude_context(targets=(
                TargetDescriptor(handle, "directory", "content", "instance",
                                 ((GRANT_PREFIX,),)),
                TargetDescriptor(TargetHandle("assets-native-subagents-other", 2),
                                 "directory", "content", "instance",
                                 ((GRANT_PREFIX,),)))),
            harness_id="claude")
    assert two_targets.value.code == errors.TARGET_CONFLICT


def compile_all_probe(items, context: AdapterContext, source: IntentSource) -> IntentSet:
    """`compile_all` with the render the guards do not care about."""
    from ordessa_assets_subagents.adapters import compile_all

    return compile_all(items, context, source,
                       render=lambda one: f"# {one.native_name}\n")


def dto_probe(definition_id: str, slug: str):
    """A definition whose *slug* is the hostile value (name → relative path)."""
    from ordessa_assets_subagents import dto

    return dto.AgentDefinition(
        server_scope=SCOPE, definition_id=definition_id, slug=slug,
        display_name="Hostile slug", description="Refused before any intent.",
        origin_scope="public", origin_owner="local")


def test_fr09_an_executable_mount_is_unreachable_from_this_domain(surface):
    """FR14/G05 policy, now against a real `Literal["read-only","executable"]`.

    `MountContent.mode` is a genuine two-value mode and the published
    constructor happily accepts `"executable"`, so "a subagent definition is
    content, never code" can no longer be expressed by the shape of a local
    enum: it is pinned as (a) every mount this domain compiles is `read-only`,
    (b) no builder or compile face in this domain takes a mode parameter at all
    — asking for one is a `TypeError`, so there is no route to `executable`, and
    (c) a mode outside the closed literal is a contract error.
    """
    from ordessa_assets_subagents.adapters import ClaudeAdapter, ManagedItem, intents

    results = surface.drive()
    item = ManagedItem(definition=results["definition"], revision=results["revision"])
    source = host_source(item.definition.definition_id)
    produced = ClaudeAdapter().compile(claude_context(), [item], source)
    mounts = [i for i in produced.intents if isinstance(i, MountContent)]
    assert mounts, "no mount was produced — the mode guard below is blind"
    assert {m.mode for m in mounts} == {"read-only"}, [m.mode for m in mounts]
    # the drive's own compile faces are read-only too, not just this one
    for key in ("claude_intents", "compile_all"):
        assert {m.mode for m in results[key].intents if isinstance(m, MountContent)} \
            == {"read-only"}, key

    # a directly-built read-only mount works, and the literal is closed
    intents.build_mount(source, TargetHandle("assets-native-subagents-h", 1),
                        native_name="guard-reviewer", content="# x\n")
    for bad_mode in ("execute", "rw", "", "READ-ONLY", "read_only", None, 0o755):
        with pytest.raises(ContractError):
            MountContent(source=source, target=TargetHandle("h", 1),
                         relative_name="agents/x.md",
                         immutable_content_ref=_content_ref(b"x"), mode=bad_mode)
    # Registered asymmetry (api-requests.md §SR-1b policy consequence): the
    # published constructor *does* accept "executable" — nothing in C0's type
    # stops it. That is precisely why the two checks below are load-bearing for
    # Q3 rather than decorative: the domain's own face must never ask.
    assert MountContent(source=source, target=TargetHandle("h", 1),
                        relative_name="agents/x.md",
                        immutable_content_ref=_content_ref(b"x"),
                        mode="executable").mode == "executable"

    # (b) no knob exists to ask for it — signature-level, so a future
    # "just thread the mode through" change turns this red instead of silently
    # gaining an executable path.
    from ordessa_assets_subagents.adapters import compile_all as domain_compile_all

    handle = TargetHandle(ClaudeAdapter().descriptor.claims[0].target_id, 1)
    for face, label, call in (
        (intents.build_mount, "build_mount",
         lambda **kw: intents.build_mount(source, handle, native_name="x",
                                          content="# x\n", **kw)),
        (domain_compile_all, "compile_all",
         lambda **kw: domain_compile_all([item], claude_context(), source,
                                         render=lambda one: "# x\n", **kw)),
        (ClaudeAdapter().compile, "ClaudeAdapter.compile",
         lambda **kw: ClaudeAdapter().compile(claude_context(), [item], source, **kw)),
    ):
        parameters = inspect.signature(face).parameters
        assert "mode" not in parameters, f"{label} grew a mode parameter: {parameters}"
        with pytest.raises(TypeError):
            call(mode="executable")


def test_fr09_declaration_fields_refuse_every_host_path_shape(surface):
    from ordessa_assets_subagents import decoder, dto, errors

    definition_id = "def_0123456789abcdef01234567"
    blind: list[str] = []
    refused = 0
    for value in PATH_SHAPED_VALUES:
        probes = {
            "tool_refs.owner_id": lambda v=value: decoder.validate_revision(
                surface.revision(definition_id, "body\n", tools=(v,))),
            "source.origin_ref": lambda v=value: decoder.validate_revision(
                dto.DefinitionRevision(
                    **{**dataclasses.asdict(surface.revision(definition_id, "body\n")),
                       "source": dto.SourceApproval(
                           origin="user-upload", origin_ref=v,
                           content_digest="sha256:" + "a" * 64,
                           approved_by_principal=PRINCIPAL, approved_at=APPROVED_AT)})),
            "definition_id": lambda v=value: decoder.validate_definition(
                dto.AgentDefinition(server_scope=SCOPE, definition_id=v, slug="s",
                                    display_name="D", description="d",
                                    origin_scope="public", origin_owner="local")),
            "origin_owner": lambda v=value: decoder.validate_definition(
                dto.AgentDefinition(server_scope=SCOPE, definition_id=definition_id,
                                    slug="s", display_name="D", description="d",
                                    origin_scope="public", origin_owner=v)),
        }
        for name, probe in probes.items():
            try:
                probe()
            except errors.DomainError:
                refused += 1
            except Exception as exc:  # noqa: BLE001
                blind.append(f"{name}:{value} -> {type(exc).__name__}: {exc}")
            else:
                blind.append(f"{name}:{value} was ACCEPTED")
    assert blind == [], "the path-shape guard is blind: " + "; ".join(blind)
    assert refused == len(PATH_SHAPED_VALUES) * len(
        ("tool_refs.owner_id", "source.origin_ref", "definition_id", "origin_owner"))

    # the store's own path builders refuse them too
    for value in PATH_SHAPED_VALUES:
        with pytest.raises(errors.DomainError):
            surface.store.definition_dir(value)


def test_fr09_writes_stay_inside_the_instance_private_root(surface, writes, monkeypatch):
    tripwires = _install_tripwires(monkeypatch)
    before = {
        "home": _snapshot(surface.decoy_home),
        "project": _snapshot(surface.decoy_project),
        "outside": _snapshot(surface.outside),
    }
    writes.reset()
    results = surface.drive()
    strays = writes.outside(surface.store_root)
    assert writes.writes(), (
        "the recorder saw no write at all during the drive, so the containment "
        "check below is blind")
    assert strays == [], (
        "FR09: every byte this domain writes belongs to its private store; "
        f"these write attempts did not: {strays}")
    assert results["definition"].definition_id, "the drive did not run, so this is blind"
    assert tripwires.fired == []
    after = {
        "home": _snapshot(surface.decoy_home),
        "project": _snapshot(surface.decoy_project),
        "outside": _snapshot(surface.outside),
    }
    changed = {key: (before[key], after[key]) for key in before if before[key] != after[key]}
    assert changed == {}, f"a user or project native location changed: {changed}"


def test_fr09_the_write_instruments_do_react(surface, writes):
    """Capability probe: the recorder and the tree snapshot must both notice a
    real write, or the containment assertions above are meaningless."""
    writes.reset()
    stray = surface.decoy_home / ".claude" / "agents" / "overwritten.md"
    stray.write_text("clobbered\n", encoding="utf-8")
    assert writes.under(surface.decoy_home), (
        "the recorder cannot see a native-directory write")
    assert writes.outside(surface.store_root), "the stray filter cannot see it either"
    before_home = _snapshot(surface.decoy_home)
    assert before_home[".claude/agents/overwritten.md"].startswith("file:")

    writes.reset()
    before_outside = _snapshot(surface.outside)
    (surface.outside / "second.txt").write_text("new\n", encoding="utf-8")
    assert _snapshot(surface.outside) != before_outside, (
        "the tree snapshot cannot see a newly created file")


def test_fr09_store_path_containment_predicate_is_not_blind(surface):
    accepted: list[str] = []
    refused: list[str] = []
    for candidate in ("", ".", "..", "../x", "/etc/passwd", "~/.claude/agents",
                      "a/b", "a\\b", ".hidden", "def_" + "x" * 200):
        try:
            path = surface.store.definition_dir(candidate)
        except Exception as exc:  # noqa: BLE001 - a typed refusal is required
            assert type(exc).__name__ == "DomainError", (candidate, type(exc).__name__)
            refused.append(candidate)
            continue
        accepted.append(candidate)
        assert _is_under(os.path.realpath(str(path)),
                         os.path.realpath(surface.store_root)), (candidate, path)
    assert accepted == [], f"these ids reach a path: {accepted}"
    assert len(refused) == 10
    assert not _is_under("/home/u/project/.claude", "/tmp/instance/store")
    assert _is_under("/tmp/instance/store/definitions/x", "/tmp/instance/store")


# -- FR11: an absent contributor must not break this domain ----------------


def test_fr11_resolution_survives_without_a_permissions_contributor(surface):
    from ordessa_assets_subagents import errors

    results = surface.drive()
    definition, revision = results["definition"], results["revision"]
    with pytest.raises(errors.DomainError) as info:
        surface.resolve(definition, revision)  # ceiling simply not passed
    assert info.value.code == errors.ADAPTER_MISSING, info.value
    # positive control: the same input WITH the authority resolves, so the
    # refusal is the absent contributor and not a fixture that never worked
    effective = surface.resolve(definition, revision, ceiling=surface.ceiling())
    assert [item.native_name for item in effective.resolved] == ["guard-reviewer"]


def test_fr11_unresolved_references_are_diagnostics_not_crashes(surface):
    from ordessa_assets_subagents import errors, references

    results = surface.drive()
    revision = surface.revision(results["definition"].definition_id, "Cite file.\n",
                                tools=("Read",))
    quiet = references.resolve_references(revision)  # no resolver injected at all
    assert quiet.unresolved
    assert {d.code for d in quiet.diagnostics} == {errors.REFERENCE_UNRESOLVED}
    assert quiet.references == ()
    with pytest.raises(errors.DomainError) as info:
        references.resolve_references(revision, fail_fast=True)
    assert info.value.code == errors.REFERENCE_UNRESOLVED
    filled = references.resolve_references(revision, tools=_ToolResolver())
    assert not filled.unresolved, filled.diagnostics
    assert [ref.owner_id for ref in filled.references] == ["Read"]


def test_fr11_a_missing_approval_authority_is_a_typed_refusal(surface):
    from ordessa_assets_subagents import ceiling as ceiling_mod, errors
    from ordessa_assets_subagents.assignments import (
        Assignment, AssignmentDecision, validate_assignment,
    )
    from ordessa_assets_subagents.scopes import Principal, ScopeKind, ServerScope

    results = surface.drive()
    definition = results["definition"]
    revision = surface.revision(definition.definition_id, "Cite file.\n")
    with pytest.raises(errors.DomainError) as info:
        ceiling_mod.admit(revision, None)
    assert info.value.code == errors.ADAPTER_MISSING

    assignment = Assignment(
        server_scope=ServerScope(SCOPE), principal=Principal(PRINCIPAL),
        scope_kind=ScopeKind.USER_GLOBAL, scope_id=None, harness_id="any",
        definition_id=definition.definition_id, decision=AssignmentDecision.ENABLE,
        revision=revision.revision,
    )
    with pytest.raises(errors.DomainError) as denied:
        validate_assignment(assignment, _Approvals(approved=()))
    assert denied.value.code == errors.ASSIGNMENT_CONFLICT
    ok = validate_assignment(
        assignment, _Approvals(approved=((definition.definition_id, revision.revision),)))
    assert ok.definition_id == definition.definition_id


def test_fr11_content_and_store_work_with_no_contributor_at_all(surface):
    """Settings / Profile / Chat are other facets' objects; the content library,
    the store and the importer must not need them to work (FR11, G15)."""
    from ordessa_assets_subagents.adapters import intents

    results = surface.drive()
    assert results["documents"], results["documents"]
    assert results["enabled"], results["enabled"]
    assert results["imported"], results["imported"]
    assert results["plans"], results["plans"]
    assert results["snapshot"].snapshot_digest.startswith("sha256:")
    # the compile face needs a granted handle and nothing else: no Profile, no
    # Chat, no Settings object reached it, and the intents it produced still
    # point at the injected private-generation handle only (FR09 again, from
    # the FR11 direction — an absent contributor cannot widen the target set)
    compiled = results["claude_intents"].intents
    assert compiled and all(type(i) is intents.MountContent for i in compiled), compiled
    granted = results["claude_context"].targets[0].handle
    assert all(i.target is granted for i in compiled), granted
    assert results["foreign_read"] is results["not_found"]


def test_fr11_missing_profile_or_chat_imports_cannot_break_the_domain():
    """No module of this domain may import a Profile / Chat / Settings owner;
    their absence is therefore proven structurally, not only at call time."""
    files = _src_files()
    assert files, "no source found — the guard would be blind"
    findings: list[str] = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        tree, error = _parse(path)
        if error:
            findings.append(error)
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for name in names:
                if name.split(".")[0] in {
                    "ordessa_server", "ordessa_server_compat", "ordessa_harness",
                    "ordessa_server_product", "pacthold",
                }:
                    findings.append(f"{path.name}: imports {name}")
    assert findings == [], "\n".join(findings)


# -- FR12: the legacy dispatch vocabulary is unreachable --------------------


def test_fr12_no_legacy_dispatch_symbol_is_reachable_from_the_domain():
    files = _src_files()
    assert files, "no source found — the guard would be blind"
    hard, tolerated = _legacy_symbol_findings(files)
    assert hard == [], (
        "FR12 / G10: the old dispatcher's vocabulary (grant edges, roster, "
        "run/list_subagents, cycle + turn/timeout policy, the synthesised MCP "
        "entry, the grant table) must not be copied into this domain:\n"
        + "\n".join(hard))
    assert len(tolerated) <= len(LEGACY_NEAR_MISS), tolerated
    for entry in tolerated:
        assert "refusal binding" in entry, entry


def test_fr12_the_domain_defines_no_roster_cycle_or_limit_control():
    files = _src_files()
    assert files, "no source found — the guard would be blind"
    offenders = _dispatch_definitions(files)
    assert offenders == [], (
        "FR12: this domain owns no second dispatch system — no roster "
        "resolution, no cycle detection, no turn/timeout budget, no "
        "delegation/dispatch runner may be defined here:\n"
        + "\n".join(sorted(set(offenders))))


def test_fr12_the_old_grant_table_is_never_the_definition_store():
    """I-4 / matrix §3: the grant table keeps its owner; this domain is
    file-backed and owns no SQL, no DB handle and no grant mutation."""
    files = _src_files()
    assert files, "no source found — the guard would be blind"
    findings = _store_takeover_findings(files)
    assert findings == [], (
        "the legacy authorization edge must never be repurposed as this "
        "plugin's definition store:\n" + "\n".join(findings))


def test_fr12_the_legacy_symbol_scan_is_capable():
    legacy = (
        "def grant_edges(rows):\n    return []\n"
        "def resolve_roster(rows, grants):\n    return []\n"
        "def has_delegation(edges, profile_id):\n    return True\n\n"
        "def check_cycle(chain):\n    return None\n"
        "def tool_definitions(*, roster, include_run=True):\n    return []\n"
        "def validate_run_arguments(args):\n    return []\n"
        "def run_subagent(name):\n    return None\n"
        "def list_subagents():\n    return []\n\n"
        "TABLE = 'server_subagent_grants'\n"
        "ENTRY = 'agentbox-subagents'\n"
        "def _roster_view():\n    return 0\n\n"
        "def _timeout_budget():\n    return 0\n\n"
        "class DelegationRunner:\n    pass\n\n"
        "def call_run_subagent():\n    return run_subagent('x')\n\n"
        "def via_kw():\n    return sorted([], key=check_cycle)\n"
    )
    with tempfile.TemporaryDirectory() as directory:
        fake = Path(directory) / "legacy.py"
        fake.write_text(legacy, encoding="utf-8")
        hard, tolerated = _legacy_symbol_findings([fake])
        definitions = _dispatch_definitions([fake])
    joined = "\n".join(hard)
    for symbol in LEGACY_FORBIDDEN_SYMBOLS:
        assert symbol in joined, f"the symbol scan misses {symbol}"
    assert tolerated == [], tolerated
    for name in ("grant_edges", "resolve_roster", "check_cycle", "_roster_view",
                 "_timeout_budget", "DelegationRunner"):
        assert any(name in entry for entry in definitions), (
            f"the dispatcher-shape scan misses {name}")
    # and it does not fire on this domain's own vocabulary
    assert _legacy_symbol_findings(_src_files())[0] == []


def test_fr12_the_store_takeover_scan_is_capable():
    with tempfile.TemporaryDirectory() as directory:
        fake = Path(directory) / "sql.py"
        fake.write_text(
            "import sqlite3\n"
            "from pacthold.storage import database\n"
            "DDL = 'CREATE TABLE server_subagent_grants (a int)'\n"
            "W = 'INSERT OR IGNORE INTO x VALUES (1)'\n"
            "def grant_subagent(parent, child):\n    return 0\n",
            encoding="utf-8")
        findings = _store_takeover_findings([fake])
    joined = "\n".join(findings)
    for token in ("sqlite3", "pacthold", "CREATE TABLE", "INSERT OR IGNORE",
                  "grant_subagent"):
        assert token in joined, (token, findings)
    assert _store_takeover_findings(_src_files()) == [], _store_takeover_findings(_src_files())


# -- FR04: an invalid or stale snapshot is refused before any effect --------


def test_fr04_a_stale_pinned_revision_refuses_before_any_write(surface, writes):
    from ordessa_assets_subagents import errors, resolution

    results = surface.drive()
    definition, revision = results["definition"], results["revision"]
    request = surface.resolution_request(definition, revision, ceiling=surface.ceiling())
    broken = dataclasses.replace(request, revisions={})
    writes.reset()
    before = _snapshot(surface.store_root)
    with pytest.raises(errors.DomainError) as info:
        resolution.resolve_preview(
            broken, approvals=_Approvals(approved=((definition.definition_id, 1),)))
    assert info.value.code == errors.REVISION_STALE
    assert writes.writes() == [], (
        "a write was attempted before the stale snapshot was noticed: "
        + str(writes.writes()))
    assert _snapshot(surface.store_root) == before


def test_fr04_a_stale_row_version_writes_nothing(surface, writes):
    from ordessa_assets_subagents import errors

    results = surface.drive()
    definition = results["definition"]
    writes.reset()
    before = _snapshot(surface.store_root)
    service = surface.service()
    with pytest.raises(errors.DomainError) as info:
        service.save_revision(
            PRINCIPAL, surface.revision(definition.definition_id, "late body\n",
                                        revision=2),
            server_scope=SCOPE, operation_key="u:stale", expected_row_version=99)
    assert info.value.code == errors.REVISION_STALE
    assert writes.writes() == [], writes.writes()
    assert _snapshot(surface.store_root) == before


def test_fr04_a_stale_assignment_upgrade_writes_nothing(surface, writes):
    from ordessa_assets_subagents import errors
    from ordessa_assets_subagents.assignments import (
        Assignment, AssignmentDecision, approve_assignment_update,
    )
    from ordessa_assets_subagents.scopes import Principal, ScopeKind, ServerScope

    results = surface.drive()
    definition = results["definition"]
    current = Assignment(
        server_scope=ServerScope(SCOPE), principal=Principal(PRINCIPAL),
        scope_kind=ScopeKind.USER_GLOBAL, scope_id=None, harness_id="any",
        definition_id=definition.definition_id, decision=AssignmentDecision.ENABLE,
        revision=1, row_version=1,
    )
    desired = dataclasses.replace(current, revision=2)
    writes.reset()
    with pytest.raises(errors.DomainError) as info:
        approve_assignment_update(
            current, desired, expected_row_version=7,
            approvals=_Approvals(approved=((definition.definition_id, 2),)))
    assert info.value.code == errors.REVISION_STALE
    assert writes.writes() == []


def test_fr04_a_refused_import_persists_nothing(surface, writes):
    from ordessa_assets_subagents import errors

    results = surface.drive()
    writes.reset()
    before = _snapshot(surface.store_root)
    with pytest.raises(errors.DomainError) as info:
        results["service"].approve_import(
            results["preview"].preview_id, principal=PRINCIPAL, server_scope=SCOPE,
            selects=["never-previewed.md"], operation_key="u:bogus")
    assert info.value.code in {errors.PERMISSION_EXCEEDS_CEILING, errors.DEFINITION_INVALID}
    assert writes.writes() == [], writes.writes()
    assert _snapshot(surface.store_root) == before


def test_fr04_an_unauthorised_principal_writes_nothing(surface, writes):
    from ordessa_assets_subagents import errors

    results = surface.drive()
    writes.reset()
    before = _snapshot(surface.store_root)
    with pytest.raises(errors.DomainError) as info:
        results["service"].save_revision(
            OTHER_PRINCIPAL,
            surface.revision(results["definition"].definition_id, "forged\n", revision=2,
                             principal=OTHER_PRINCIPAL),
            server_scope=SCOPE, operation_key="u:forge",
            expected_row_version=surface.store.get_definition(
                results["definition"].definition_id).row_version)
    assert info.value.code in {errors.PERMISSION_EXCEEDS_CEILING, errors.REVISION_STALE,
                              errors.DEFINITION_INVALID}
    assert writes.writes() == [], writes.writes()
    assert _snapshot(surface.store_root) == before


def test_fr04_a_stale_store_writer_changes_nothing(surface, writes):
    """The storage layer keeps its own CAS: a stale writer is refused here too,
    so the guarantee does not depend on the service standing in front of it."""
    from ordessa_assets_subagents import dto, errors

    results = surface.drive()
    row = surface.store.get_definition(results["definition"].definition_id)
    stale = dto.AgentDefinition(
        **{**dataclasses.asdict(row), "description": "rewritten by a stale writer",
           "row_version": row.row_version})
    writes.reset()
    before = _snapshot(surface.store_root)
    with pytest.raises(errors.DomainError) as info:
        surface.store.replace_definition(stale, expected_row_version=row.row_version + 5)
    assert info.value.code == errors.REVISION_STALE
    assert writes.writes() == [], (
        "the store attempted a write before noticing the stale row version: "
        + str(writes.writes()))
    assert _snapshot(surface.store_root) == before
    # a stored revision is never rewritten. The publish itself happens before
    # the refusal, so staging inside the private root is expected; what FR04
    # requires is that nothing outside it is touched and the committed tree is
    # byte-identical afterwards, which the assertions below pin.
    writes.reset()
    with pytest.raises(errors.DomainError) as frozen:
        surface.store.write_revision(dataclasses.replace(
            results["revision"], role_body="rewritten history"))
    assert frozen.value.code == errors.REVISION_STALE
    assert writes.outside(surface.store_root) == [], writes.outside(surface.store_root)
    assert _snapshot(surface.store_root) == before
    assert surface.store.get_revision(
        row.definition_id, 1).role_body == results["revision"].role_body


def test_fr04_the_refusal_instruments_do_react(surface, writes):
    """The four 'nothing was written' assertions above are only worth anything
    if these instruments notice a write that legitimately happened."""
    surface.drive()
    writes.reset()
    service = surface.service()
    definition = service.create_definition(
        PRINCIPAL, server_scope=SCOPE, slug="guard-probe", display_name="Guard probe",
        description="Probe row.", origin_scope="public", origin_owner="local",
        operation_key="u:probe-create")
    assert writes.writes(), "the recorder saw no write attempt at all"
    assert writes.outside(surface.store_root) == [], writes.outside(surface.store_root)
    before = _snapshot(surface.store_root)
    assert before, "the store tree is empty, so the snapshot cannot compare"
    service.archive(
        PRINCIPAL, definition.definition_id, server_scope=SCOPE,
        operation_key="u:probe-archive",
        expected_row_version=surface.store.get_definition(definition.definition_id).row_version)
    assert _snapshot(surface.store_root) != before, (
        "the tree snapshot cannot see a changed row")


# -- FR14: importing content never executes it ------------------------------


def test_fr14_a_definition_body_is_never_executed(surface, monkeypatch):
    from ordessa_assets_subagents import decoder, errors

    tripwires = _install_tripwires(monkeypatch)
    sentinel_dir = surface.private / "exec-proof"
    sentinel_dir.mkdir()
    service = surface.service()
    definition = service.create_definition(
        PRINCIPAL, server_scope=SCOPE, slug="body-probe", display_name="Body probe",
        description="Hostile body probe.", origin_scope="public", origin_owner="local",
        operation_key="u:body-create")

    verdicts: dict[str, str] = {}
    for index, (label, template) in enumerate(HOSTILE_BODIES, start=1):
        body = template.format(sentinel=str(sentinel_dir / f"pwned-{index}"))
        revision = surface.revision(definition.definition_id, body, revision=index)
        try:
            service.save_revision(
                PRINCIPAL, revision, server_scope=SCOPE, operation_key=f"u:body-{index}",
                expected_row_version=surface.store.get_definition(
                    definition.definition_id).row_version)
        except errors.DomainError as exc:
            verdicts[label] = f"refused:{exc.code}"
            continue
        stored = service.get_revision(definition.definition_id, index)
        verdicts[label] = "stored-verbatim" if stored.role_body == body else "MUTATED"
    assert set(verdicts) == {label for label, _ in HOSTILE_BODIES}, verdicts
    bad = {k: v for k, v in verdicts.items()
           if v != "stored-verbatim" and not v.startswith("refused:")}
    assert bad == {}, f"a hostile body was interpreted rather than stored/refused: {bad}"
    assert list(sentinel_dir.iterdir()) == [], (
        "FR14: content was executed — these artefacts appeared")
    assert tripwires.fired == [], tripwires.fired

    # the pure decoder keeps the text whole; nothing is templated away
    document = ("---\nname: probe-body\ndescription: Probe.\n---\n\n"
                + HOSTILE_BODIES[0][1].format(sentinel=str(sentinel_dir / "pwned-doc")))
    mapping = decoder.decode_import_document(document, item="probe")
    assert "os.system" in mapping["role_body"], mapping["role_body"]
    assert "{{" not in mapping["role_body"] or "7*7" in mapping["role_body"]
    assert (sentinel_dir / "49").exists() is False
    assert list(sentinel_dir.iterdir()) == []


def test_fr14_no_recursive_include_or_remote_fetch_is_followed(surface, monkeypatch):
    from ordessa_assets_subagents import errors
    from ordessa_assets_subagents.service import DefinitionService
    from ordessa_assets_subagents.store import DefinitionStore

    tripwires = _install_tripwires(monkeypatch)
    directives = {
        "wiki-link.md": "---\nname: wiki-a\ndescription: D.\n---\n\nSee ![[other]]\n",
        "codex-include.md": "---\nname: inc-a\ndescription: D.\n---\n\n@[[file]]\n",
        "at-import.md": "---\nname: at-a\ndescription: D.\n---\n\n@import other\n",
        "jinja-include.md": "---\nname: jin-a\ndescription: D.\n---\n\n"
                            "{{ include \"secret.md\" }}\n",
        "include-key.md": "---\nname: ik-a\ndescription: D.\n---\n\ninclude: secret.md\n",
        "remote.md": "---\nname: rem-a\ndescription: D.\n---\n\n"
                     "fetch https://example.test/agent.md please\n",
    }
    source = surface.private / "directive-source"
    source.mkdir()
    for name, content in directives.items():
        (source / name).write_text(content, encoding="utf-8")
    secret = surface.outside / "secret.md"
    secret.write_text("-----BEGIN " + "RSA PRIVATE KEY" + "-----\n", encoding="utf-8")

    service = DefinitionService(DefinitionStore(surface.private / "directive-store"),
                                authority=_Authority())
    preview = service.import_preview("directive-source", import_root=surface.private)
    by_name = {entry.relative_path: entry for entry in preview.files}
    assert set(by_name) == set(directives), sorted(by_name)
    selectable = sorted(name for name, entry in by_name.items() if entry.selectable)
    assert selectable == [], f"these would still import: {selectable}"
    for name in sorted(directives):
        with pytest.raises(errors.DomainError):
            service.approve_import(
                preview.preview_id, principal=PRINCIPAL, server_scope=SCOPE,
                selects=[name], operation_key=f"u:import-{name}")
        with pytest.raises(errors.DomainError):
            service.import_plan(
                PRINCIPAL, preview.preview_id, server_scope=SCOPE, selects=[name])
    assert (surface.private / "directive-store" / "definitions").exists() is False, (
        "an import that was refused still created definitions")
    assert tripwires.fired == [], "a URL was fetched during preview or approval"
    assert "-----BEGIN RSA" not in repr(preview.files), (
        "G05: a followed directive leaked another file's content")


def test_fr14_a_symlinked_import_source_is_never_followed(surface):
    from ordessa_assets_subagents import errors
    from ordessa_assets_subagents.service import DefinitionService
    from ordessa_assets_subagents.store import DefinitionStore

    secret = surface.outside / "private-key.md"
    secret.write_text("-----BEGIN " + "RSA PRIVATE KEY" + "-----\n", encoding="utf-8")
    source = surface.private / "symlink-source"
    source.mkdir()
    (source / "real.md").write_text(
        "---\nname: real-doc\ndescription: D.\n---\n\nplain body\n", encoding="utf-8")
    os.symlink(secret, source / "escape.md")

    service = DefinitionService(DefinitionStore(surface.private / "symlink-store"),
                                authority=_Authority())
    outcome: list[Any] = []
    try:
        outcome.append(service.import_preview("symlink-source", import_root=surface.private))
    except errors.DomainError as exc:
        outcome.append(exc)
    refused = [entry for entry in outcome if isinstance(entry, errors.DomainError)]
    previews = [entry for entry in outcome if not isinstance(entry, errors.DomainError)]
    assert refused or previews, outcome
    if previews:  # a per-file refusal is also a legal verdict
        entry = {f.relative_path: f for f in previews[0].files}["escape.md"]
        assert not entry.selectable, "a symlinked import source is selectable"
        assert "-----BEGIN RSA" not in repr(previews[0].files)
    assert secret.read_text(encoding="utf-8").startswith("-----BEGIN"), (
        "the symlink target was rewritten, not just avoided")
    assert (surface.private / "symlink-store" / "definitions").exists() is False


def test_fr14_ordinary_placeholders_survive_untouched(surface):
    """The negative column of G05 forbids *followed* directives only. An
    ordinary `{{ ... }}` or `!cmd` in role text must survive byte-for-byte,
    which is what proves nothing is being templated or shell-expanded."""
    from ordessa_assets_subagents import decoder

    text = ("---\nname: placeholder-probe\ndescription: D.\n---\n\n"
            "Sum: {{ 7*7 }}\nrun !echo hello\nraw $HOME stays\n")
    mapping = decoder.decode_import_document(text, item="probe")
    body = mapping["role_body"]
    assert "{{ 7*7 }}" in body, body
    assert "!echo hello" in body, body
    assert "$HOME" in body, body
    assert "49" not in body and "hello\n" not in body.replace("!echo hello", "")


# -- G24: zero side effects on the user HOME --------------------------------


def test_g24_no_write_ever_targets_the_user_home(surface, writes, monkeypatch):
    from ordessa_assets_subagents import decoder

    sentinel = surface.tmp / "sentinel-home"
    sentinel.mkdir()
    monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: sentinel))
    monkeypatch.setattr(os.path, "expanduser",
                        lambda path, **kwargs: str(path).replace("~", str(sentinel), 1))
    assert pathlib.Path.home() == sentinel, "the sentinel HOME is not in place"
    assert os.path.expanduser("~/.claude") == str(sentinel / ".claude")

    tripwires = _install_tripwires(monkeypatch)
    writes.reset()
    results = surface.drive()
    decoder.decode_import_document(
        "---\nname: x-probe\ndescription: D.\n---\n\nbody\n", item="probe")

    assert writes.under(sentinel) == [], (
        f"FR09/US3: the domain wrote into the user HOME at {sentinel}: "
        + str(writes.under(sentinel)))
    assert _snapshot(sentinel) == {}, f"content appeared under the sentinel HOME: " \
                                      f"{_snapshot(sentinel)}"
    assert tripwires.fired == []
    assert results["definition"].definition_id, "the drive did not run; blind green"

    # capability: the same instruments do see a write into the sentinel HOME
    writes.reset()
    (sentinel / "probe.txt").write_text("clobber\n", encoding="utf-8")
    assert writes.under(sentinel), "the recorder is blind to HOME writes"
    assert _snapshot(sentinel), "the snapshot is blind to HOME writes"


def test_g24_no_module_addresses_a_path_through_the_user_home():
    """`Path.home()` may only appear in a *refusal* guard (service._inside
    compares a candidate against HOME to reject it); it must never be the base
    of a path that is opened, read, written or joined."""
    files = _src_files()
    assert files, "no source found — the guard would be blind"
    findings: list[str] = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        tree, error = _parse(path)
        if error:
            findings.append(error)
            continue
        findings.extend(f"{path.name}: {hit}" for hit in _home_target_findings(source))
    assert findings == [], (
        "contracts.md §C1 / G24: no path of this domain may be derived from the "
        "user HOME:\n" + "\n".join(findings))


def test_g24_the_home_scan_is_capable():
    assert _home_target_findings('open(os.path.expanduser("~/.claude/x.md"), "w")')
    assert _home_target_findings('p = Path.home() / ".codex" / "config.toml"')
    assert _home_target_findings('home = Path.home()\nopen(home / "x.md", "w")')
    assert _home_target_findings('Path("~/.claude/agents/x.md").write_text("y")')
    assert _home_target_findings('home = Path.home()\nshutil.copytree(home, other)')
    # a refusal guard that only *compares* HOME is legal and must stay green
    assert _home_target_findings(
        'home = Path.home().resolve()\nif resolved == home:\n    raise ValueError()') == []
    assert _home_target_findings('if value.startswith("~"):\n    raise _invalid()') == []
    assert _home_target_findings("x = 'guard-reviewer'\nimport hashlib\n") == []
