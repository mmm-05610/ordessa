"""Claude's agent-runtime/2 contribution, without a second registry or ledger.

Planning works without installations. Effectful capability is explicitly absent
until deployment composes existing UnitRecords, invocation verification and
native owner projections. Missing ports fail typed before dispatch. This file
does not hide an unimplemented universal runtime behind a success response.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Mapping

from pacthold.agents.public import (
    AgentContributionSet, RuntimeProviderDescriptor, RUNTIME_PROVIDER_VERSION,
    ConfigurationUnsupported, ConfigurationDescription, ConfigurationChangeResult,
    ConfigurationRevisionConflict, UnitInspection, ConfigurationSnapshot,
)
from .native_channel import FAMILY_ID, COMMAND_CATALOG_ID, compile_config, plan_launch, channel_report
from .sdk import SDK_VERSION


class ClaudeProviderUnavailable(ConfigurationUnsupported):
    code = "CLAUDE_PROVIDER_UNAVAILABLE"


class ClaudeCodeRuntimeProvider:
    """No activation identity supplied by the author; host grants it via registry.

    ``unit_records`` is the existing journal's UnitRecords object. ``unit_port``
    is its trusted owner projection/native binding, not a new store. Its exact
    supported_methods must be supplied by deployment and are checked for methods.
    The object must not claim methods whose effect/confirmation is unavailable.
    """
    _PURE = ("describe_definition", "inspect_installation", "assess_configuration", "plan_preparation")
    _PORT = ("start", "query_step", "describe_access", "connect", "inspect_unit",
             "describe_configuration", "inspect_configuration", "apply_configuration",
             "query_change", "stop", "release", "recover")

    def __init__(self, *, definition_ref, implementation_digest, verifier=None,
                 unit_records=None, unit_port=None, preparation_authority=None):
        self._verifier, self._records, self._units = verifier, unit_records, unit_port
        self._preparation_authority = preparation_authority
        supported = list(self._PURE)
        if unit_records is not None:
            if not callable(getattr(unit_records, "reserve_unit", None)):
                raise ClaudeProviderUnavailable("existing UnitRecords reservation port required")
            # A caller-selected plan is not authorized by merely copying a
            # valid claim's digest. Root/native plan must match the fixed core
            # operation context using its deployment-owned original-store cut.
            if (verifier is not None and getattr(unit_records, "verifier", None) is verifier
                    and callable(getattr(preparation_authority, "verify_preparation", None))):
                supported.append("prepare")
        if unit_port is not None:
            declared = getattr(unit_port, "supported_methods", ())
            if (not isinstance(declared, tuple) or len(set(declared)) != len(declared)
                    or any(method not in self._PORT or not callable(getattr(unit_port, method, None))
                           for method in declared)):
                raise ClaudeProviderUnavailable("unit owner must declare exact implemented public methods")
            if verifier is None:
                raise ClaudeProviderUnavailable("unit owner needs explicit invocation verifier")
            supported.extend(declared)
        self.descriptor = RuntimeProviderDescriptor(FAMILY_ID, RUNTIME_PROVIDER_VERSION,
            definition_ref, implementation_digest, tuple(supported))

    def contributions(self):
        return AgentContributionSet(agent_runtime_providers=(self,))

    def _required(self, method):
        if method not in self.descriptor.supported_methods:
            raise ClaudeProviderUnavailable("Claude runtime method has no admitted implementation: " + method)

    def describe_definition(self, definition_ref):
        if definition_ref != self.descriptor.definition_ref:
            raise ClaudeProviderUnavailable("definition differs from fixed provider descriptor")
        return {"definitionRef": dict(self.descriptor.definition_ref), "familyId": FAMILY_ID,
                "commandCatalogId": COMMAND_CATALOG_ID, "channel": "claude-agent-sdk",
                "sdkVersion": SDK_VERSION, "runtimeReady": "unknown",
                "nativeFacts": channel_report(), "supportedMethods": list(self.descriptor.supported_methods)}

    def inspect_installation(self, binding):
        # Explicit path only, no execution, SDK imports, PATH or login probing.
        if not isinstance(binding, Mapping) or set(binding) != {"executable", "artifactDigest"}:
            raise ClaudeProviderUnavailable("explicit executable and expected digest required")
        path = Path(binding["executable"])
        if not path.is_absolute() or not path.is_file():
            return {"available": False, "artifactPresent": False, "executableAvailable": False,
                    "reason": "executableMissing", "runtimeReady": "unknown"}
        expected = binding["artifactDigest"]
        if not isinstance(expected, str) or not expected.startswith("sha256:") or len(expected) != 71:
            raise ClaudeProviderUnavailable("fixed installation digest required")
        try:
            with path.open("rb") as stream:
                checksum = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    checksum.update(chunk)
                digest = "sha256:" + checksum.hexdigest()
        except (OSError, ValueError):
            raise ClaudeProviderUnavailable("specified installation could not be inspected") from None
        if digest != expected:
            raise ClaudeProviderUnavailable("installation digest differs from admitted binding")
        executable = os.access(path, os.X_OK)
        return {"available": executable, "artifactPresent": True, "executableAvailable": executable,
                "reason": None if executable else "artifactNotExecutable",
                "artifactDigest": digest, "runtimeReady": "unknown",
                "protocolCompatibility": "unverified", "sdkVersion": SDK_VERSION}

    def assess_configuration(self, manifest, installation, context):
        # Family schema is owned here; secrets/resources require owner material
        # acquisition first. Pure planning does not resolve references or log them.
        if not isinstance(manifest, Mapping):
            raise ClaudeProviderUnavailable("explicit compiled Claude configuration materials required")
        return {"compiled": compile_config(manifest, bidirectional=True),
                "runtimeReady": "unknown", "installationAvailable": installation.get("available") is True}

    def plan_preparation(self, snapshot, context, correlation):
        if (not isinstance(context, Mapping) or set(context) != {"home", "workspace", "materials", "privateRootFacts"}
                or not isinstance(correlation, Mapping)):
            raise ClaudeProviderUnavailable("explicit owner preparation roots/materials/correlation required")
        compiled = compile_config(context["materials"], bidirectional=True)
        native = plan_launch(home=context["home"], workspace=context["workspace"],
                             extra_args=tuple(compiled["args"]), bidirectional=True)
        # This is a private provider plan, never a public ready Unit/Node.
        return {"nativePlan": native, "privateRootFacts": context["privateRootFacts"],
                "profileSnapshot": snapshot, "correlation": dict(correlation), "channel": "claude-agent-sdk"}

    def prepare(self, plan, invocation_context):
        self._required("prepare")
        facts = invocation_context.facts
        if not isinstance(plan, Mapping) or "privateRootFacts" not in plan or plan.get("channel") != "claude-agent-sdk":
            raise ClaudeProviderUnavailable("fixed explicit Claude preparation plan required")
        provider = facts["providerRef"]
        if (provider.get("providerId") != FAMILY_ID
                or provider.get("contractVersion") != RUNTIME_PROVIDER_VERSION
                or provider.get("implementationDigest") != self.descriptor.implementation_digest
                or provider.get("environmentNamespace") != self.descriptor.definition_ref["environmentNamespace"]
                or facts["targetRef"].get("environmentNamespace") != provider.get("environmentNamespace")
                or getattr(self._records, "verifier", None) is not self._verifier):
            raise ClaudeProviderUnavailable("prepare provider or original journal verifier differs")
        if self._preparation_authority.verify_preparation(plan, facts) is not True:
            raise ClaudeProviderUnavailable("supplied preparation differs from fixed authorized operation plan")
        # UnitRecords consumes the authentic prepare context and reserves the
        # canonical scope in its existing SQLite transaction before any launch.
        unit, created = self._records.reserve_unit(invocation_context,
            provider_ref=provider, node_ref=facts["targetRef"],
            input_digest=facts["inputDigest"], private_root_facts=plan["privateRootFacts"])
        return {"unitReservation": unit, "created": created, "nativeStarted": False}

    def _read(self, method, *args):
        self._required(method)
        return getattr(self._units, method)(*args)

    def _effect(self, method, action, unit_ref, context, *args):
        self._required(method)
        inspection = self.inspect_unit(unit_ref)
        facts = context.facts
        if facts["providerRef"] != inspection.provider_ref or facts["managementEpoch"] != inspection.management_epoch:
            raise ClaudeProviderUnavailable("native unit owner/epoch differs from invocation")
        if method == "apply_configuration" and facts["targetRef"] != inspection.configuration_target_ref:
            raise ClaudeProviderUnavailable("configuration invocation targets another native scope")
        verified = self._verifier.verify_and_consume(context, action, inspection.provider_ref,
            facts["targetRef"], facts["inputDigest"])
        if verified.get("query") is not False:
            raise ClaudeProviderUnavailable("effect requires original durable invocation claim")
        if method in {"stop", "release"} and inspection.ownership != "owned":
            raise ClaudeProviderUnavailable("destructive lifecycle requires verified owned unit")
        return getattr(self._units, method)(unit_ref, *args, context)

    def start(self, prepared_unit, invocation_context):
        # Trusted owner must call existing begin_session BEFORE its SDK open,
        # and record_session only after native evidence. Until composed it is
        # absent from supported_methods; this adapter never opens a substitute.
        self._required("start")
        return self._units.start(prepared_unit, invocation_context)

    def query_step(self, correlation, authorized_read_context):
        self._required("query_step")
        self._verify_read(authorized_read_context)
        return self._read("query_step", correlation, authorized_read_context)

    def _verify_read(self, context, inspection=None):
        facts = context.facts
        if inspection is not None and (facts["providerRef"] != inspection.provider_ref
                or facts["managementEpoch"] != inspection.management_epoch
                or facts["targetRef"] != inspection.configuration_target_ref):
            raise ClaudeProviderUnavailable("read authority differs from original native owner/scope")
        verified = self._verifier.verify_and_consume(context, "query", facts["providerRef"],
                                                     facts["targetRef"], facts["inputDigest"])
        if verified.get("query") is not True:
            raise ClaudeProviderUnavailable("query requires current authorized read context")

    def describe_access(self, unit_ref):
        return self._read("describe_access", unit_ref)

    def connect(self, unit_ref, authorized_lease):
        # Owner returns its authorized entrance; never an unguarded raw SDK.
        return self._read("connect", unit_ref, authorized_lease)

    def inspect_unit(self, unit_ref):
        result = self._read("inspect_unit", unit_ref)
        if not isinstance(result, UnitInspection) or result.unit_ref != unit_ref:
            raise ClaudeProviderUnavailable("current native unit projection unavailable")
        return result

    def describe_configuration(self, unit_ref):
        result = self._read("describe_configuration", unit_ref)
        if not isinstance(result, tuple) or any(not isinstance(item, ConfigurationDescription) for item in result):
            raise ClaudeProviderUnavailable("typed native configuration descriptions required")
        return result

    def inspect_configuration(self, unit_ref):
        result = self._read("inspect_configuration", unit_ref)
        if not isinstance(result, ConfigurationSnapshot) or result.unit_ref != unit_ref:
            raise ClaudeProviderUnavailable("actual native snapshot unavailable")
        return result

    def apply_configuration(self, unit_ref, change_request, invocation_context):
        snapshot = self.inspect_configuration(unit_ref)
        if snapshot.source_revision is None or snapshot.comparison_guarantee == "unavailable":
            raise ClaudeProviderUnavailable("configuration revision comparison unavailable")
        if snapshot.source_revision != change_request.expected_configuration_revision:
            raise ConfigurationRevisionConflict("configuration revision differs from native owner")
        # Owner must serialize/recheck again at the actual SDK dispatch cut.
        result = self._effect("apply_configuration", "applyConfiguration", unit_ref,
                              invocation_context, change_request)
        if not isinstance(result, ConfigurationChangeResult):
            raise ClaudeProviderUnavailable("native ACK cannot replace typed operation confirmation")
        return result

    def query_change(self, unit_ref, operation_ref, authorized_read_context):
        self._required("query_change")
        inspection = self.inspect_unit(unit_ref)
        if authorized_read_context.facts["operationRef"] != operation_ref:
            raise ClaudeProviderUnavailable("read authority belongs to another operation")
        self._verify_read(authorized_read_context, inspection)
        result = self._read("query_change", unit_ref, operation_ref, authorized_read_context)
        if not isinstance(result, ConfigurationChangeResult) or result.operation_ref != operation_ref:
            raise ClaudeProviderUnavailable("original operation native evidence unavailable")
        return result

    def stop(self, unit_ref, invocation_context):
        return self._effect("stop", "stop", unit_ref, invocation_context)

    def release(self, unit_ref, invocation_context):
        return self._effect("release", "release", unit_ref, invocation_context)

    def recover(self, native_binding, invocation_context):
        self._required("recover")
        # There is deliberately no latest-session selection or new SDK launch.
        return self._units.recover(native_binding, invocation_context)
