#!/usr/bin/env python3
"""``envctl`` — standalone reference driver for the execution-environment contract.

This is a *reference consumer* of ``ordessa_environments`` and
``ordessa_environments_local``. It deliberately imports nothing from units,
agents, ACP, the Server or any Harness/Profile layer: a managed environment is
listed, inspected and used from the environment contract alone (the
resource-only path required by the migration acceptance).

Usage
-----
::

    envctl --state DIR providers [--json]
    envctl --state DIR list [--json]
    envctl --state DIR create local --root ABS [--alias NAME] [--json]
    envctl --state DIR register local <backend-id> [--alias NAME] [--json]
    envctl --state DIR inspect <alias|identity> [--json]
    envctl --state DIR capabilities <alias|identity> [--json]
    envctl --state DIR use <alias|identity> [--owner NAME] [--share] [--timeout SEC] -- <argv...>
    envctl --state DIR files <alias> ls|cat|write <args...> [--json]
    envctl --state DIR stop|delete <alias> [--json]

State
-----
The state directory comes from ``--state DIR`` or ``ENVCTL_STATE`` and is
required. It holds the CLI-owned registry (``environments.sqlite``, the
``SQLiteEnvironmentStore``), the CLI-owned alias map (``aliases.json``) and the
default local working root (``work/``). ``aliases.json`` never stores secrets.

JSON envelope
-------------
``--json`` prints exactly one JSON object to stdout and nothing else::

    {"apiVersion": "agent-tools/1", "requestId": ..., "command": ...,
     "status": "confirmed|refused|unknown", "data": ...,
     "error": null | {"code": ..., "message": ..., "retryable": bool}}

Normal mode streams the command's own output. Exit codes: 0 ok, 2
invalid/refused before any effect, 3 authorization, 4 unsupported/unavailable,
5 conflict, 6 unknown (never retried), 7 local observation timeout. ``use``
propagates the child's real exit code.

Refusals and non-goals
----------------------
There is no interactive terminal in v1: ``use`` without a command after ``--``
exits 2 with "terminal sessions are unavailable in v1; pass a command". The
Local provider implements no resource start/stop/delete, so those commands
refuse explicitly (exit 2) and never touch user files. OpenShell needs an
already authenticated ``SandboxClient`` and its same-authority RPC stub from
composition; this design has no standalone authenticated-client bootstrap, so
``providers`` reports it ``UNAVAILABLE`` and no auth, fallback or retry is
invented. Nothing here auto-starts a service, falls back to another provider or
retries an unknown outcome.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import stat
import sys
import uuid
from contextlib import suppress
from pathlib import Path

from ordessa_environments import (
    BackendNotFound,
    EnvironmentFailure,
    EnvironmentGuaranteeUnmet,
    EnvironmentManager,
    EnvironmentOperationUnknown,
    EnvironmentRefused,
    ProcessRequest,
    ProcessStartFailed,
    ProcessWaitTimeout,
    SQLiteEnvironmentStore,
)
from ordessa_environments_local import (
    LocalEnvironmentResourceProvider,
    probe_local,
)

API_VERSION = "agent-tools/1"

EXIT_OK = 0
EXIT_INVALID = 2
EXIT_AUTHORIZATION = 3
EXIT_UNSUPPORTED = 4
EXIT_CONFLICT = 5
EXIT_UNKNOWN = 6
EXIT_TIMEOUT = 7

REGISTRY_FILENAME = "environments.sqlite"
ALIASES_FILENAME = "aliases.json"
WORK_DIRNAME = "work"

#: Alias names are CLI-owned identifiers, never credentials. The pattern keeps
#: them shell-safe and rejects identity-shaped or secret-shaped values.
ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

#: JSON mode bounds captured command output so one envelope stays bounded.
CAPTURE_LIMIT = 1024 * 1024
#: Grace periods after a timeout/cancel; these are local observation windows.
CANCEL_GRACE_SECONDS = 5.0
DRAIN_GRACE_SECONDS = 5.0

VALUE_OPTIONS = ("--state", "--request-id", "--root", "--alias", "--owner", "--timeout")
FLAG_OPTIONS = ("--json", "--share")

LOCAL_NOTE = (
    "isolation=none: a development process runner, not a security sandbox"
)
OPENSHELL_REASON = (
    "OpenShell requires an already authenticated SandboxClient and its "
    "same-authority RPC stub from composition; no standalone authenticated-client "
    "bootstrap exists in this design, so the provider is unavailable here"
)
ASSURANCE_STATEMENT = (
    "provider-reported isolation; it is not a permission, lease or hold"
)


class CliError(Exception):
    """A classified CLI failure: stable code, exit code and envelope status."""

    def __init__(self, exit_code, code, message, *, status="refused", retryable=False, data=None):
        super().__init__(message)
        self.exit_code = exit_code
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable
        self.data = data


class Invocation:
    __slots__ = ("state_dir", "json_mode", "request_id", "command", "positionals", "child_argv", "options")

    def __init__(self, *, state_dir, json_mode, request_id, command, positionals, child_argv, options):
        self.state_dir = state_dir
        self.json_mode = json_mode
        self.request_id = request_id
        self.command = command
        self.positionals = positionals
        self.child_argv = child_argv
        self.options = options


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------

def _head(argv):
    """Tokens before the first ``--``; the tail belongs to the child command."""
    if "--" in argv:
        return list(argv[: argv.index("--")])
    return list(argv)


def _raw_json_requested(argv):
    return "--json" in _head(argv)


def _raw_request_id(argv):
    head = _head(argv)
    if "--request-id" in head:
        index = head.index("--request-id")
        if index + 1 < len(head):
            return head[index + 1]
    return None


def _raw_command(argv):
    head = _head(argv)
    index = 0
    while index < len(head):
        token = head[index]
        if token in FLAG_OPTIONS:
            index += 1
        elif token in VALUE_OPTIONS:
            index += 2
        elif token.startswith("--"):
            index += 1
        else:
            return token
    return "unknown"


def parse_invocation(argv):
    head = _head(argv)
    child_argv = list(argv[argv.index("--") + 1:]) if "--" in argv else None
    options = {}
    positionals = []
    index = 0
    while index < len(head):
        token = head[index]
        if token in FLAG_OPTIONS:
            options[token] = True
            index += 1
        elif token in VALUE_OPTIONS:
            if index + 1 >= len(head):
                raise CliError(EXIT_INVALID, "ENVCTL_INVALID_ARGUMENT", f"{token} requires a value")
            options[token] = head[index + 1]
            index += 2
        elif token.startswith("--"):
            raise CliError(EXIT_INVALID, "ENVCTL_INVALID_ARGUMENT", f"unknown option {token!r}")
        else:
            positionals.append(token)
            index += 1
    if child_argv is not None and (not positionals or positionals[0] != "use"):
        # ``--`` terminates option parsing for non-``use`` commands.
        positionals.extend(child_argv)
        child_argv = None
    command = positionals[0] if positionals else None
    if command is not None:
        positionals = positionals[1:]
    state_dir = options.get("--state") or os.environ.get("ENVCTL_STATE")
    return Invocation(
        state_dir=state_dir,
        json_mode=bool(options.get("--json")),
        request_id=options.get("--request-id"),
        command=command,
        positionals=positionals,
        child_argv=child_argv,
        options=options,
    )


# ---------------------------------------------------------------------------
# envelopes and error classification
# ---------------------------------------------------------------------------

def _write_envelope(command, request_id, status, data, error):
    envelope = {
        "apiVersion": API_VERSION,
        "requestId": request_id,
        "command": command,
        "status": status,
        "data": data,
        "error": error,
    }
    sys.stdout.write(json.dumps(envelope, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def report_error(error, *, command, request_id, json_mode):
    if json_mode:
        _write_envelope(
            command,
            request_id,
            error.status,
            error.data,
            {"code": error.code, "message": error.message, "retryable": error.retryable},
        )
    else:
        sys.stderr.write(f"envctl: {error.message}\n")
        sys.stderr.flush()
    return error.exit_code


def report_success(command, request_id, data, json_mode, human):
    if json_mode:
        _write_envelope(command, request_id, "confirmed", data, None)
    elif human:
        sys.stdout.write(human if human.endswith("\n") else human + "\n")
        sys.stdout.flush()
    return EXIT_OK


def to_cli_error(error):
    """Map a package failure onto the frozen CLI exit-code contract."""
    if isinstance(error, CliError):
        return error
    if isinstance(error, ProcessWaitTimeout):
        return CliError(
            EXIT_TIMEOUT,
            "ENVCTL_TIMEOUT",
            "local observation timed out; the command may still be running (no automatic retry)",
            status="unknown",
        )
    if isinstance(error, EnvironmentOperationUnknown):
        return CliError(
            EXIT_UNKNOWN,
            "ENVCTL_OPERATION_UNKNOWN",
            "operation outcome is unknown; inspect before acting (no automatic retry)",
            status="unknown",
        )
    if isinstance(error, BackendNotFound):
        return CliError(EXIT_UNSUPPORTED, "ENVCTL_BACKEND_NOT_FOUND", error.detail)
    if isinstance(error, EnvironmentGuaranteeUnmet):
        return CliError(EXIT_UNSUPPORTED, "ENVCTL_GUARANTEE_UNMET", error.detail)
    if isinstance(error, ProcessStartFailed):
        return CliError(EXIT_UNSUPPORTED, "ENVCTL_PROCESS_START_FAILED", error.detail)
    if isinstance(error, EnvironmentRefused):
        return CliError(EXIT_INVALID, "ENVCTL_REFUSED", error.detail)
    if isinstance(error, EnvironmentFailure):
        return CliError(EXIT_UNSUPPORTED, "ENVCTL_ENVIRONMENT_FAILURE", error.detail)
    if isinstance(error, OSError):
        return CliError(EXIT_UNSUPPORTED, "ENVCTL_IO_ERROR", str(error))
    return CliError(EXIT_UNSUPPORTED, "ENVCTL_UNAVAILABLE", str(error))


# ---------------------------------------------------------------------------
# state: registry, aliases and manager
# ---------------------------------------------------------------------------

def open_state(state_dir):
    """Open the CLI-owned registry and alias map for ``state_dir``."""
    state_dir.mkdir(parents=True, exist_ok=True)
    provider = LocalEnvironmentResourceProvider(default_root=str(state_dir / WORK_DIRNAME))
    manager = EnvironmentManager(
        store=SQLiteEnvironmentStore(state_dir / REGISTRY_FILENAME),
        providers={"local": provider},
    )
    return manager, load_aliases(state_dir)


def load_aliases(state_dir):
    path = state_dir / ALIASES_FILENAME
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CliError(
            EXIT_INVALID, "ENVCTL_ALIAS_STORE_INVALID", f"aliases.json is not readable JSON: {error}"
        ) from error
    aliases = payload.get("aliases") if isinstance(payload, dict) else None
    if not isinstance(aliases, dict):
        raise CliError(
            EXIT_INVALID, "ENVCTL_ALIAS_STORE_INVALID", "aliases.json does not hold an alias map"
        )
    for name, identity in aliases.items():
        if not isinstance(name, str) or not isinstance(identity, str) or not identity.startswith("environment/"):
            raise CliError(
                EXIT_INVALID,
                "ENVCTL_ALIAS_STORE_INVALID",
                "aliases.json holds a non-identity alias target",
            )
    return dict(aliases)


def save_aliases(state_dir, aliases):
    path = state_dir / ALIASES_FILENAME
    payload = {"apiVersion": API_VERSION, "aliases": dict(sorted(aliases.items()))}
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def validate_alias(alias):
    if not isinstance(alias, str) or not ALIAS_PATTERN.match(alias):
        raise CliError(
            EXIT_INVALID,
            "ENVCTL_INVALID_ALIAS",
            "alias must match [A-Za-z0-9][A-Za-z0-9._-]{0,63}",
        )


def precheck_alias(aliases, alias):
    if alias is None:
        return
    validate_alias(alias)
    if alias in aliases:
        raise CliError(
            EXIT_CONFLICT, "ENVCTL_ALIAS_CONFLICT", f"alias {alias!r} already exists"
        )


def bind_alias(state_dir, aliases, alias, identity):
    if alias is None:
        return
    aliases[alias] = identity
    save_aliases(state_dir, aliases)


def aliases_for(identity, aliases):
    return sorted(name for name, target in aliases.items() if target == identity)


def resolve_reference(manager, aliases, token):
    """Resolve ``<alias|identity>`` to a stored identity; never guess."""
    if token in aliases:
        identity = aliases[token]
        if identity not in manager.store.identities():
            raise CliError(
                EXIT_INVALID,
                "ENVCTL_UNKNOWN_RESOURCE",
                f"alias {token!r} points at an unknown environment identity",
            )
        return identity, token
    if isinstance(token, str) and token.startswith("environment/"):
        if token in manager.store.identities():
            return token, None
        raise CliError(EXIT_INVALID, "ENVCTL_UNKNOWN_RESOURCE", f"unknown environment identity {token!r}")
    raise CliError(EXIT_INVALID, "ENVCTL_INVALID_REFERENCE", f"unknown alias or identity {token!r}")


def require_one_reference(inv, command):
    if len(inv.positionals) != 1:
        raise CliError(
            EXIT_INVALID, "ENVCTL_INVALID_ARGUMENT", f"{command} requires exactly one <alias|identity>"
        )
    return inv.positionals[0]


def parse_timeout(value):
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        raise CliError(EXIT_INVALID, "ENVCTL_INVALID_TIMEOUT", "--timeout requires seconds") from None
    if not math.isfinite(seconds) or seconds < 0:
        raise CliError(
            EXIT_INVALID, "ENVCTL_INVALID_TIMEOUT", "--timeout requires finite nonnegative seconds"
        )
    return seconds


# ---------------------------------------------------------------------------
# resource description
# ---------------------------------------------------------------------------

def capabilities_summary(observation):
    if observation is None:
        return None
    return {"isolation": observation.capabilities.isolation,
            "provides": sorted(observation.capabilities.provides)}


def capabilities_block(observation):
    """Isolation, derived assurance and provider-supplied values.

    ``values`` is the provider's own capability detail; ``assurance`` is a
    derived, explicitly non-authoritative statement. Neither is a permission.
    """
    if observation is None:
        return None
    capabilities = observation.capabilities
    return {
        "isolation": capabilities.isolation,
        "provides": sorted(capabilities.provides),
        "assurance": {
            "isolation": capabilities.isolation,
            "isolationIsSecurityBoundary": False,
            "localDevelopmentOnly": capabilities.isolation == "none",
            "statement": ASSURANCE_STATEMENT,
        },
        "values": dict(capabilities.detail),
    }


def describe(identity, alias, snapshot, aliases):
    observation = snapshot.observation
    return {
        "identity": identity,
        "alias": alias,
        "aliases": aliases_for(identity, aliases),
        "provider": snapshot.provider_id,
        "backendId": snapshot.backend_id,
        "phase": snapshot.phase,
        "generation": snapshot.generation,
        "state": observation.state if observation else None,
        "observedAt": observation.observed_at if observation else None,
        "runtimeIdentity": observation.runtime_identity if observation else None,
        "capabilities": capabilities_block(observation),
        "activeUses": snapshot.active_uses,
    }


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def command_providers(inv, state_dir, request_id):
    probe = probe_local(default_root=str(state_dir / WORK_DIRNAME))
    local = {
        "id": "local",
        "available": bool(probe.get("available")),
        "isolation": probe.get("isolation"),
        "capabilities": sorted(probe.get("capabilities", ())),
        "defaultRoot": probe.get("defaultRoot"),
        "bindingId": LocalEnvironmentResourceProvider.binding_id,
        "operations": sorted(LocalEnvironmentResourceProvider.operations),
        "note": LOCAL_NOTE,
    }
    openshell = {
        "id": "openshell",
        "available": False,
        "isolation": None,
        "capabilities": [],
        "operations": [],
        "status": "UNAVAILABLE",
        "reason": OPENSHELL_REASON,
    }
    data = {"providers": [local, openshell]}
    human = "\n".join(
        [
            f"local available isolation={local['isolation']} "
            f"capabilities={','.join(local['capabilities'])} operations=- "
            f"defaultRoot={local['defaultRoot']}",
            f"openshell UNAVAILABLE reason={OPENSHELL_REASON}",
        ]
    )
    return report_success("providers", request_id, data, inv.json_mode, human)


def command_list(inv, state_dir, request_id):
    manager, aliases = open_state(state_dir)
    entries = []
    for snapshot in manager.list():
        observation = snapshot.observation
        entries.append(
            {
                "identity": snapshot.identity,
                "aliases": aliases_for(snapshot.identity, aliases),
                "provider": snapshot.provider_id,
                "backendId": snapshot.backend_id,
                "phase": snapshot.phase,
                "generation": snapshot.generation,
                "state": observation.state if observation else None,
                "capabilities": capabilities_summary(observation),
                "activeUses": snapshot.active_uses,
            }
        )
    known = {entry["identity"] for entry in entries}
    orphan_aliases = sorted(name for name, identity in aliases.items() if identity not in known)
    data = {"resources": entries, "orphanAliases": orphan_aliases}
    lines = [
        f"{entry['identity']} alias={','.join(entry['aliases']) or '-'} "
        f"provider={entry['provider']} state={entry['state']} "
        f"phase={entry['phase']} activeUses={entry['activeUses']} "
        f"isolation={entry['capabilities']['isolation'] if entry['capabilities'] else '-'}"
        for entry in entries
    ]
    if orphan_aliases:
        lines.append("orphanAliases=" + ",".join(orphan_aliases))
    return report_success("list", request_id, data, inv.json_mode, "\n".join(lines))


def _require_local_provider(positionals, usage):
    if not positionals:
        raise CliError(EXIT_INVALID, "ENVCTL_INVALID_ARGUMENT", usage)
    if positionals[0] == "openshell":
        raise CliError(EXIT_UNSUPPORTED, "ENVCTL_PROVIDER_UNAVAILABLE", OPENSHELL_REASON)
    if positionals[0] != "local":
        raise CliError(EXIT_INVALID, "ENVCTL_INVALID_ARGUMENT", usage)


def command_create(inv, state_dir, request_id):
    usage = "usage: envctl --state DIR create local --root ABS [--alias NAME]"
    if len(inv.positionals) != 1:
        _require_local_provider(inv.positionals, usage)
        raise CliError(EXIT_INVALID, "ENVCTL_INVALID_ARGUMENT", usage)
    _require_local_provider(inv.positionals, usage)
    root = inv.options.get("--root")
    if root is None:
        raise CliError(EXIT_INVALID, "ENVCTL_INVALID_ARGUMENT", "create local requires --root ABS")
    if not os.path.isabs(root):
        raise CliError(
            EXIT_INVALID, "ENVCTL_INVALID_ARGUMENT", "create local --root must be an absolute path"
        )
    manager, aliases = open_state(state_dir)
    alias = inv.options.get("--alias")
    precheck_alias(aliases, alias)
    instance = manager.create("local", {"root": os.path.normpath(root)})
    bind_alias(state_dir, aliases, alias, instance.identity)
    snapshot = instance.snapshot
    data = describe(instance.identity, alias, snapshot, aliases)
    human = (
        f"created {instance.identity} alias={alias or '-'} provider={snapshot.provider_id} "
        f"backend={snapshot.backend_id} state={snapshot.observation.state if snapshot.observation else None}"
    )
    return report_success("create", request_id, data, inv.json_mode, human)


def command_register(inv, state_dir, request_id):
    usage = "usage: envctl --state DIR register local <backend-id> [--alias NAME]"
    if len(inv.positionals) != 2:
        _require_local_provider(inv.positionals, usage)
        raise CliError(EXIT_INVALID, "ENVCTL_INVALID_ARGUMENT", usage)
    _require_local_provider(inv.positionals, usage)
    backend_id = inv.positionals[1]
    if not os.path.isabs(backend_id):
        raise CliError(
            EXIT_INVALID, "ENVCTL_INVALID_ARGUMENT", "register local requires an absolute backend directory"
        )
    manager, aliases = open_state(state_dir)
    alias = inv.options.get("--alias")
    precheck_alias(aliases, alias)
    instance = manager.register("local", backend_id)
    bind_alias(state_dir, aliases, alias, instance.identity)
    snapshot = instance.snapshot
    data = describe(instance.identity, alias, snapshot, aliases)
    human = (
        f"registered {instance.identity} alias={alias or '-'} provider={snapshot.provider_id} "
        f"backend={snapshot.backend_id}"
    )
    return report_success("register", request_id, data, inv.json_mode, human)


def command_inspect(inv, state_dir, request_id):
    manager, aliases = open_state(state_dir)
    identity, alias = resolve_reference(manager, aliases, require_one_reference(inv, "inspect"))
    snapshot = manager.get(identity).inspect()
    data = describe(identity, alias, snapshot, aliases)
    observation = snapshot.observation
    human = "\n".join(
        [
            f"identity: {identity}",
            f"alias: {alias or '-'}",
            f"provider: {snapshot.provider_id}",
            f"backend: {snapshot.backend_id}",
            f"phase: {snapshot.phase}",
            f"state: {observation.state if observation else '-'}",
            f"isolation: {observation.capabilities.isolation if observation else '-'}",
            f"capabilities: {','.join(sorted(observation.capabilities.provides)) if observation else '-'}",
            f"activeUses: {snapshot.active_uses}",
        ]
    )
    return report_success("inspect", request_id, data, inv.json_mode, human)


def command_capabilities(inv, state_dir, request_id):
    manager, aliases = open_state(state_dir)
    identity, alias = resolve_reference(manager, aliases, require_one_reference(inv, "capabilities"))
    snapshot = manager.get(identity).snapshot
    if snapshot.observation is None:
        raise CliError(
            EXIT_UNSUPPORTED,
            "ENVCTL_NO_OBSERVED_CAPABILITIES",
            "resource has no observed capabilities yet",
        )
    block = capabilities_block(snapshot.observation)
    data = {
        "identity": identity,
        "alias": alias,
        "aliases": aliases_for(identity, aliases),
        "provider": snapshot.provider_id,
        "phase": snapshot.phase,
        "generation": snapshot.generation,
        "capabilities": block,
    }
    human = "\n".join(
        [
            f"identity: {identity}",
            f"isolation: {block['isolation']}",
            f"provides: {','.join(block['provides'])}",
            f"assurance: localDevelopmentOnly={block['assurance']['localDevelopmentOnly']} "
            f"isolationIsSecurityBoundary={block['assurance']['isolationIsSecurityBoundary']}",
            f"values: {json.dumps(block['values'], sort_keys=True)}",
        ]
    )
    return report_success("capabilities", request_id, data, inv.json_mode, human)


def command_files(inv, state_dir, request_id):
    usage = "usage: envctl --state DIR files <alias> ls|cat|write <args...>"
    if len(inv.positionals) < 2:
        raise CliError(EXIT_INVALID, "ENVCTL_INVALID_ARGUMENT", usage)
    reference, operation = inv.positionals[0], inv.positionals[1]
    arguments = inv.positionals[2:]
    manager, aliases = open_state(state_dir)
    identity, alias = resolve_reference(manager, aliases, reference)
    use = manager.get(identity).acquire(f"envctl-files/{os.getpid()}", sharing=False)
    try:
        if operation == "ls":
            if arguments:
                raise CliError(EXIT_INVALID, "ENVCTL_INVALID_ARGUMENT", "files ls takes no arguments")
            entries = sorted(use.files.list())
            data = {"identity": identity, "alias": alias, "operation": "ls", "entries": entries}
            human = "\n".join(entries)
        elif operation == "cat":
            if len(arguments) != 1:
                raise CliError(EXIT_INVALID, "ENVCTL_INVALID_ARGUMENT", "files cat requires one relative path")
            content = use.files.read_text(arguments[0])
            data = {
                "identity": identity,
                "alias": alias,
                "operation": "cat",
                "path": arguments[0],
                "content": content,
            }
            human = content if (not content or content.endswith("\n")) else content + "\n"
        elif operation == "write":
            if len(arguments) != 2:
                raise CliError(
                    EXIT_INVALID, "ENVCTL_INVALID_ARGUMENT", "files write requires <relative-path> <content>"
                )
            use.files.write_text(arguments[0], arguments[1])
            size = len(arguments[1].encode("utf-8"))
            data = {
                "identity": identity,
                "alias": alias,
                "operation": "write",
                "path": arguments[0],
                "bytes": size,
            }
            human = f"wrote {arguments[0]} ({size} bytes)"
        else:
            raise CliError(EXIT_INVALID, "ENVCTL_INVALID_ARGUMENT", usage)
    finally:
        use.release()
    return report_success("files", request_id, data, inv.json_mode, human)


def command_use(inv, state_dir, request_id):
    if len(inv.positionals) != 1:
        raise CliError(
            EXIT_INVALID,
            "ENVCTL_INVALID_ARGUMENT",
            "usage: envctl --state DIR use <alias|identity> [--owner NAME] [--share] [--timeout SEC] -- <argv...>",
        )
    if not inv.child_argv:
        # Pre-effect refusal: no Use is acquired and no process is started.
        raise CliError(
            EXIT_INVALID,
            "ENVCTL_NO_COMMAND",
            "terminal sessions are unavailable in v1; pass a command",
        )
    timeout = parse_timeout(inv.options.get("--timeout"))
    owner = inv.options.get("--owner") or f"envctl/{os.getpid()}"
    if not isinstance(owner, str) or not owner.strip():
        raise CliError(EXIT_INVALID, "ENVCTL_INVALID_ARGUMENT", "--owner requires a non-empty name")
    sharing = bool(inv.options.get("--share"))
    manager, aliases = open_state(state_dir)
    identity, alias = resolve_reference(manager, aliases, inv.positionals[0])
    use = manager.get(identity).acquire(owner, sharing=sharing)
    try:
        outcome = asyncio.run(_execute_use(use, inv.child_argv, timeout, inv.json_mode))
    except BaseException:
        with suppress(Exception):
            use.release()
        raise
    payload = {
        "identity": identity,
        "alias": alias,
        "useIdentity": use.identity,
        "generation": use.generation,
        "processIdentity": outcome["processIdentity"],
        "exitCode": outcome["exitCode"],
        "timedOut": outcome["timedOut"],
        "stdoutBytes": len(outcome["stdout"]),
        "stderrBytes": len(outcome["stderr"]),
        "truncated": outcome["truncated"],
        "useReleased": outcome["useReleased"],
        "releaseError": outcome["releaseError"],
    }
    if inv.json_mode:
        payload["stdout"] = outcome["stdout"].decode("utf-8", "replace")
        payload["stderr"] = outcome["stderr"].decode("utf-8", "replace")
    if outcome["timedOut"]:
        message = "local observation timed out; the command may still be running (no automatic retry)"
        if not outcome["useReleased"]:
            message += "; the recorded Use remains held"
        return report_error(
            CliError(EXIT_TIMEOUT, "ENVCTL_TIMEOUT", message, status="unknown", data=payload),
            command="use",
            request_id=request_id,
            json_mode=inv.json_mode,
        )
    if outcome["ioUnknown"]:
        message = "process output outcome is unknown; inspect before acting (no automatic retry)"
        if not outcome["useReleased"]:
            message += "; the recorded Use remains held"
        return report_error(
            CliError(EXIT_UNKNOWN, "ENVCTL_IO_UNKNOWN", message, status="unknown", data=payload),
            command="use",
            request_id=request_id,
            json_mode=inv.json_mode,
        )
    if inv.json_mode:
        # One envelope on stdout, then the child's real exit code: the JSON
        # envelope never hides the propagated command result.
        _write_envelope("use", request_id, "confirmed", payload, None)
    return outcome["exitCode"] if outcome["exitCode"] is not None else EXIT_UNKNOWN


def _lifecycle_command(operation):
    def handler(inv, state_dir, request_id):
        reference = require_one_reference(inv, operation)
        manager, aliases = open_state(state_dir)
        identity, alias = resolve_reference(manager, aliases, reference)
        instance = manager.get(identity)
        try:
            receipt = getattr(instance, operation)()
        except EnvironmentRefused as error:
            raise CliError(
                EXIT_INVALID,
                "ENVCTL_LOCAL_LIFECYCLE_UNSUPPORTED",
                f"local provider refuses resource {operation}: {error.detail}; "
                "user files are preserved and nothing was deleted",
            ) from error
        data = {
            "identity": identity,
            "alias": alias,
            "operation": operation,
            "generation": receipt.generation,
            "confirmed": receipt.confirmed,
        }
        human = f"{operation} {identity} confirmed={receipt.confirmed}"
        return report_success(operation, request_id, data, inv.json_mode, human)

    return handler


# ---------------------------------------------------------------------------
# one-shot Use execution
# ---------------------------------------------------------------------------

async def _pump_stdin(process):
    """Forward this process's stdin to the managed child, then request EOF.

    v1 has no interactive terminal: a TTY stdin is closed immediately, and a
    piped/regular-file stdin is streamed and closed. Regular files are read
    synchronously (they are always ready), while pipes and sockets go through
    the loop's own reader. Nothing invents a terminal.
    """
    try:
        fd = sys.stdin.fileno()
        mode = os.fstat(fd).st_mode
    except (AttributeError, ValueError, OSError):
        with suppress(Exception):
            await process.close_stdin()
        return
    if stat.S_ISREG(mode):
        try:
            while True:
                data = os.read(fd, 65536)
                if not data:
                    break
                await process.write_stdin(data)
        except (EnvironmentFailure, OSError):
            pass
        finally:
            with suppress(Exception):
                await process.close_stdin()
        return
    if stat.S_ISCHR(mode) and os.isatty(fd):
        with suppress(Exception):
            await process.close_stdin()
        return
    if not (stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode)):
        # Character devices such as /dev/null are not loop-readable here and
        # carry no interactive input: request EOF instead of inventing a TTY.
        with suppress(Exception):
            await process.close_stdin()
        return
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    transport = None
    try:
        transport, _ = await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        while True:
            data = await reader.read(65536)
            if not data:
                break
            await process.write_stdin(data)
    except (EnvironmentFailure, OSError, ValueError):
        pass
    finally:
        if transport is not None:
            with suppress(Exception):
                transport.close()
        with suppress(Exception):
            await process.close_stdin()


async def _execute_use(use, argv, timeout, json_mode):
    """Start one process in the Use, stream it, confirm exit, release both.

    Returns a dict; never leaves an unconfirmed process claiming a real exit.
    """
    request = ProcessRequest.build(argv, cwd=use.files.root(), env=os.environ)
    process = use.execution.start(request)
    capture = {"stdout": bytearray(), "stderr": bytearray()}
    truncated = {"stdout": False, "stderr": False}
    state = {"ioUnknown": False, "timedOut": False, "observation": None,
             "useReleased": False, "releaseError": None}

    def sink(chunk, name):
        if not json_mode:
            stream = sys.stdout.buffer if name == "stdout" else sys.stderr.buffer
            stream.write(chunk)
            stream.flush()
            return
        room = CAPTURE_LIMIT - len(capture[name])
        if room <= 0:
            truncated[name] = True
            return
        if len(chunk) > room:
            capture[name].extend(chunk[:room])
            truncated[name] = True
        else:
            capture[name].extend(chunk)

    async def drain(reader, name):
        while True:
            chunk = await reader(65536)
            if not chunk:
                return
            sink(chunk, name)

    stdout_task = asyncio.create_task(drain(process.read_stdout, "stdout"))
    stderr_task = asyncio.create_task(drain(process.read_stderr, "stderr"))
    stdin_task = asyncio.create_task(_pump_stdin(process))
    try:
        try:
            state["observation"] = await process.wait_exit(timeout=timeout)
        except ProcessWaitTimeout:
            state["timedOut"] = True
            with suppress(Exception):
                await process.cancel(force=True)
            with suppress(Exception):
                state["observation"] = await process.wait_exit(timeout=CANCEL_GRACE_SECONDS)
        for task in (stdout_task, stderr_task):
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=DRAIN_GRACE_SECONDS)
            except asyncio.TimeoutError:
                task.cancel()
            except EnvironmentFailure:
                state["ioUnknown"] = True
        stdin_task.cancel()
        with suppress(BaseException):
            await stdin_task
    finally:
        try:
            process.release()
        except Exception as error:  # noqa: BLE001 - reported, never retried
            state["releaseError"] = f"process transport release failed: {error}"
        try:
            use.release()
            state["useReleased"] = True
        except Exception as error:  # noqa: BLE001 - reported, never retried
            if state["releaseError"] is None:
                state["releaseError"] = f"use release failed: {error}"

    observation = state["observation"]
    exit_code = observation.exit_code if observation is not None and observation.state == "exited" else None
    return {
        "exitCode": exit_code,
        "timedOut": state["timedOut"],
        "ioUnknown": state["ioUnknown"],
        "stdout": bytes(capture["stdout"]),
        "stderr": bytes(capture["stderr"]),
        "truncated": dict(truncated),
        "processIdentity": process.identity,
        "useReleased": state["useReleased"],
        "releaseError": state["releaseError"],
    }


COMMANDS = {
    "providers": command_providers,
    "list": command_list,
    "create": command_create,
    "register": command_register,
    "inspect": command_inspect,
    "capabilities": command_capabilities,
    "use": command_use,
    "files": command_files,
    "stop": _lifecycle_command("stop"),
    "delete": _lifecycle_command("delete"),
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    raw_json = _raw_json_requested(argv)
    request_id = _raw_request_id(argv) or uuid.uuid4().hex
    command = _raw_command(argv)
    try:
        inv = parse_invocation(argv)
    except CliError as error:
        return report_error(error, command=command, request_id=request_id, json_mode=raw_json)
    request_id = inv.request_id or request_id
    command = inv.command or "unknown"
    try:
        if inv.state_dir is None:
            raise CliError(
                EXIT_INVALID,
                "ENVCTL_STATE_REQUIRED",
                "state directory is required: pass --state DIR or set ENVCTL_STATE",
            )
        state_dir = Path(inv.state_dir).expanduser().absolute()
        handler = COMMANDS.get(command)
        if handler is None:
            raise CliError(EXIT_INVALID, "ENVCTL_UNKNOWN_COMMAND", f"unknown command {command!r}")
        return handler(inv, state_dir, request_id)
    except CliError as error:
        return report_error(error, command=command, request_id=request_id, json_mode=inv.json_mode)
    except BaseException as error:  # noqa: BLE001 - classified, never silently swallowed
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        classified = to_cli_error(error)
        return report_error(classified, command=command, request_id=request_id, json_mode=inv.json_mode)


if __name__ == "__main__":
    sys.exit(main())
