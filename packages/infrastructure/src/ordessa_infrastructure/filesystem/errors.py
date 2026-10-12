"""Neutral filesystem mechanism errors.

These are intentionally free of any business error code. Owners that need their
own vocabulary (for example Engineering's ``package_directory_unsafe``) catch
these and re-raise their own errors, so the mechanism never leaks a product
contract and never invents a second authority over the caller's policy.
"""
from __future__ import annotations


class FilesystemMechanismError(Exception):
    """Base class for every error raised by this package."""


class UnsafePathError(FilesystemMechanismError):
    """A path component was absolute, empty, ``.``/``..`` or separator-bearing."""


class UnsafeFileTypeError(FilesystemMechanismError):
    """An object was a symlink, or not the directory/regular file required."""


class DirectoryReplacedError(FilesystemMechanismError):
    """A directory's identity changed between check and open."""


class PlatformUnsupportedError(FilesystemMechanismError):
    """The platform lacks the required guarantee (``O_NOFOLLOW``/``O_DIRECTORY``).

    Raised instead of silently reading/creating a symlink-followable object.
    A caller may catch this and refuse, but the mechanism never falls back to
    ``O_NOFOLLOW = 0`` and pretends the guarantee held.
    """


class FileAlreadyExistsError(FilesystemMechanismError):
    """Exclusive creation found an existing name (``O_EXCL``)."""


class PublicationError(FilesystemMechanismError):
    """A staged single-file publication failed.

    ``stage`` names the stage that failed and ``target_may_have_changed`` is
    true when the atomic replace had already completed, so the caller must not
    assume the previous target content is intact. This mechanism never rolls
    back and never deletes the final target on the caller's behalf.
    """

    def __init__(self, stage: str, message: str, *, target_may_have_changed: bool = False) -> None:
        super().__init__(message)
        self.stage = stage
        self.target_may_have_changed = target_may_have_changed
