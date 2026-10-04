"""Workspace-owned directory binding contract; no plugin activation required.

Deployment must inject existing records and trusted authority/realm capabilities.
This public face does not certify production host contribution admission.
"""
from .directory_binding import (
    DirectoryAuthorityPort, DirectoryBindingEvidence, DirectoryBindingService,
    DirectoryGrant, LocalDirectoryRealm, ProjectRef,
)

__all__ = ["DirectoryAuthorityPort", "DirectoryBindingEvidence", "DirectoryBindingService",
           "DirectoryGrant", "LocalDirectoryRealm", "ProjectRef"]
