"""Read generated document captures for one exact, committed package.

This adapter is an explicitly selected SourceMaterialPort. It does not resolve
the SourceRef locator to an external file: the original source identity remains
on the package, while these exact captured bytes are retained in the Library's
content-addressed blob authority.
"""
from __future__ import annotations

import hashlib

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.domain.artifacts.provenance import SourceRef, VersionCapture
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef


class PackageDocumentMaterials:
    """Expose only documents in one committed package as exact source material."""

    def __init__(self, factory, blobs, *, scope: Scope,
                 package_ref: ImplementationPackageRef):
        library = getattr(factory, "library", None)
        authority_id = getattr(factory, "authority_id", None)
        if (factory is None or blobs is None or type(scope) is not Scope
                or type(package_ref) is not ImplementationPackageRef
                or library is None or getattr(blobs, "library", None) is not library
                or type(authority_id) is not str or not authority_id
                or getattr(blobs, "authority_id", None) != authority_id
                or package_ref.realm_id != scope.realm_id
                or package_ref.project_id != scope.project_id):
            raise ApplicationError("SOURCE_UNAVAILABLE")
        self.factory = factory
        self.blobs = blobs
        self.scope = scope
        self.package_ref = package_ref

    def read(self, context: CommandContext, ref: SourceRef) -> bytes:
        if (type(context) is not CommandContext or context.scope != self.scope
                or type(ref) is not SourceRef or type(ref.capture) is not VersionCapture):
            raise ApplicationError("SOURCE_UNAVAILABLE")
        try:
            with self.factory.begin(context.scope, "read") as uow:
                try:
                    package = uow.implementation.resolve_package(self.package_ref)
                except ApplicationError as error:
                    if error.code == "NOT_FOUND":
                        raise ApplicationError("SOURCE_UNAVAILABLE") from error
                    raise
            if package.scope != self.scope:
                raise ApplicationError("SOURCE_UNAVAILABLE")
            documents = tuple(item.source_ref for item in package.payload.documents)
            if ref not in documents:
                same_source = any(item.source_id == ref.source_id and item.locator == ref.locator
                                  for item in documents)
                raise ApplicationError("SOURCE_VERSION_MISMATCH" if same_source
                                       else "SOURCE_UNAVAILABLE")
            digest = ref.capture.content_digest
            if digest.algorithm != "sha256":
                raise ApplicationError("SOURCE_CONTENT_MISMATCH")
            from .blob_bytes import object_id as blob_object_id
            blob_ref = BlobRef(digest, ref.byte_length, ref.media_type,
                               blob_object_id(self.blobs.authority_id, digest.hex))
            raw = self.blobs.read_verified(blob_ref)
            if (len(raw) != ref.byte_length
                    or hashlib.sha256(raw).hexdigest() != digest.hex):
                raise ApplicationError("SOURCE_CONTENT_MISMATCH")
            return raw
        except ApplicationError:
            raise
        except Exception as error:
            raise ApplicationError("SOURCE_UNAVAILABLE") from error


__all__ = ["PackageDocumentMaterials"]
