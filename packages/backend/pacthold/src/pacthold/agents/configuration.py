"""AU-1 configuration contracts. Facts come only from the instance owner.

These immutable DTOs grant no authority and perform no native effects.
Declarations retain the existing Profile vocabulary; no brand schema lives here.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Mapping

from ordessa_environment_api import IdentityMismatchError
from ordessa_environment_api.operations import safe_json, sealed_mapping
from .contracts import manifest_content, _safe_tree

CONFIGURATION_CONTRACT_VERSION = "agent-configuration/1"
ITEM_OUTCOMES = frozenset({"applied", "deferred", "restartRequired", "rejected", "conflict", "unknown"})


class ConfigurationContractError(ValueError):
    code = "CONFIGURATION_CONTRACT_INVALID"


class ConfigurationUnsupported(ConfigurationContractError):
    code = "CONFIGURATION_UNSUPPORTED"


class ConfigurationRevisionConflict(IdentityMismatchError):
    code = "CONFIGURATION_REVISION_CONFLICT"


def _name(value):
    if not isinstance(value, str) or not value or value.strip() != value or len(value) > 256 or any(ord(c) < 32 for c in value):
        raise ConfigurationContractError("bounded nonempty identity required")
    return value


def _reference(value, environment=None):
    if not isinstance(value, Mapping) or len(value) < 2:
        raise ConfigurationContractError("complete scoped owner reference required")
    _name(value.get("environmentNamespace"))
    if environment is not None and value["environmentNamespace"] != environment:
        raise ConfigurationContractError("configuration reference environment differs")
    plain = json.loads(safe_json(value))
    _safe_tree(plain)
    return sealed_mapping(plain)


def _snapshot(value):
    plain = json.loads(safe_json(value))
    _safe_tree(plain)
    return sealed_mapping(plain)


@dataclass(frozen=True)
class ApplicationPolicy:
    allow_deferred: bool = False
    allow_restart: bool = False

    def __post_init__(self):
        if type(self.allow_deferred) is not bool or type(self.allow_restart) is not bool:
            raise ConfigurationContractError("application policy requires explicit booleans")

    def to_dict(self):
        return {"allowDeferred": self.allow_deferred, "allowRestart": self.allow_restart}


@dataclass(frozen=True)
class ConfigurationChangeRequest:
    request_id: str
    expected_configuration_revision: str
    declarations: tuple[Mapping, ...]
    application_policy: ApplicationPolicy = ApplicationPolicy()

    def __post_init__(self):
        _name(self.request_id)
        _name(self.expected_configuration_revision)
        if not isinstance(self.application_policy, ApplicationPolicy) or not isinstance(self.declarations, tuple) or not self.declarations:
            raise ConfigurationContractError("explicit nonempty change declarations required")
        plain = [json.loads(safe_json(item)) for item in self.declarations]
        environments = {ref.get("environmentNamespace") for item in plain for ref in item.get("resourceRefs", [])}
        if len(environments) > 1:
            raise ConfigurationContractError("declaration resource environments differ")
        environment = next(iter(environments), "contract-validation")
        manifest_content({"harnessDefinitionRef": {"environmentNamespace": environment, "definitionId": "contract"},
                          "schemaVersion": CONFIGURATION_CONTRACT_VERSION, "declarations": plain}, environment)
        object.__setattr__(self, "declarations", tuple(sealed_mapping(item) for item in plain))

    def to_dict(self):
        return {"requestId": self.request_id, "expectedConfigurationRevision": self.expected_configuration_revision,
                "declarations": [json.loads(safe_json(item)) for item in self.declarations],
                "applicationPolicy": self.application_policy.to_dict()}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {"requestId", "expectedConfigurationRevision", "declarations", "applicationPolicy"}:
            raise ConfigurationContractError("change request fields differ")
        policy = value["applicationPolicy"]
        if not isinstance(policy, dict) or set(policy) != {"allowDeferred", "allowRestart"} or not isinstance(value["declarations"], list):
            raise ConfigurationContractError("application policy or declarations fields differ")
        return cls(value["requestId"], value["expectedConfigurationRevision"], tuple(value["declarations"]),
                   ApplicationPolicy(policy["allowDeferred"], policy["allowRestart"]))


@dataclass(frozen=True)
class ConfigurationDescription:
    configuration_kind: str
    schema_version: str
    input_schema: Mapping
    supported_actions: tuple[str, ...]
    scope: str | None
    application_modes: tuple[str, ...]
    confirmation: str
    support_status: str

    def __post_init__(self):
        _name(self.configuration_kind); _name(self.schema_version)
        if (not isinstance(self.supported_actions, tuple)
                or len(set(self.supported_actions)) != len(self.supported_actions)
                or any(item not in {"value", "reset", "disabled"} for item in self.supported_actions)
                or self.scope not in {"instance", "session", "nextInput", None}
                or not isinstance(self.application_modes, tuple)
                or len(set(self.application_modes)) != len(self.application_modes)
                or any(item not in {"live", "deferred", "restart"} for item in self.application_modes)
                or self.confirmation not in {"readback", "operationReceipt", "none"}
                or self.support_status not in {"supported", "unsupported", "unknown"}):
            raise ConfigurationContractError("invalid owner configuration description")
        if self.support_status == "supported" and (not self.supported_actions or not self.application_modes or self.scope is None):
            raise ConfigurationContractError("supported configuration requires explicit actions, scope and modes")
        object.__setattr__(self, "input_schema", sealed_mapping(json.loads(safe_json(self.input_schema))))

    def to_dict(self):
        return {"configurationKind": self.configuration_kind, "schemaVersion": self.schema_version,
                "inputSchema": json.loads(safe_json(self.input_schema)), "supportedActions": list(self.supported_actions),
                "scope": self.scope, "applicationModes": list(self.application_modes),
                "confirmation": self.confirmation, "supportStatus": self.support_status}


@dataclass(frozen=True)
class ConfigurationSnapshot:
    unit_ref: Mapping
    scope_ref: Mapping
    source_revision: str | None
    observed_at: str
    configuration: Mapping
    unknown_items: tuple[str, ...]
    confirmation_evidence: Mapping
    comparison_guarantee: str

    def __post_init__(self):
        unit = _reference(self.unit_ref)
        object.__setattr__(self, "unit_ref", unit)
        object.__setattr__(self, "scope_ref", _reference(self.scope_ref, unit["environmentNamespace"]))
        if self.source_revision is not None:
            _name(self.source_revision)
        elif self.comparison_guarantee != "unavailable":
            raise ConfigurationContractError("unknown revision cannot promise version comparison")
        _name(self.observed_at)
        from datetime import datetime
        try:
            instant = datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
            if instant.tzinfo is None: raise ValueError()
        except ValueError:
            raise ConfigurationContractError("snapshot observation requires an explicit timezone") from None
        if self.comparison_guarantee not in {"nativeAtomic", "ownerSerialized", "unavailable"}:
            raise ConfigurationContractError("comparison guarantee must be declared")
        if not isinstance(self.unknown_items, tuple) or len(set(self.unknown_items)) != len(self.unknown_items):
            raise ConfigurationContractError("unknown fields must be explicit and unique")
        for name in self.unknown_items: _name(name)
        if any(name in self.configuration for name in self.unknown_items):
            raise ConfigurationContractError("unknown configuration cannot also be actual")
        if any(name in self.configuration for name in ("desired", "pending")):
            raise ConfigurationContractError("desired and pending are not actual configuration")
        object.__setattr__(self, "configuration", _snapshot(self.configuration))
        object.__setattr__(self, "confirmation_evidence", _reference(self.confirmation_evidence, unit["environmentNamespace"]))

    def to_dict(self):
        return {"unitRef": json.loads(safe_json(self.unit_ref)), "scopeRef": json.loads(safe_json(self.scope_ref)),
                "sourceRevision": self.source_revision, "observedAt": self.observed_at,
                "configuration": json.loads(safe_json(self.configuration)), "unknownItems": list(self.unknown_items),
                "confirmationEvidence": json.loads(safe_json(self.confirmation_evidence)),
                "comparisonGuarantee": self.comparison_guarantee}


@dataclass(frozen=True)
class ConfigurationItemResult:
    declaration_id: str
    outcome: str
    confirmation: Mapping | None = None

    def __post_init__(self):
        _name(self.declaration_id)
        if self.outcome not in ITEM_OUTCOMES:
            raise ConfigurationContractError("unknown configuration item outcome")
        if self.outcome == "applied" and self.confirmation is None:
            raise ConfigurationContractError("applied requires operation-bound owner confirmation")
        if self.confirmation is not None:
            value = self.confirmation
            if not isinstance(value, Mapping) or set(value) != {"operationRef", "unitRef", "scopeRef", "requestDigest", "evidenceRef"}:
                raise ConfigurationContractError("complete operation-bound confirmation required")
            _name(value["operationRef"]); _name(value["requestDigest"])
            unit = _reference(value["unitRef"])
            _reference(value["scopeRef"], unit["environmentNamespace"])
            _reference(value["evidenceRef"], unit["environmentNamespace"])
            object.__setattr__(self, "confirmation", _snapshot(value))

    def to_dict(self):
        return {"declarationId": self.declaration_id, "outcome": self.outcome,
                "confirmation": None if self.confirmation is None else json.loads(safe_json(self.confirmation))}


@dataclass(frozen=True)
class ConfigurationChangeResult:
    operation_ref: str
    item_results: tuple[ConfigurationItemResult, ...]
    confirmed_snapshot: ConfigurationSnapshot | None = None

    def __post_init__(self):
        _name(self.operation_ref)
        if not isinstance(self.item_results, tuple) or not self.item_results or any(not isinstance(item, ConfigurationItemResult) for item in self.item_results):
            raise ConfigurationContractError("explicit item results required")
        if len({item.declaration_id for item in self.item_results}) != len(self.item_results):
            raise ConfigurationContractError("duplicate item result")
        if self.confirmed_snapshot is not None and not isinstance(self.confirmed_snapshot, ConfigurationSnapshot):
            raise ConfigurationContractError("typed owner snapshot required")
        for item in self.item_results:
            if item.confirmation is not None and item.confirmation["operationRef"] != self.operation_ref:
                raise ConfigurationContractError("item confirmation belongs to another operation")
            if item.outcome == "applied" and self.confirmed_snapshot is not None:
                if safe_json(item.confirmation["unitRef"]) != safe_json(self.confirmed_snapshot.unit_ref) or safe_json(item.confirmation["scopeRef"]) != safe_json(self.confirmed_snapshot.scope_ref):
                    raise ConfigurationContractError("confirmed snapshot target differs")

    @property
    def overall_outcome(self):
        outcomes = {item.outcome for item in self.item_results}
        return next(iter(outcomes)) if len(outcomes) == 1 else "partial"

    def to_dict(self):
        return {"operationRef": self.operation_ref, "overallOutcome": self.overall_outcome,
                "itemResults": [item.to_dict() for item in self.item_results],
                "confirmedSnapshot": None if self.confirmed_snapshot is None else self.confirmed_snapshot.to_dict()}


@dataclass(frozen=True)
class UnitInspection:
    """Current owner projection; never stored as a second runtime authority."""
    unit_ref: Mapping
    provider_ref: Mapping
    configuration_target_ref: Mapping
    directory_binding_ref: object
    management_epoch: int
    ownership: str
    source_revision: str
    observed_at: str
    evidence_ref: Mapping

    def __post_init__(self):
        from .directory import DirectoryBindingRef
        unit = _reference(self.unit_ref)
        environment = unit['environmentNamespace']
        object.__setattr__(self, 'unit_ref', unit)
        for name in ('provider_ref', 'configuration_target_ref', 'evidence_ref'):
            object.__setattr__(self, name, _reference(getattr(self, name), environment))
        if (not isinstance(self.directory_binding_ref, DirectoryBindingRef)
                or self.directory_binding_ref.environment_namespace != environment
                or type(self.management_epoch) is not int or self.management_epoch < 0
                or self.ownership not in {'owned', 'borrowed', 'unknown'}):
            raise ConfigurationContractError('current owner unit evidence required')
        _name(self.source_revision); _name(self.observed_at)
        from datetime import datetime
        try:
            if datetime.fromisoformat(self.observed_at.replace('Z', '+00:00')).tzinfo is None:
                raise ValueError()
        except ValueError:
            raise ConfigurationContractError('unit inspection requires a timezone') from None
