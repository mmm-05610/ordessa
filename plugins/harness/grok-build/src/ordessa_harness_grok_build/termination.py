"""Real grok-build ``NativeTerminationEvidencePort``: process-level termination proof.

The owner verifies the actual stop/release effect against the REAL owned
subprocess handle bound at channel open — exit code and liveness are read
from the process itself, never taken from a caller string:

- the bound record's isolated roots must equal the journal's sealed unit
  roots, and the launch argv must be the pinned installation (fixed
  installation/root);
- the observed PID must be the record's actual subprocess PID;
- the process must have exited, its observed exit code must equal the
  handle's return code, and no ``/proc/<pid>`` residual may remain;
- the caller's evidence must carry exactly this attempt's action and the
  original correlation the records re-bind at record time.

For ``stop`` the factory record must still be held; for ``release`` the
factory record must already be released (release never kills — a live owned
unit is refused to its caller before any claim). A unit with no owned channel
verifies the "nothing owned" fact from this port's own binding registry.
Verified outcomes return only versioned provenance refs.
"""
from __future__ import annotations

import hashlib
import os
import threading
from typing import Any, Mapping

from ordessa_execution_api.environment.operations import safe_json, sealed_mapping
from ordessa_harness_grok_build.client import PROTOCOL
from ordessa_harness_grok_build.runtime_channel import ChannelRecord

TERMINATION_EVIDENCE_FIELDS = frozenset({"action", "correlation", "pid", "exitCode", "observedAt"})
TERMINATION_NONE_FIELDS = frozenset({"action", "correlation", "observedAt", "ownedProcess"})


class GrokBuildTerminationRefused(RuntimeError):
    code = "GROKBUILD_TERMINATION_REFUSED"


def _digits(value: Any) -> bool:
    return isinstance(value, str) and value.isdigit() and len(value) <= 12


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _instant(value: Any) -> bool:
    from datetime import datetime

    if not isinstance(value, str) or not value or len(value) > 64:
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


class GrokBuildTerminationEvidencePort:
    """Production termination evidence owner for the grok-build family.

    Constructed with the deployment's one channel factory (read-only record
    lookups). The provider binds each opened unit channel here; confirmed
    termination facts are verified against the real exited handle at record
    time. No PID, command line, path or secret outside these refs is exposed.
    """

    def __init__(self, factory):
        record_open = getattr(factory, "record", None)
        if not callable(record_open) or getattr(factory, "executable", None) is None:
            raise GrokBuildTerminationRefused("termination evidence requires the owned channel factory")
        self._factory = factory
        self._bindings: dict[str, ChannelRecord] = {}  # unit id -> owned channel record, live only
        self._lock = threading.RLock()

    # -- provider binding ---------------------------------------------------
    def bind_unit_channel(self, unit_ref, record) -> None:
        """Bind one opened unit channel for later termination verification."""
        if (not isinstance(unit_ref, str) or not unit_ref or len(unit_ref) > 256
                or not isinstance(record, ChannelRecord)):
            raise GrokBuildTerminationRefused("owned unit channel record binding requires unit and record")
        with self._lock:
            existing = self._bindings.get(unit_ref)
            if existing is not None and existing is not record:
                raise GrokBuildTerminationRefused("unit already bound to another owned channel record")
            self._bindings[unit_ref] = record

    # -- records-side evidence port ------------------------------------------
    def verify_termination(self, unit, action, correlation, evidence) -> Mapping[str, str]:
        if (not isinstance(action, str) or action not in ("stop", "release")
                or not isinstance(correlation, str) or not correlation or len(correlation) > 2048):
            raise GrokBuildTerminationRefused("termination verification requires the original attempt facts")
        if not isinstance(evidence, Mapping):
            raise GrokBuildTerminationRefused("termination evidence must be the observed effect facts")
        if evidence.get("action") != action or evidence.get("correlation") != correlation:
            raise GrokBuildTerminationRefused("termination evidence belongs to another attempt")
        if hasattr(evidence, "get") and evidence.get("ownedProcess") is not None:
            return self._verify_no_owned_process(unit, action, correlation, evidence)
        return self._verify_process_effect(unit, action, correlation, evidence)

    def observe_termination(self, unit, action, correlation) -> Mapping[str, str]:
        """Read-only process facts for cold reconciliation; no effect, no claim.

        Reconciliation along the ORIGINAL correlation stays read-only: this
        re-observes the real exited handle so the records' reconcile path can
        conclude a retained attempt with owner-verified facts, or nothing.
        """
        if (not isinstance(action, str) or action not in ("stop", "release")
                or not isinstance(correlation, str) or not correlation or len(correlation) > 2048):
            raise GrokBuildTerminationRefused("termination observation requires the original attempt facts")
        unit_ref, _ = self._unit_facts(unit)
        observed = {"action": action, "correlation": correlation,
                    "observedAt": _now()}
        with self._lock:
            record = self._bindings.get(unit_ref)
        if record is None:
            observed["ownedProcess"] = "none"
        else:
            code = record.channel._process.poll()
            if code is None:
                raise GrokBuildTerminationRefused("owned process is still running; no termination fact exists")
            observed["pid"] = str(record.channel._process.pid)
            observed["exitCode"] = str(int(code))
        try:
            return sealed_mapping(observed)
        except (TypeError, ValueError) as error:
            raise GrokBuildTerminationRefused("termination observation is not JSON-encodable") from error

    # -- internals -------------------------------------------------------------
    def _unit_facts(self, unit):
        facts = getattr(unit, "facts", None)
        ref = getattr(unit, "unit_ref", None)
        if (not isinstance(facts, Mapping) or not isinstance(ref, str) or not ref
                or not isinstance(facts.get("privateRootFacts"), Mapping)):
            raise GrokBuildTerminationRefused("original unit reservation facts unavailable")
        return ref, facts

    def _verify_no_owned_process(self, unit, action, correlation, evidence):
        unit_ref, facts = self._unit_facts(unit)
        if (set(evidence) != TERMINATION_NONE_FIELDS or evidence.get("ownedProcess") != "none"
                or not _instant(evidence.get("observedAt"))):
            raise GrokBuildTerminationRefused("no-owned-process termination evidence shape differs")
        with self._lock:
            bound = self._bindings.get(unit_ref)
        if bound is not None:
            raise GrokBuildTerminationRefused("owned channel record still exists for this unit")
        canonical = {"unit": safe_json(unit.public_ref), "action": action,
                     "correlation": correlation, "pid": "none", "exitCode": "none",
                     "observedAt": evidence["observedAt"]}
        return self._refs(canonical)

    def _verify_process_effect(self, unit, action, correlation, evidence):
        unit_ref, facts = self._unit_facts(unit)
        if (set(evidence) != TERMINATION_EVIDENCE_FIELDS
                or not _digits(evidence.get("pid")) or not _digits(evidence.get("exitCode"))
                or not _instant(evidence.get("observedAt"))):
            raise GrokBuildTerminationRefused("termination evidence shape differs")
        with self._lock:
            record = self._bindings.get(unit_ref)
        if record is None:
            raise GrokBuildTerminationRefused("no owned channel record was ever bound for this unit")
        # Fixed installation and the journal's sealed isolated roots.
        if record.spec.argv[0] != self._factory.executable:
            raise GrokBuildTerminationRefused("owned process argv is not the pinned installation")
        if safe_json(record.roots) != safe_json(facts["privateRootFacts"]):
            raise GrokBuildTerminationRefused("owned process roots differ from the original unit roots")
        process = record.channel._process
        if str(process.pid) != evidence["pid"]:
            raise GrokBuildTerminationRefused("observed pid differs from the owned subprocess")
        code = process.poll()
        if code is None:
            raise GrokBuildTerminationRefused("owned process is still running; no termination effect exists")
        if str(int(code)) != evidence["exitCode"]:
            raise GrokBuildTerminationRefused("observed exit code differs from the real subprocess exit")
        if os.path.exists(f"/proc/{process.pid}"):
            raise GrokBuildTerminationRefused("residual process identity still present")
        try:
            held = self._factory.record(record.entry) is record
        except Exception:
            held = False  # any factory refusal means this record is no longer held
        if action == "stop" and not held:
            raise GrokBuildTerminationRefused("stop evidence requires the held owned channel record")
        if action == "release" and held:
            raise GrokBuildTerminationRefused("release evidence requires the released channel record")
        canonical = {"unit": safe_json(unit.public_ref), "action": action,
                     "correlation": correlation, "pid": evidence["pid"],
                     "exitCode": evidence["exitCode"], "observedAt": evidence["observedAt"]}
        return self._refs(canonical)

    @staticmethod
    def _refs(canonical: Mapping[str, str]) -> Mapping[str, str]:
        digest = hashlib.sha256(safe_json(canonical).encode()).hexdigest()
        try:
            return sealed_mapping({"nativeRealm": PROTOCOL,
                                   "action": canonical["action"],
                                   "processRef": "grok-build-process/" + canonical["pid"],
                                   "exitRef": "exit/" + canonical["exitCode"],
                                   "evidenceRef": "grok-build-termination/" + digest})
        except (TypeError, ValueError) as error:
            raise GrokBuildTerminationRefused("termination provenance refs are not JSON-encodable") from error
