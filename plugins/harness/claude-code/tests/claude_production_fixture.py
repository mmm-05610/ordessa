"""Shared C substrate: real temporary SQLite ledger + real core issuer +
original store claims including the cleanup stop/release steps, composed with
the family's production evidence ports and every explicitly injected port.

No Claude SDK, no Claude binary, no model call and no user credential exists
on this layer. Controlled `python` sleep processes are REAL test-owned
processes used to prove actual effect behavior; P against the native Claude
runtime is absent (no installed binary anywhere in this tree) and is never
claimed. Nothing here installs a package, touches user data, or signs in.
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages/execution/agents/tests/support"))

from agent_tools_fixtures.invocation_authority import Authority, CurrentState  # noqa: E402
from agent_tools_fixtures.unit_records import ROOT, parts  # noqa: E402

from ordessa_infrastructure.identifiers import RequestKey  # noqa: E402
from ordessa_units.definitions.operations import OperationIntent, StepIntent
from ordessa_infrastructure.encoding.immutable_json import safe_json  # noqa: E402
from pacthold.adapters.sqlite.environment.store import SqliteStorePort  # noqa: E402
from ordessa_units.bindings.contracts import DirectoryBindingRef  # noqa: E402
from ordessa_units.admission.invocation import InvocationIssuer  # noqa: E402

from ordessa_harness_claude_code.native_evidence import (  # noqa: E402
    ClaudeConfigurationEvidence, ClaudeNativeUnitEvidence, ClaudeTerminationEvidence,
)
from ordessa_harness_claude_code.ownership import ClaudeOwnedChannels  # noqa: E402
from ordessa_harness_claude_code.owner_projection import ClaudeOwnerUnitProjection  # noqa: E402

FAMILY_DIGEST = "sha256:" + "c" * 64
FAMILY_PROVIDER = {"environmentNamespace": "env", "providerId": "claude",
                   "ownerActivationRef": {"environmentNamespace": "env",
                                          "pluginId": "claude-independent", "generation": 1},
                   "generation": 1, "contractVersion": "agent-runtime/2",
                   "implementationDigest": FAMILY_DIGEST}
NODE = {"environmentNamespace": "env", "nodeId": "node", "generation": 1}
MODEL_DECLARATION = {"declarationId": "decl-model", "configurationKind": "claude.model",
                     "schemaVersion": "1", "action": "value", "requirement": "required",
                     "payload": {"model": "changed-model"}, "resourceRefs": []}
SESSION_EVIDENCE = "real-native-owner-evidence"


class FamilyPorts:
    """The family's composed evidence ports (identity-shared singletons)."""

    def __init__(self):
        self.native_unit = ClaudeNativeUnitEvidence()
        self.termination = ClaudeTerminationEvidence()
        self.configuration = ClaudeConfigurationEvidence()
        self.channels = ClaudeOwnedChannels()


def family_core_parts(tmp_path, *, with_session=False):
    """Real journal + real core claims (prepare/start/configuration/stop/release).

    When ``with_session`` is set, the controlled session substitute confirms
    the frozen session ledger as well — only the configuration ledger demands
    a confirmed native session binding, and no production session bridge yet
    exists in this tree.
    """
    service, journal, *_ = parts(tmp_path)
    ports = FamilyPorts()
    service.native_unit_evidence = ports.native_unit
    service.termination_evidence = ports.termination
    service.configuration_evidence = ports.configuration
    target = service.scope_authority.scope.owner_ref(FAMILY_PROVIDER)
    request = RequestKey("env", "controlled-principal", "unit-flow")
    directory = DirectoryBindingRef("env", "directory", 1, "sha256:" + "d" * 64)
    bindings = {
        "prepare": {"action": "prepare", "targetRef": NODE, "delegationRef": None, "cleanup": False},
        "start": {"action": "start", "targetRef": NODE, "delegationRef": None, "cleanup": False},
        "configuration": {"action": "applyConfiguration", "targetRef": target,
                          "delegationRef": None, "cleanup": False},
    }
    store = SqliteStorePort(tmp_path / "core.sqlite")
    steps = (StepIntent("prepare", FAMILY_PROVIDER, "input", "prepare-correlation"),
             StepIntent("start", FAMILY_PROVIDER, "start-input", "start-correlation"),
             StepIntent("configuration", FAMILY_PROVIDER, "change-input", "configuration-correlation"))
    intent = OperationIntent("flow-operation", "controlled-unit-flow", None,
                             {"environmentNamespace": "env", "directoryBindingRef": directory.to_dict(),
                              "invocationBindings": bindings,
                              "effectiveDeclarations": [MODEL_DECLARATION]}, steps)
    store.reserve_operation(request, "flow-digest", intent)
    authority = Authority()
    current = CurrentState(FAMILY_PROVIDER, directory, target)
    # The cleanup claims require the exact previously acquired target — the
    # controlled publication substitute acquired this unit's Node target.
    current.acquired = NODE
    current.evidence = {"environmentNamespace": "env", "evidenceRef": "fixture/acquisition"}
    issuer = InvocationIssuer(store, authority, current, clock=lambda: 50)
    service.verifier = issuer.verifier()

    def issued(step):
        binding = bindings[step]
        return issuer.issue(request, "flow-digest", step, binding["action"], binding["targetRef"],
                            cleanup=binding["cleanup"])

    unit, _ = service.reserve_unit(issued("prepare"), provider_ref=FAMILY_PROVIDER,
                                   node_ref=NODE, input_digest="input", private_root_facts=ROOT)
    store.record_operation_step(request, "flow-digest", "prepare", "input", 1, "concluded",
                                {"unitRef": unit.unit_ref})
    if with_session:
        session_ticket = service.begin_session(unit.unit_ref, issued("start"), input_digest="start-input")
        service.record_session(session_ticket, expected_source_revision=2, state="confirmed",
                              evidence=SESSION_EVIDENCE)
        store.record_operation_step(request, "flow-digest", "start", "start-input", 1, "concluded",
                                    {"evidenceRef": SESSION_EVIDENCE})
    publication = {"directoryBindingRef": directory.to_dict(), "managementEpoch": 0,
                   "ownership": "owned", "evidenceRef": {"environmentNamespace": "env",
                                                         "evidenceRef": "owner-publication/original"}}
    return {"records": service, "ports": ports, "unit": unit, "store": store, "request": request,
            "issuer": issuer, "authority": authority, "current": current, "issued": issued,
            "journal": journal, "projection": ClaudeOwnerUnitProjection(
                service, verifier=service.verifier,
                preparation_authority=lambda plan, facts: True,
                publication_owner=lambda unit_, binding: dict(publication)),
            "bindings": bindings, "target": target, "directory": directory,
            "epoch_port": service.epoch_port}


def cleanup_operation(parts, action):
    """One separate real lifecycle operation (one cleanup action per request)."""
    kind, digest = {"stop": "agent-stop", "release": "agent-release"}[action], "cleanup-digest"
    request = RequestKey("env", "controlled-principal", action + "-request")
    binding = {"action": action, "targetRef": NODE, "delegationRef": None, "cleanup": True}
    step = (StepIntent(action, FAMILY_PROVIDER, action + "-input", action + "-correlation"),)
    intent = OperationIntent("lifecycle-" + action, kind, None,
                             {"environmentNamespace": "env",
                              "directoryBindingRef": parts["directory"].to_dict(),
                              "invocationBindings": {action: binding}}, step)
    parts["store"].reserve_operation(request, digest, intent)

    def issued():
        return parts["issuer"].issue(request, digest, action, action, NODE, cleanup=True)

    def query():
        return parts["issuer"].issue_query(request, digest, action)

    return {"request": request, "issued": issued, "query": query, "operation": intent.operation_ref}


def same_reference(left, right):
    try:
        return safe_json(left) == safe_json(right)
    except (TypeError, ValueError):
        return False


class ControlledChannel:
    """A real owner-managed test process with the registry's channel surface.

    The child is a plain sleep process (no model, no network); close() reaps
    it by identity exactly like the production transport path: stdin close,
    terminate, kill, each awaited.
    """

    def __init__(self, argv):
        import subprocess
        self._process = subprocess.Popen(  # noqa: S603 - controlled fixed argv
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def is_alive(self):
        return self._process.poll() is None

    def close(self, *, timeout: float = 5.0):
        if self._process.poll() is not None:
            code = self._process.returncode
        else:
            code = None
            try:
                self._process.stdin.close()
                code = self._process.wait(timeout=timeout)
            except Exception:
                code = None
            if code is None:
                self._process.terminate()
                try:
                    code = self._process.wait(timeout=timeout)
                except Exception:
                    self._process.kill()
                    code = self._process.wait(timeout=timeout)
        try:
            self._process.stdout.close()
            self._process.stderr.close()
        except OSError:
            pass
        return code if isinstance(code, int) else -1

    def break_close(self):
        def broken(*args, **kwargs):
            raise OSError("controlled closing refusal")
        self.close = broken

    def exit(self):
        """Force-terminate the child by identity and reap it."""
        if self._process.poll() is None:
            self._process.terminate()
            self._process.wait(timeout=5)


def sleeping_process():
    import sys
    return ControlledChannel([sys.executable, "-c", "import time; time.sleep(30)"])


def reap_entries(channels):
    for key in list(getattr(channels, "_entries", {})):
        entry = getattr(channels, "_entries", {}).get(key)
        if entry is None:
            continue
        try:
            if entry.channel.is_alive():
                entry.channel.exit()
        except Exception:
            pass


def termination_row(parts, action="stop"):
    with parts["journal"]._connect() as db:
        rows = db.execute("SELECT * FROM harness_unit_terminations WHERE action=?", (action,)).fetchall()
    return rows[-1] if rows else None
