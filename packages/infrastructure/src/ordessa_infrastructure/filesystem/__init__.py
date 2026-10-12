"""Business-neutral filesystem mechanisms.

Public entries:

* :mod:`ordessa_infrastructure.filesystem.directories` — dirfd traversal
  relative to a trusted descriptor, and identity-checked no-follow opens.
* :mod:`ordessa_infrastructure.filesystem.files` — restricted file opens,
  exclusive creation and directory sync.
* :mod:`ordessa_infrastructure.filesystem.publication` — staged single-file
  publication with explicit durability accounting.
* :mod:`ordessa_infrastructure.filesystem.errors` — neutral error types.

Importing this package performs no IO. The mechanisms own no business path,
mode policy, cleanup authority or commit protocol; callers pass explicit
permissions and keep their own validation and completion semantics.
"""
from .directories import (
    is_safe_component,
    open_directory_absolute,
    open_directory_nofollow,
    open_directory_relative,
)
from .errors import (
    DirectoryReplacedError,
    FileAlreadyExistsError,
    FilesystemMechanismError,
    PlatformUnsupportedError,
    PublicationError,
    UnsafeFileTypeError,
    UnsafePathError,
)
from .files import (
    create_exclusive_at,
    open_file_at,
    open_regular_at,
    read_regular_at,
    sync_directory,
)
from .publication import PublicationStage, PublishedFile, publish_file

__all__ = [
    "is_safe_component",
    "open_directory_absolute",
    "open_directory_nofollow",
    "open_directory_relative",
    "create_exclusive_at",
    "open_file_at",
    "open_regular_at",
    "read_regular_at",
    "sync_directory",
    "PublicationStage",
    "PublishedFile",
    "publish_file",
    "DirectoryReplacedError",
    "FileAlreadyExistsError",
    "FilesystemMechanismError",
    "PlatformUnsupportedError",
    "PublicationError",
    "UnsafeFileTypeError",
    "UnsafePathError",
]
