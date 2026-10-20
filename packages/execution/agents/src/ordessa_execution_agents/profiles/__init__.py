"""Explicit Profile public contract; importing creates no services, stores or IO.

Cross-distribution clients import this package. Internal implementation modules
may use their owned modules directly. The Agent aggregate consumes this same
contract; it does not define another Profile service or state authority.
"""
from .definitions.models import Profile, ProfileRevisionRef, ProfileRevision, ProfileContent, ConfigurationDeclaration
from .definitions.errors import (HistoricalProfileIdentityMismatch,
                                 ProfileAccessRefused, ProfileChangeUnknown,
                                 ProfileRevisionConflict, ProfileStoreUnavailable,
                                 ProfileValidationError)
from .definitions.validation import ProfileNotFound
from .definitions.codec import decode_revision_ref, encode_revision_ref, decode_profile, encode_profile, decode_content, encode_content, decode_revision, encode_revision, canonical_content, content_digest
from .definitions.historical_projection import AgentBoxProfileV1, HistoricalProfileViewPort
from .management.historical_projection import exact_historical_envelope
from .management.service import ProfileService
from .management.ports import ProfileStorePort, ProfileAdmissionPort, ProfileValidatorPort
from .management.record_store import RecordProfileStore
from .management.sqlite_store import SqliteProfileStore

__all__ = [
    "Profile", "ProfileRevisionRef", "ProfileRevision", "ProfileContent", "ConfigurationDeclaration",
    "HistoricalProfileIdentityMismatch",
    "ProfileNotFound", "ProfileRevisionConflict", "ProfileValidationError",
    "ProfileAccessRefused", "ProfileStoreUnavailable", "ProfileChangeUnknown",
    "ProfileService", "ProfileStorePort", "ProfileAdmissionPort", "ProfileValidatorPort",
    "RecordProfileStore", "SqliteProfileStore",
    "AgentBoxProfileV1", "HistoricalProfileViewPort", "exact_historical_envelope",
    "decode_content", "encode_content",
    "decode_revision_ref", "encode_revision_ref", "decode_profile", "encode_profile",
    "decode_revision", "encode_revision", "canonical_content", "content_digest",
]
