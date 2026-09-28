# T009 import migration map (old `pacthold.*` → now)

Baseline: pre-migration commit 14cdb563e5 (328 IDs all green). Symbols are top-level defs/classes/UPPER constants.

Legend: **core** = still defined in `packages/pacthold` (path shown); **compat** = relocated to
`plugins/runtime-compat` (import as `pacthold_runtime_compat.<module>`); **removed** = deliberately
gone from the kernel at T009 (no kernel replacement; the relocated copy or a test stand-in is the home).

## `pacthold.cli`

| symbol | now at |
| --- | --- |
| `PROG` | core (unchanged: `pacthold.cli`) |
| `cmd_doctor` | core (unchanged: `pacthold.cli`) |
| `cmd_help` | core (unchanged: `pacthold.cli`) |
| `cmd_launch` | compat: `pacthold_runtime_compat.cli` |
| `cmd_plugins_list` | core (unchanged: `pacthold.cli`) |
| `cmd_web` | compat: `pacthold_runtime_compat.cli` |
| `main` | core (unchanged: `pacthold.cli`) |

## `pacthold.cli.commands.plugins`

| symbol | now at |
| --- | --- |
| `cmd_plugins_doctor` | core (unchanged: `pacthold.cli.commands.plugins`) |
| `cmd_plugins_inspect` | core (unchanged: `pacthold.cli.commands.plugins`) |

## `pacthold.core.descriptors`

| symbol | now at |
| --- | --- |
| `ResourceProviderDescriptor` | core (unchanged: `pacthold.core.descriptors`) |
| `validate_component_id` | core (unchanged: `pacthold.core.descriptors`) |
| `validate_contract_id` | core (unchanged: `pacthold.core.descriptors`) |

## `pacthold.core.dispatch`

| symbol | now at |
| --- | --- |
| `DispatchCoordinator` | core (unchanged: `pacthold.core.dispatch`) |
| `ExecutionView` | core (unchanged: `pacthold.core.dispatch`) |
| `LeaseView` | core (unchanged: `pacthold.core.dispatch`) |
| `StopDispatchResult` | core (unchanged: `pacthold.core.dispatch`) |
| `SubmitResult` | core (unchanged: `pacthold.core.dispatch`) |
| `lease_fact_id` | core (unchanged: `pacthold.core.dispatch`) |
| `reconcile_support_of` | core (unchanged: `pacthold.core.dispatch`) |
| `store_execution_facts` | core (unchanged: `pacthold.core.dispatch`) |
| `store_lease_facts` | core (unchanged: `pacthold.core.dispatch`) |

## `pacthold.core.dtos`

| symbol | now at |
| --- | --- |
| `AcquireRequest` | core (unchanged: `pacthold.core.dtos`) |
| `AcquireResult` | core (unchanged: `pacthold.core.dtos`) |
| `Observation` | core (unchanged: `pacthold.core.dtos`) |
| `ReconcileRequest` | core (unchanged: `pacthold.core.dtos`) |
| `ReconcileResult` | core (unchanged: `pacthold.core.dtos`) |
| `ReleaseRequest` | core (unchanged: `pacthold.core.dtos`) |
| `ReleaseResult` | core (unchanged: `pacthold.core.dtos`) |
| `ResolvedInputDeclaration` | core (unchanged: `pacthold.core.dtos`) |
| `RunHandle` | core (unchanged: `pacthold.core.dtos`) |
| `StartRequest` | core (unchanged: `pacthold.core.dtos`) |
| `StartResult` | core (unchanged: `pacthold.core.dtos`) |
| `StopRequest` | core (unchanged: `pacthold.core.dtos`) |
| `StopResult` | core (unchanged: `pacthold.core.dtos`) |

## `pacthold.core.enums`

| symbol | now at |
| --- | --- |
| `AcquireOutcome` | core (unchanged: `pacthold.core.enums`) |
| `ExecutionState` | core (unchanged: `pacthold.core.enums`) |
| `LeaseState` | core (unchanged: `pacthold.core.enums`) |
| `ObservationKind` | core (unchanged: `pacthold.core.enums`) |
| `OperationState` | core (unchanged: `pacthold.core.enums`) |
| `OwnershipKind` | core (unchanged: `pacthold.core.enums`) |
| `ReconcileOutcome` | core (unchanged: `pacthold.core.enums`) |
| `ReconcileSupport` | core (unchanged: `pacthold.core.enums`) |
| `ReleaseOutcome` | core (unchanged: `pacthold.core.enums`) |
| `StartOutcome` | core (unchanged: `pacthold.core.enums`) |
| `StopOutcome` | core (unchanged: `pacthold.core.enums`) |

## `pacthold.core.errors`

| symbol | now at |
| --- | --- |
| `BatchAlreadyUsedError` | core (unchanged: `pacthold.core.errors`) |
| `ContractNotRegisteredError` | core (unchanged: `pacthold.core.errors`) |
| `ContractWiringPending` | core (unchanged: `pacthold.core.errors`) |
| `CoreDTOError` | core (unchanged: `pacthold.core.errors`) |
| `CoreError` | core (unchanged: `pacthold.core.errors`) |
| `DispatchError` | core (unchanged: `pacthold.core.errors`) |
| `InvalidContractIdError` | core (unchanged: `pacthold.core.errors`) |
| `InvalidProviderIdError` | core (unchanged: `pacthold.core.errors`) |
| `MissingContractReferenceError` | core (unchanged: `pacthold.core.errors`) |
| `OwnerBusyError` | core (unchanged: `pacthold.core.errors`) |
| `OwnerNotRegisteredError` | core (unchanged: `pacthold.core.errors`) |
| `PlanDigestConflictError` | core (unchanged: `pacthold.core.errors`) |
| `ProviderNotRegisteredError` | core (unchanged: `pacthold.core.errors`) |
| `ProviderVersionMismatchError` | core (unchanged: `pacthold.core.errors`) |
| `ReconcileUnsupportedError` | core (unchanged: `pacthold.core.errors`) |
| `RegistrationConflictError` | core (unchanged: `pacthold.core.errors`) |
| `RuntimeClosedError` | core (unchanged: `pacthold.core.errors`) |
| `TerminalExecutionError` | core (unchanged: `pacthold.core.errors`) |
| `UnknownExecutionError` | core (unchanged: `pacthold.core.errors`) |
| `UnknownOperationError` | core (unchanged: `pacthold.core.errors`) |

## `pacthold.core.plan`

| symbol | now at |
| --- | --- |
| `ExecutionPlan` | core (unchanged: `pacthold.core.plan`) |
| `ResourceRequirement` | core (unchanged: `pacthold.core.plan`) |

## `pacthold.core.protocols`

| symbol | now at |
| --- | --- |
| `ExecutionProvider` | core (unchanged: `pacthold.core.protocols`) |
| `ResourceProvider` | core (unchanged: `pacthold.core.protocols`) |

## `pacthold.core.registration`

| symbol | now at |
| --- | --- |
| `CoreContributionSet` | core (unchanged: `pacthold.core.registration`) |
| `CoreRegistration` | core (unchanged: `pacthold.core.registration`) |
| `CoreRegistry` | core (unchanged: `pacthold.core.registration`) |
| `CoreRegistrySnapshot` | core (unchanged: `pacthold.core.registration`) |

## `pacthold.core.runtime`

| symbol | now at |
| --- | --- |
| `CoreRuntime` | core (unchanged: `pacthold.core.runtime`) |
| `ShutdownReport` | core (unchanged: `pacthold.core.runtime`) |

## `pacthold.core.store`

| symbol | now at |
| --- | --- |
| `CoreStore` | core (unchanged: `pacthold.core.store`) |

## `pacthold.execution.contracts`

| symbol | now at |
| --- | --- |
| `CancelOutcome` | core (unchanged: `pacthold.execution.contracts`) |
| `DeadlinePolicy` | core (unchanged: `pacthold.execution.contracts`) |
| `DeliveryOutcome` | core (unchanged: `pacthold.execution.contracts`) |
| `EvidenceClass` | core (unchanged: `pacthold.execution.contracts`) |
| `ExecutionObservation` | core (unchanged: `pacthold.execution.contracts`) |
| `ExecutionReceipt` | core (unchanged: `pacthold.execution.contracts`) |
| `ExecutionRequest` | core (unchanged: `pacthold.execution.contracts`) |
| `NeutralBinding` | core (unchanged: `pacthold.execution.contracts`) |
| `ObservationState` | core (unchanged: `pacthold.execution.contracts`) |
| `TurnExecutionPort` | core (unchanged: `pacthold.execution.contracts`) |

## `pacthold.execution.first_run_lock`

| symbol | now at |
| --- | --- |
| `FIRST_RUN_WAIT_SECONDS` | core (unchanged: `pacthold.execution.first_run_lock`) |
| `FirstRunGate` | core (unchanged: `pacthold.execution.first_run_lock`) |
| `FirstRunLockTimeout` | core (unchanged: `pacthold.execution.first_run_lock`) |
| `first_run_gate` | core (unchanged: `pacthold.execution.first_run_lock`) |

## `pacthold.execution.lifecycle`

| symbol | now at |
| --- | --- |
| `NeutralRun` | core (unchanged: `pacthold.execution.lifecycle`) |
| `NeutralRunTracker` | core (unchanged: `pacthold.execution.lifecycle`) |

## `pacthold.extensions.api`

| symbol | now at |
| --- | --- |
| `AgentBoxPlugin` | compat: `pacthold_runtime_compat.api` |
| `ContinuationRoute` | compat: `pacthold_runtime_compat.api` |
| `ContinuationRouteDescriptor` | compat: `pacthold_runtime_compat.api` |
| `FinalizationContribution` | core (unchanged: `pacthold.extensions.api`) |
| `FinalizationContributor` | core (unchanged: `pacthold.extensions.api`) |
| `HarnessProfileManager` | compat: `pacthold_runtime_compat.api` |
| `HostControl` | core (unchanged: `pacthold.extensions.api`) |
| `HostControlUnavailable` | core (unchanged: `pacthold.extensions.api`) |
| `PLUGIN_API_VERSION` | core (unchanged: `pacthold.extensions.api`) |
| `PluginContext` | core (unchanged: `pacthold.extensions.api`) |
| `PluginDescriptor` | core (unchanged: `pacthold.extensions.api`) |
| `PluginRegistration` | core (unchanged: `pacthold.extensions.api`) |
| `ProfileEnvelope` | compat: `pacthold_runtime_compat.api` |
| `ProviderContinuationRoute` | compat: `pacthold_runtime_compat.api` |
| `ProviderHostControl` | compat: `pacthold_runtime_compat.api` |
| `RegistryBindable` | core (unchanged: `pacthold.extensions.api`) |
| `ResourceSelection` | core (unchanged: `pacthold.extensions.api`) |
| `ResourceSelector` | core (unchanged: `pacthold.extensions.api`) |
| `SelectorCompatibility` | core (unchanged: `pacthold.extensions.api`) |
| `SelectorField` | core (unchanged: `pacthold.extensions.api`) |

## `pacthold.extensions.bootstrap`

| symbol | now at |
| --- | --- |
| `ExtensionEnvironment` | core (unchanged: `pacthold.extensions.bootstrap`) |
| `build_extension_environment` | core (unchanged: `pacthold.extensions.bootstrap`) |
| `build_extension_environment_from_parts` | core (unchanged: `pacthold.extensions.bootstrap`) |
| `build_extension_registry` | core (unchanged: `pacthold.extensions.bootstrap`) |
| `register_shared_runtime_contracts` | compat: `pacthold_runtime_compat.bootstrap` |

## `pacthold.extensions.capability.documents`

| symbol | now at |
| --- | --- |
| `Condition` | compat: `pacthold_runtime_compat.capability.documents` |
| `EnvironmentFact` | compat: `pacthold_runtime_compat.capability.documents` |
| `EvidenceRef` | compat: `pacthold_runtime_compat.capability.documents` |
| `MatchContext` | compat: `pacthold_runtime_compat.capability.documents` |
| `RequirementParameterSet` | compat: `pacthold_runtime_compat.capability.documents` |
| `SandboxDeclaration` | compat: `pacthold_runtime_compat.capability.documents` |
| `SandboxDeclarationDocument` | compat: `pacthold_runtime_compat.capability.documents` |
| `SandboxGrant` | compat: `pacthold_runtime_compat.capability.documents` |
| `SandboxRequirement` | compat: `pacthold_runtime_compat.capability.documents` |
| `canonical_json` | compat: `pacthold_runtime_compat.capability.documents` |
| `requirement_set_digest` | compat: `pacthold_runtime_compat.capability.documents` |

## `pacthold.extensions.capability.errors`

| symbol | now at |
| --- | --- |
| `AuthorizationExceeded` | compat: `pacthold_runtime_compat.capability.errors` |
| `AuthorizationMissing` | compat: `pacthold_runtime_compat.capability.errors` |
| `CapabilityContractError` | compat: `pacthold_runtime_compat.capability.errors` |
| `CapabilityIdInvalid` | compat: `pacthold_runtime_compat.capability.errors` |
| `CapabilityUnknown` | compat: `pacthold_runtime_compat.capability.errors` |
| `DeclarationConflict` | compat: `pacthold_runtime_compat.capability.errors` |
| `EvidenceInvalid` | compat: `pacthold_runtime_compat.capability.errors` |
| `REFUSAL_AUTHORIZATION_EXCEEDED` | compat: `pacthold_runtime_compat.capability.errors` |
| `REFUSAL_AUTHORIZATION_MISSING` | compat: `pacthold_runtime_compat.capability.errors` |
| `REFUSAL_CONDITION_UNSATISFIED` | compat: `pacthold_runtime_compat.capability.errors` |
| `REFUSAL_DECLARATION_CONFLICT` | compat: `pacthold_runtime_compat.capability.errors` |
| `REFUSAL_DECLARATION_MISSING` | compat: `pacthold_runtime_compat.capability.errors` |
| `REFUSAL_ENVIRONMENT_MISMATCH` | compat: `pacthold_runtime_compat.capability.errors` |
| `REFUSAL_EVIDENCE_ABSENT` | compat: `pacthold_runtime_compat.capability.errors` |
| `REFUSAL_EVIDENCE_STALE` | compat: `pacthold_runtime_compat.capability.errors` |
| `REFUSAL_PARAMETER_NOT_COVERED` | compat: `pacthold_runtime_compat.capability.errors` |
| `REFUSAL_PIN_NOT_MATCHED` | compat: `pacthold_runtime_compat.capability.errors` |
| `REFUSAL_PROVIDER_NOT_AUTHORIZED` | compat: `pacthold_runtime_compat.capability.errors` |
| `REFUSAL_UNKNOWN_CAPABILITY` | compat: `pacthold_runtime_compat.capability.errors` |
| `RequirementConflict` | compat: `pacthold_runtime_compat.capability.errors` |

## `pacthold.extensions.capability.ids`

| symbol | now at |
| --- | --- |
| `require_capability_id` | compat: `pacthold_runtime_compat.capability.ids` |

## `pacthold.extensions.capability.match`

| symbol | now at |
| --- | --- |
| `CONDITION_FAILED` | compat: `pacthold_runtime_compat.capability.match` |
| `CONDITION_UNKNOWN` | compat: `pacthold_runtime_compat.capability.match` |
| `CONDITION_VERIFIED` | compat: `pacthold_runtime_compat.capability.match` |
| `MatchOutcome` | compat: `pacthold_runtime_compat.capability.match` |
| `MatchRule` | compat: `pacthold_runtime_compat.capability.match` |
| `MatchedItem` | compat: `pacthold_runtime_compat.capability.match` |
| `Refusal` | compat: `pacthold_runtime_compat.capability.match` |
| `match_requirements` | compat: `pacthold_runtime_compat.capability.match` |

## `pacthold.extensions.capability.requirements`

| symbol | now at |
| --- | --- |
| `sidecar_grants` | compat: `pacthold_runtime_compat.capability.requirements` |
| `sidecar_requirements` | compat: `pacthold_runtime_compat.capability.requirements` |

## `pacthold.extensions.capability.selection`

| symbol | now at |
| --- | --- |
| `REASON_INCUMBENT_NOT_MATCHED` | compat: `pacthold_runtime_compat.capability.selection` |
| `REASON_SUPERSEDED` | compat: `pacthold_runtime_compat.capability.selection` |
| `SelectionRecord` | compat: `pacthold_runtime_compat.capability.selection` |
| `select_declaration` | compat: `pacthold_runtime_compat.capability.selection` |

## `pacthold.extensions.capability.slots`

| symbol | now at |
| --- | --- |
| `slot_of_capability` | compat: `pacthold_runtime_compat.capability.slots` |

## `pacthold.extensions.catalog`

| symbol | now at |
| --- | --- |
| `CONTINUATION_ROUTE` | compat: `pacthold_runtime_compat.catalog` |
| `CONTRIBUTION_KINDS` | core (unchanged: `pacthold.extensions.catalog`) |
| `CREDENTIAL_MATERIALIZER` | compat: `pacthold_runtime_compat.catalog` |
| `CatalogBindable` | core (unchanged: `pacthold.extensions.catalog`) |
| `ExtensionCatalog` | core (unchanged: `pacthold.extensions.catalog`) |
| `ExtensionCatalogBuilder` | core (unchanged: `pacthold.extensions.catalog`) |
| `ExtensionContribution` | core (unchanged: `pacthold.extensions.catalog`) |
| `FINALIZATION_CONTRIBUTOR` | core (unchanged: `pacthold.extensions.catalog`) |
| `HARNESS_MANAGER` | compat: `pacthold_runtime_compat.catalog` |
| `HOST_CONTROL` | core (unchanged: `pacthold.extensions.catalog`) |
| `RESOURCE_SELECTOR` | core (unchanged: `pacthold.extensions.catalog`) |
| `TRANSPORT_OPERATION` | compat: `pacthold_runtime_compat.catalog` |
| `TransportOperationResolver` | compat: `pacthold_runtime_compat.catalog` |
| `activate_catalog_bindings` | core (unchanged: `pacthold.extensions.catalog`) |
| `activate_registry_bindings` | core (unchanged: `pacthold.extensions.catalog`) |
| `build_catalog_from_report` | core (unchanged: `pacthold.extensions.catalog`) |

## `pacthold.extensions.conformance`

| symbol | now at |
| --- | --- |
| `assert_plugin_conforms` | core (unchanged: `pacthold.extensions.conformance`) |
| `check_plugin_conformance` | core (unchanged: `pacthold.extensions.conformance`) |

## `pacthold.extensions.credentials`

| symbol | now at |
| --- | --- |
| `CONTRACT_ID` | compat: `pacthold_runtime_compat.credentials` / `pacthold_runtime_compat.runtime_composition.protocol` |
| `CredentialMaterializer` | compat: `pacthold_runtime_compat.credentials` |
| `PreparedSecretMount` | compat: `pacthold_runtime_compat.credentials` |
| `ResolvedCredential` | compat: `pacthold_runtime_compat.credentials` |

## `pacthold.extensions.diagnostics`

| symbol | now at |
| --- | --- |
| `DiagnosticSeverity` | core (unchanged: `pacthold.extensions.diagnostics`) |
| `PluginDiagnostic` | core (unchanged: `pacthold.extensions.diagnostics`) |
| `PluginDiagnosticReport` | core (unchanged: `pacthold.extensions.diagnostics`) |
| `check_registration_conformance` | core (unchanged: `pacthold.extensions.diagnostics`) |
| `diagnostic_json` | core (unchanged: `pacthold.extensions.diagnostics`) |

## `pacthold.extensions.finalization`

| symbol | now at |
| --- | --- |
| `HostFinalizationCoordinator` | core (unchanged: `pacthold.extensions.finalization`) |

## `pacthold.extensions.loader`

| symbol | now at |
| --- | --- |
| `ENTRY_POINT_GROUP` | core (unchanged: `pacthold.extensions.loader`) |
| `PluginCompatibilityError` | core (unchanged: `pacthold.extensions.loader`) |
| `PluginLoadRecord` | core (unchanged: `pacthold.extensions.loader`) |
| `PluginLoadReport` | core (unchanged: `pacthold.extensions.loader`) |
| `load_installed_plugins` | core (unchanged: `pacthold.extensions.loader`) |

## `pacthold.extensions.profile_envelope`

| symbol | now at |
| --- | --- |
| `ProfileEnvelopeManager` | compat: `pacthold_runtime_compat.profile_envelope` |
| `to_profile_envelope` | compat: `pacthold_runtime_compat.profile_envelope` |

## `pacthold.extensions.runtime_composition.assembler`

| symbol | now at |
| --- | --- |
| `assemble_runtime_composition` | compat: `pacthold_runtime_compat.runtime_composition.assembler` |

## `pacthold.extensions.runtime_composition.coordinator`

| symbol | now at |
| --- | --- |
| `ResolvedComposition` | compat: `pacthold_runtime_compat.runtime_composition.coordinator` |
| `RuntimeCompositionCoordinator` | compat: `pacthold_runtime_compat.runtime_composition.coordinator` |

## `pacthold.extensions.runtime_composition.fake`

| symbol | now at |
| --- | --- |
| `FakeCompositionCoordinator` | compat: `pacthold_runtime_compat.runtime_composition.fake` |
| `FakeHost` | compat: `pacthold_runtime_compat.runtime_composition.fake` |
| `FakeSandbox` | compat: `pacthold_runtime_compat.runtime_composition.fake` |
| `FakeTerminal` | compat: `pacthold_runtime_compat.runtime_composition.fake` |
| `TargetCreationSentinel` | compat: `pacthold_runtime_compat.runtime_composition.fake` |

## `pacthold.extensions.runtime_composition.protocol`

| symbol | now at |
| --- | --- |
| `AttachDescriptor` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `COMPENSATION_CAPABILITY` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `CONTRACT_ID` | compat: `pacthold_runtime_compat.credentials` / `pacthold_runtime_compat.runtime_composition.protocol` |
| `CapabilitySet` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `CapabilityStatus` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `CompositionAttemptRecord` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `CompositionCoordinator` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `CompositionError` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `CompositionErrorCode` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `CompositionPreflightReceipt` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `CompositionRejected` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `HarnessCommandSpec` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `HostTransport` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `HostTransportOperation` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `IsolatedProcessSpec` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `MountPlan` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `NativeCorrelationSet` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `PreparedMountSource` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `ProjectionRejected` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `RUNTIME_HOST_CONTRACT_ID` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `RuntimeBinding` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `RuntimeBundle` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `RuntimeHost` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `RuntimeHostProvider` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `RuntimeHostRef` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `RuntimeHostV1` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `RuntimeSourceDeclaration` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `SANDBOX_CONTRACT_ID` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `Sandbox` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `SandboxAmbiguous` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `SandboxError` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `SandboxProvider` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `SandboxRef` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `SandboxRequirements` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `SandboxUnavailable` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `SandboxUnsupported` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `SandboxV1` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `StartAmbiguous` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `TERMINAL_SESSION_CONTRACT_ID` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `TERMINATE_TRANSPORT_KIND` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `TerminalAllocation` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `TerminalRunHandle` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `TerminalSession` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `TerminalSessionProvider` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `TerminalSessionRef` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `TerminalSessionV1` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `TransportOperationContribution` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `TransportOperationDescriptor` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `TransportOperationHandler` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `attempt_key` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `content_digest` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `declare_source` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `digest` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `digest_json` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |
| `guest_path` | compat: `pacthold_runtime_compat.runtime_composition.protocol` |

## `pacthold.extensions.runtime_composition.sandbox_port`

| symbol | now at |
| --- | --- |
| `RoomInvariants` | compat: `pacthold_runtime_compat.runtime_composition.sandbox_port` |
| `RoomProcessSpec` | compat: `pacthold_runtime_compat.runtime_composition.sandbox_port` |
| `SANDBOX_PORT_FACTORY` | compat: `pacthold_runtime_compat.runtime_composition.sandbox_port` |
| `SANDBOX_PORT_MODULE_VARIABLE` | compat: `pacthold_runtime_compat.runtime_composition.sandbox_port` |
| `SandboxInvariantUnsupported` | compat: `pacthold_runtime_compat.runtime_composition.sandbox_port` |
| `SandboxPort` | compat: `pacthold_runtime_compat.runtime_composition.sandbox_port` |
| `SandboxPortError` | compat: `pacthold_runtime_compat.runtime_composition.sandbox_port` |
| `SandboxPortUnavailable` | compat: `pacthold_runtime_compat.runtime_composition.sandbox_port` |
| `SidecarRoomRequest` | compat: `pacthold_runtime_compat.runtime_composition.sandbox_port` |
| `register_sandbox_port_factory` | compat: `pacthold_runtime_compat.runtime_composition.sandbox_port` |
| `resolve_sandbox_port` | compat: `pacthold_runtime_compat.runtime_composition.sandbox_port` |

## `pacthold.resource_contracts`

| symbol | now at |
| --- | --- |
| `contract_type` | compat: `pacthold_runtime_compat.resource_contracts` |

## `pacthold.resource_contracts.agent_box_profile_v1`

| symbol | now at |
| --- | --- |
| `AgentBoxProfileV1` | compat: `pacthold_runtime_compat.resource_contracts.agent_box_profile_v1` |

## `pacthold.resource_contracts.agent_skill_v1`

| symbol | now at |
| --- | --- |
| `AgentSkillV1` | compat: `pacthold_runtime_compat.resource_contracts.agent_skill_v1` |

## `pacthold.resource_contracts.credential_v1`

| symbol | now at |
| --- | --- |
| `CredentialRefV1` | compat: `pacthold_runtime_compat.resource_contracts.credential_v1` |

## `pacthold.resource_contracts.harness_capabilities`

| symbol | now at |
| --- | --- |
| `CAPABILITY_CLAIMS_INVALID` | compat: `pacthold_runtime_compat.resource_contracts.harness_capabilities` |
| `CAPABILITY_CONFLICT_OBSERVED_WITHOUT_DECLARATION` | compat: `pacthold_runtime_compat.resource_contracts.harness_capabilities` |
| `CAPABILITY_NOT_DECLARED` | compat: `pacthold_runtime_compat.resource_contracts.harness_capabilities` |
| `CAPABILITY_NOT_OBSERVED` | compat: `pacthold_runtime_compat.resource_contracts.harness_capabilities` |
| `CAPABILITY_OBSERVED_UNSUPPORTED` | compat: `pacthold_runtime_compat.resource_contracts.harness_capabilities` |
| `CAPABILITY_SCHEMA_VERSION` | compat: `pacthold_runtime_compat.resource_contracts.harness_capabilities` |
| `CAPABILITY_UNKNOWN_ID` | compat: `pacthold_runtime_compat.resource_contracts.harness_capabilities` |
| `CAPABILITY_VALUE_NOT_BOOLEAN` | compat: `pacthold_runtime_compat.resource_contracts.harness_capabilities` |
| `CapabilityClaimsInvalid` | compat: `pacthold_runtime_compat.resource_contracts.harness_capabilities` |
| `CapabilityDeclaration` | compat: `pacthold_runtime_compat.resource_contracts.harness_capabilities` |
| `CapabilityDeclarationError` | compat: `pacthold_runtime_compat.resource_contracts.harness_capabilities` |
| `CapabilityUnknownId` | compat: `pacthold_runtime_compat.resource_contracts.harness_capabilities` |
| `CapabilityValueNotBoolean` | compat: `pacthold_runtime_compat.resource_contracts.harness_capabilities` |
| `IMPLEMENTATION_LEVEL_CAPABILITIES` | compat: `pacthold_runtime_compat.resource_contracts.harness_capabilities` |
| `SEMANTIC_CAPABILITIES` | compat: `pacthold_runtime_compat.resource_contracts.harness_capabilities` |
| `canonical_capabilities` | compat: `pacthold_runtime_compat.resource_contracts.harness_capabilities` |
| `capability_view` | compat: `pacthold_runtime_compat.resource_contracts.harness_capabilities` |
| `merge_capabilities` | compat: `pacthold_runtime_compat.resource_contracts.harness_capabilities` |
| `validate_claims` | compat: `pacthold_runtime_compat.resource_contracts.harness_capabilities` |

## `pacthold.resource_contracts.home_projection`

| symbol | now at |
| --- | --- |
| `GUEST_HOME` | compat: `pacthold_runtime_compat.resource_contracts.home_projection` |
| `HOME_TARGET_PREFIX` | compat: `pacthold_runtime_compat.resource_contracts.home_projection` |
| `HomeProjectionRejected` | compat: `pacthold_runtime_compat.resource_contracts.home_projection` |
| `MAX_TARGET_SEGMENTS` | compat: `pacthold_runtime_compat.resource_contracts.home_projection` |
| `MAX_TARGET_SEGMENT_LENGTH` | compat: `pacthold_runtime_compat.resource_contracts.home_projection` |
| `PROJECTION_DIRECTORY` | compat: `pacthold_runtime_compat.resource_contracts.home_projection` |
| `PROJECTION_FILE` | compat: `pacthold_runtime_compat.resource_contracts.home_projection` |
| `home_projection_target` | compat: `pacthold_runtime_compat.resource_contracts.home_projection` |
| `is_protected_state_path` | compat: `pacthold_runtime_compat.resource_contracts.home_projection` |
| `protected_state_paths` | compat: `pacthold_runtime_compat.resource_contracts.home_projection` |

## `pacthold.resource_contracts.prompt_fragment_v1`

| symbol | now at |
| --- | --- |
| `PromptFragmentV1` | compat: `pacthold_runtime_compat.resource_contracts.prompt_fragment_v1` |

## `pacthold.resource_contracts.runtime_artifacts`

| symbol | now at |
| --- | --- |
| `MAX_RUNTIME_ARTIFACT_BYTES` | compat: `pacthold_runtime_compat.resource_contracts.runtime_artifacts` |
| `MAX_RUNTIME_ARTIFACT_ENTRIES` | compat: `pacthold_runtime_compat.resource_contracts.runtime_artifacts` |
| `MAX_RUNTIME_ARTIFACT_PATH_BYTES` | compat: `pacthold_runtime_compat.resource_contracts.runtime_artifacts` |
| `MAX_RUNTIME_ARTIFACT_TREES` | compat: `pacthold_runtime_compat.resource_contracts.runtime_artifacts` |
| `RUNTIME_ARTIFACT_DOMAIN` | compat: `pacthold_runtime_compat.resource_contracts.runtime_artifacts` |
| `RUNTIME_ARTIFACT_NAME` | compat: `pacthold_runtime_compat.resource_contracts.runtime_artifacts` |
| `RUNTIME_ARTIFACT_TARGET` | compat: `pacthold_runtime_compat.resource_contracts.runtime_artifacts` |
| `RuntimeArtifactRejected` | compat: `pacthold_runtime_compat.resource_contracts.runtime_artifacts` |
| `runtime_artifact_name` | compat: `pacthold_runtime_compat.resource_contracts.runtime_artifacts` |
| `runtime_artifact_tree_digest` | compat: `pacthold_runtime_compat.resource_contracts.runtime_artifacts` |
| `runtime_artifact_tree_summary` | compat: `pacthold_runtime_compat.resource_contracts.runtime_artifacts` |
| `validate_runtime_artifact_target` | compat: `pacthold_runtime_compat.resource_contracts.runtime_artifacts` |

## `pacthold.resource_contracts.workspace_v1`

| symbol | now at |
| --- | --- |
| `WorkspaceV1` | compat: `pacthold_runtime_compat.resource_contracts.workspace_v1` |

## `pacthold.storage.database`

| symbol | now at |
| --- | --- |
| `Database` | compat: `pacthold_runtime_compat.storage.database` |
| `FutureSchemaError` | compat: `pacthold_runtime_compat.storage.database` |
| `PRODUCT_SCHEMA_VERSION` | compat: `pacthold_runtime_compat.storage.database` |

## `pacthold.storage.objects`

| symbol | now at |
| --- | --- |
| `ObjectRecord` | core (unchanged: `pacthold.storage.objects`) |
| `ObjectStore` | core (unchanged: `pacthold.storage.objects`) |

## `pacthold.storage.secrets`

| symbol | now at |
| --- | --- |
| `MAX_SECRET_BYTES` | core (unchanged: `pacthold.storage.secrets`) |
| `MemorySecretStore` | core (unchanged: `pacthold.storage.secrets`) |
| `SecretLocatorUnavailable` | core (unchanged: `pacthold.storage.secrets`) |
| `SecretStore` | core (unchanged: `pacthold.storage.secrets`) |
| `WindowsDpapiSecretStore` | core (unchanged: `pacthold.storage.secrets`) |

## `pacthold.work_core.db`

| symbol | now at |
| --- | --- |
| `configure_database` | core (unchanged: `pacthold.work_core.db`) |
| `get_conn` | core (unchanged: `pacthold.work_core.db`) |

## `pacthold.work_core.errors`

| symbol | now at |
| --- | --- |
| `CapabilityUnsupported` | core (unchanged: `pacthold.work_core.errors`) |
| `ContractViolation` | core (unchanged: `pacthold.work_core.errors`) |
| `DispatchAmbiguous` | core (unchanged: `pacthold.work_core.errors`) |
| `DispatchFailed` | core (unchanged: `pacthold.work_core.errors`) |
| `DispatchRejected` | core (unchanged: `pacthold.work_core.errors`) |
| `ExecutionStartIndeterminate` | core (unchanged: `pacthold.work_core.errors`) |
| `ExecutionStartRejected` | core (unchanged: `pacthold.work_core.errors`) |
| `FinalizationConflict` | core (unchanged: `pacthold.work_core.errors`) |
| `FinalizationRequired` | core (unchanged: `pacthold.work_core.errors`) |
| `InputFrozen` | core (unchanged: `pacthold.work_core.errors`) |
| `InvalidProjection` | core (unchanged: `pacthold.work_core.errors`) |
| `InvalidProjectionTransition` | core (unchanged: `pacthold.work_core.errors`) |
| `InvalidRef` | core (unchanged: `pacthold.work_core.errors`) |
| `InvalidResourceObservation` | core (unchanged: `pacthold.work_core.errors`) |
| `InvalidStartReceipt` | core (unchanged: `pacthold.work_core.errors`) |
| `ProviderUnavailable` | core (unchanged: `pacthold.work_core.errors`) |
| `WorkCoreError` | core (unchanged: `pacthold.work_core.errors`) |
| `WorkNotOpen` | core (unchanged: `pacthold.work_core.errors`) |

## `pacthold.work_core.events`

| symbol | now at |
| --- | --- |
| `CoreEvent` | core (unchanged: `pacthold.work_core.events`) |
| `EventType` | core (unchanged: `pacthold.work_core.events`) |
| `MAX_RESPONSIBILITY_INTENT_LENGTH` | core (unchanged: `pacthold.work_core.events`) |
| `RESPONSIBILITY_INTENT_KEY` | core (unchanged: `pacthold.work_core.events`) |
| `execution_created_event` | core (unchanged: `pacthold.work_core.events`) |
| `normalize_responsibility_intent` | core (unchanged: `pacthold.work_core.events`) |

## `pacthold.work_core.finalization`

| symbol | now at |
| --- | --- |
| `ExecutionFinalizationRequest` | core (unchanged: `pacthold.work_core.finalization`) |
| `FinalizationReceipt` | core (unchanged: `pacthold.work_core.finalization`) |

## `pacthold.work_core.models`

| symbol | now at |
| --- | --- |
| `Execution` | core (unchanged: `pacthold.work_core.models`) |
| `MAX_METADATA_ITEMS` | core (unchanged: `pacthold.work_core.models`) |
| `MAX_METADATA_KEY_LENGTH` | core (unchanged: `pacthold.work_core.models`) |
| `MAX_METADATA_VALUE_LENGTH` | core (unchanged: `pacthold.work_core.models`) |
| `Ref` | core (unchanged: `pacthold.work_core.models`) |
| `RefType` | core (unchanged: `pacthold.work_core.models`) |
| `Work` | core (unchanged: `pacthold.work_core.models`) |
| `WorkLifecycle` | core (unchanged: `pacthold.work_core.models`) |

## `pacthold.work_core.projection`

| symbol | now at |
| --- | --- |
| `ExecutionProjection` | core (unchanged: `pacthold.work_core.projection`) |
| `Freshness` | core (unchanged: `pacthold.work_core.projection`) |
| `Outcome` | core (unchanged: `pacthold.work_core.projection`) |
| `Phase` | core (unchanged: `pacthold.work_core.projection`) |

## `pacthold.work_core.registry`

| symbol | now at |
| --- | --- |
| `DispatchReceipt` | core (unchanged: `pacthold.work_core.registry`) |
| `ExecutionPreflightRequest` | core (unchanged: `pacthold.work_core.registry`) |
| `ExecutionProvider` | core (unchanged: `pacthold.work_core.registry`) |
| `ExecutionStartReceipt` | core (unchanged: `pacthold.work_core.registry`) |
| `ExecutionStartRequest` | core (unchanged: `pacthold.work_core.registry`) |
| `ExtensionRegistry` | core (unchanged: `pacthold.work_core.registry`) |
| `ProviderDescriptor` | core (unchanged: `pacthold.work_core.registry`) |
| `RecoverySupport` | core (unchanged: `pacthold.work_core.registry`) |
| `ResolutionEffect` | core (unchanged: `pacthold.work_core.registry`) |
| `ResolvedExecutionInput` | core (unchanged: `pacthold.work_core.registry`) |
| `ResourceProvider` | core (unchanged: `pacthold.work_core.registry`) |
| `ResourceResolutionContext` | core (unchanged: `pacthold.work_core.registry`) |

## `pacthold.work_core.repository`

| symbol | now at |
| --- | --- |
| `ConcurrencyConflict` | core (unchanged: `pacthold.work_core.repository`) |
| `CoreRepository` | core (unchanged: `pacthold.work_core.repository`) |
| `ExecutionNotFound` | core (unchanged: `pacthold.work_core.repository`) |
| `RefRelation` | core (unchanged: `pacthold.work_core.repository`) |
| `WorkNotFound` | core (unchanged: `pacthold.work_core.repository`) |

## `pacthold.work_core.resource_observations`

| symbol | now at |
| --- | --- |
| `MAX_DETAIL_LENGTH` | core (unchanged: `pacthold.work_core.resource_observations`) |
| `MAX_OBSERVER_ID_LENGTH` | core (unchanged: `pacthold.work_core.resource_observations`) |
| `ResourceObservation` | core (unchanged: `pacthold.work_core.resource_observations`) |
| `ResourceObservationCoverage` | core (unchanged: `pacthold.work_core.resource_observations`) |
| `ResourceObservationKind` | core (unchanged: `pacthold.work_core.resource_observations`) |
| `ResourceObservationResult` | core (unchanged: `pacthold.work_core.resource_observations`) |
| `ResourceObserverRole` | core (unchanged: `pacthold.work_core.resource_observations`) |

## `pacthold.work_core.runtime`

| symbol | now at |
| --- | --- |
| `AGENT_BOX_HOME_ENV` | core (unchanged: `pacthold.work_core.runtime`) |
| `DISPLAY_NAME` | core (unchanged: `pacthold.work_core.runtime`) |
| `agent_box_home` | core (unchanged: `pacthold.work_core.runtime`) |
| `database_path` | core (unchanged: `pacthold.work_core.runtime`) |
| `migrations_dir` | core (unchanged: `pacthold.work_core.runtime`) |

## `pacthold.work_core.services`

| symbol | now at |
| --- | --- |
| `ExecutionService` | core (unchanged: `pacthold.work_core.services`) |
| `WorkService` | core (unchanged: `pacthold.work_core.services`) |

## Counts

core(unchanged)=209  core(moved)=0  compat=192  removed=0

## Non-symbol moves (paths B must re-target)

| old path | now |
| --- | --- |
| `pacthold.migrations/001_init.sql` … `009_execution_finalization.sql` | `pacthold_runtime_compat/migrations/` (byte-sealed, names/numbering unchanged; register via `pacthold_runtime_compat.legacy_migrations.register_legacy_migrations()` before the first Core connection) |
| `pacthold.migrations/` (kernel dir) | keeps only the new neutral `001_core_schema.sql` recorded in its own table `core_schema_versions` (CREATE-IF-NOT-EXISTS end state; independent of the old `schema_versions`) |
| `pacthold.cli` `web`/`launch` subcommands, Web-aware `doctor`, launcher `main` | `pacthold_runtime_compat.cli` (kernel CLI keeps neutral `plugins`/`doctor`; the `pacthold` console-script entry still resolves to `pacthold.cli:main`) |
| `pacthold.work_core.registry.ExtensionRegistry()` implicit `CONTRACT_TYPES` seed | bare kernel registry starts EMPTY; seed via `ExtensionRegistry(seed_contracts=…)`; product: `pacthold_runtime_compat.bootstrap.build_product_registry()` |
| `pacthold.extensions.catalog` business kinds (`harness_manager`, `continuation_route`, `credential_materializer`, `transport_operation`), `TRANSPORT_OPERATION`, `TransportOperationResolver`, business query methods | `pacthold_runtime_compat.catalog` (`PRODUCT_CONTRIBUTION_KINDS/SPECS`, `ProductExtensionCatalog(Builder)`, `TransportOperationResolver`); kernel keeps the neutral `ContributionKindSpec` mechanism, `CORE_CONTRIBUTION_KINDS/SPECS` |
| `pacthold.extensions.bootstrap.SHARED_RUNTIME_CONTRACTS` / `register_shared_runtime_contracts` / product defaults in `build_extension_environment` | `pacthold_runtime_compat.bootstrap` (same names + `build_product_environment*`; kernel builder now takes optional `registry=`/`catalog_builder=`) |
| `pacthold.extensions.api` business SDK (`AgentBoxPlugin`, `ProfileEnvelope`, `HarnessProfileManager`, `ProviderHostControl`, `ContinuationRoute(D descriptor)`, `ProviderContinuationRoute`, business slots on `PluginRegistration`) | `pacthold_runtime_compat.api` (product `PluginRegistration` subclasses the kernel one; kernel `PluginRegistration` keeps only the 6 neutral tuple slots) |
| `pacthold.extensions.credentials` (`CredentialMaterializer`, `PreparedSecretMount`, `ResolvedCredential`, `CONTRACT_ID`) | `pacthold_runtime_compat.credentials` |
| `pacthold.extensions.profile_envelope` (`ProfileEnvelopeManager`, `to_profile_envelope`) | `pacthold_runtime_compat.profile_envelope` |
| `pacthold.extensions.capability.*` | `pacthold_runtime_compat.capability.*` (same submodule names) |
| `pacthold.extensions.runtime_composition.*` | `pacthold_runtime_compat.runtime_composition.*` (same submodule names) |
| `pacthold.extensions.sandbox` (re-export shim) | `pacthold_runtime_compat.sandbox` (frozen; must not grow) |
| `pacthold.resource_contracts.*` (package, `CONTRACT_TYPES`, all `*_v1` modules, `harness_capabilities`, `home_projection`, `runtime_artifacts`) | `pacthold_runtime_compat.resource_contracts.*` (same submodule names, `agent-box.*` ids verbatim) |
| `pacthold.storage` facade exports `Database`, `FutureSchemaError` (and `pacthold.storage.database` module, `PRODUCT_SCHEMA_VERSION=21`, `_migrate_*` chain) | `pacthold_runtime_compat.storage` / `.storage.database`; kernel `pacthold.storage` keeps only `ObjectStore/ObjectRecord/MemorySecretStore/SecretStore/WindowsDpapiSecretStore` |
| `pacthold.work_core.db` global runner | unchanged public API (`get_conn/configure_database`) but now runs registered namespaces (assembly first, core last); `register_migration_source/registered_migration_sources/MigrationSource` are the new injection seam |

