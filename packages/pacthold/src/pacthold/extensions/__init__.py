"""Public extension API and entry-point loader for third-party integrations.

specs/010 T009: this namespace exposes only the kernel-neutral plugin
mechanism.  Business SDK surfaces (profile envelopes, credentials,
capability documents, runtime composition, sandbox shims and the product
catalog/bootstrap pieces) live in the compatibility assembly,
``pacthold_runtime_compat``, which may import the kernel but is never
imported by it.
"""

from .api import (
    PLUGIN_API_VERSION,
    PluginContext,
    PluginDescriptor,
    PluginRegistration,
    FinalizationContribution,
    FinalizationContributor,
    HostControl,
    RegistryBindable,
    ResourceSelection,
    ResourceSelector,
    SelectorCompatibility,
    SelectorField,
)
from .catalog import (
    CONTRIBUTION_KINDS,
    CORE_CONTRIBUTION_KINDS,
    CORE_CONTRIBUTION_SPECS,
    CatalogBindable,
    ContributionKindSpec,
    ExtensionCatalog,
    ExtensionCatalogBuilder,
    ExtensionContribution,
    ValidationContext,
    activate_catalog_bindings,
    activate_registry_bindings,
    build_catalog_from_report,
)
from .bootstrap import (
    ExtensionEnvironment,
    build_extension_environment,
    build_extension_environment_from_parts,
    build_extension_registry,
)
from .loader import (
    ENTRY_POINT_GROUP,
    PluginLoadRecord,
    PluginLoadReport,
    PluginCompatibilityError,
    load_installed_plugins,
)
from .diagnostics import (
    DiagnosticSeverity,
    PluginDiagnostic,
    PluginDiagnosticReport,
    check_registration_conformance,
)
from .conformance import assert_plugin_conforms, check_plugin_conformance

__all__ = [
    "ENTRY_POINT_GROUP",
    "PLUGIN_API_VERSION",
    "PluginContext",
    "PluginDescriptor",
    "PluginLoadRecord",
    "PluginLoadReport",
    "PluginCompatibilityError",
    "PluginRegistration",
    "FinalizationContribution",
    "FinalizationContributor",
    "HostControl",
    "RegistryBindable",
    "CatalogBindable",
    "ResourceSelection",
    "ResourceSelector",
    "SelectorField",
    "SelectorCompatibility",
    "CONTRIBUTION_KINDS",
    "CORE_CONTRIBUTION_KINDS",
    "CORE_CONTRIBUTION_SPECS",
    "ContributionKindSpec",
    "ValidationContext",
    "ExtensionCatalog",
    "ExtensionCatalogBuilder",
    "ExtensionContribution",
    "ExtensionEnvironment",
    "activate_catalog_bindings",
    "activate_registry_bindings",
    "build_catalog_from_report",
    "build_extension_environment",
    "build_extension_environment_from_parts",
    "build_extension_registry",
    "load_installed_plugins",
    "DiagnosticSeverity",
    "PluginDiagnostic",
    "PluginDiagnosticReport",
    "check_registration_conformance",
    "assert_plugin_conforms",
    "check_plugin_conformance",
    "HostFinalizationCoordinator",
]
