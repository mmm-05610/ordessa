"""Safe filesystem implementation of the method resource reader port."""
from __future__ import annotations

from pathlib import Path

from ...methods.definitions.models import MethodSource


class FileResourceReader:
    """Bounded descriptor-relative reader; rejects links and non-regular files."""

    def read(self, source: MethodSource, relative_path: str, max_bytes: int) -> bytes:
        import errno
        import os
        import stat

        from ...methods.validation.references import validate_logical_path
        from ...methods.definitions.errors import MethodFailure, MethodError

        logical = validate_logical_path(relative_path)
        root = Path(source.root).resolve(strict=True)
        if not root.is_dir():
            raise MethodFailure(MethodError("RESOURCE_ROOT_INVALID", "method root is not a directory"))
        nofollow = getattr(os, "O_NOFOLLOW", None)
        directory = getattr(os, "O_DIRECTORY", None)
        nonblocking = getattr(os, "O_NONBLOCK", None)
        if nofollow is None or directory is None or nonblocking is None:
            raise MethodFailure(MethodError("SAFE_OPEN_UNAVAILABLE", "platform cannot safely open method resources", path=logical))

        fd = os.open(root, os.O_RDONLY | directory | nofollow)
        try:
            parts = logical.split("/")
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | directory | nofollow, dir_fd=fd)
                os.close(fd)
                fd = child
            # Reject special files before opening them, then keep O_NONBLOCK on
            # the final open to close the stat/open race for FIFOs.
            candidate = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISREG(candidate.st_mode) or candidate.st_nlink != 1:
                raise MethodFailure(MethodError("RESOURCE_NOT_PRIVATE_FILE", "resource must be a regular non-hardlinked file", path=logical))
            file_fd = os.open(parts[-1], os.O_RDONLY | nofollow | nonblocking, dir_fd=fd)
        except OSError as exc:
            code = "RESOURCE_NOT_FOUND" if exc.errno == errno.ENOENT else "RESOURCE_READ_FAILED"
            raise MethodFailure(MethodError(code, "resource could not be opened safely", path=logical)) from exc
        finally:
            os.close(fd)
        try:
            metadata = os.fstat(file_fd)
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                    or metadata.st_dev != candidate.st_dev or metadata.st_ino != candidate.st_ino):
                raise MethodFailure(MethodError("RESOURCE_NOT_PRIVATE_FILE", "resource must be a regular non-hardlinked file", path=logical))
            if metadata.st_size > max_bytes:
                raise MethodFailure(MethodError("RESOURCE_TOO_LARGE", "resource exceeds its byte limit", path=logical))
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(file_fd, min(65536, max_bytes + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > max_bytes:
                    raise MethodFailure(MethodError("RESOURCE_TOO_LARGE", "resource exceeds its byte limit", path=logical))
            return b"".join(chunks)
        except OSError as exc:
            raise MethodFailure(MethodError("RESOURCE_READ_FAILED", "resource could not be read", path=logical)) from exc
        finally:
            os.close(file_fd)
