"""Harness-only registration and discovery mechanisms."""

from .definition_admission import (HARNESS_DEFINITION_VERSION, HarnessDefinitionDescriptor,
    HarnessInstallationObservation, HarnessDefinitionDeclaration,
    AdmittedHarnessDefinition, HarnessAdmission, HarnessCatalog, harness_registration_snapshot)
from .registration import HarnessRegistration
from .errors import CatalogAdmissionRefused, CatalogIdentityConflict, CatalogUnavailable

__all__ = ['HARNESS_DEFINITION_VERSION', 'HarnessDefinitionDescriptor',
    'HarnessInstallationObservation', 'HarnessDefinitionDeclaration',
    'AdmittedHarnessDefinition', 'HarnessAdmission', 'HarnessCatalog', 'HarnessRegistration',
    'harness_registration_snapshot', 'CatalogAdmissionRefused', 'CatalogIdentityConflict',
    'CatalogUnavailable']
