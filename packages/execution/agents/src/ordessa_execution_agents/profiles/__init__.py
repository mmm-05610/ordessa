"""Explicit Profile public contract; importing creates no services, stores or IO.

Cross-distribution clients import this package. Internal implementation modules
may use their owned modules directly. The Agent aggregate consumes this same
contract; it does not define another Profile service or state authority.
"""
from .definitions.models import Profile, ProfileRevisionRef, ProfileRevision, ProfileContent, ConfigurationDeclaration
from .definitions.validation import ProfileNotFound, ProfileRevisionConflict, ProfileValidationError
from .definitions.codec import decode_revision_ref, encode_revision_ref, decode_profile, encode_profile, decode_content, encode_content, decode_revision, encode_revision, canonical_content, content_digest
from .management.service import ProfileService
from .management.ports import ProfileStorePort

__all__ = [
    "Profile", "ProfileRevisionRef", "ProfileRevision", "ProfileContent", "ConfigurationDeclaration",
    "ProfileNotFound", "ProfileRevisionConflict", "ProfileValidationError",
    "ProfileService", "ProfileStorePort",
    "decode_content", "encode_content",
    "decode_revision_ref", "encode_revision_ref", "decode_profile", "encode_profile",
    "decode_revision", "encode_revision", "canonical_content", "content_digest",
]
