import os
import stat
import subprocess
import sys

import pytest

from ordessa_infrastructure.filesystem import (
    DirectoryReplacedError,
    FileAlreadyExistsError,
    PlatformUnsupportedError,
    UnsafeFileTypeError,
    UnsafePathError,
    create_exclusive_at,
    is_safe_component,
    open_directory_absolute,
    open_directory_nofollow,
    open_directory_relative,
    open_file_at,
    open_regular_at,
    read_regular_at,
)


def _open_root(tmp_path):
    return open_directory_nofollow(tmp_path)


def test_safe_component_rules():
    for bad in ("", ".", "..", "a/b", "/abs", r"a\\b"):
        assert not is_safe_component(bad), bad
    for good in ("a", "a.b", "names-1"):
        assert is_safe_component(good), good


def test_open_directory_relative_rejects_traversal_and_absolute(tmp_path):
    root = _open_root(tmp_path)
    try:
        with pytest.raises(UnsafePathError):
            open_directory_relative(root, "..")
        with pytest.raises(UnsafePathError):
            open_directory_relative(root, "/etc")
        with pytest.raises(UnsafePathError):
            open_directory_relative(root, "a/b")
    finally:
        os.close(root)


def test_open_directory_nofollow_refuses_symlink(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(UnsafeFileTypeError):
        open_directory_nofollow(link)
    regular = tmp_path / "regular.txt"
    regular.write_text("x")
    with pytest.raises(UnsafeFileTypeError):
        open_directory_nofollow(regular)


def test_open_directory_absolute_walks_and_rejects_parent(tmp_path):
    child = tmp_path / "child"
    child.mkdir()
    fd = open_directory_absolute(child)
    try:
        assert stat.S_ISDIR(os.fstat(fd).st_mode)
    finally:
        os.close(fd)
    # ``Path.absolute()`` keeps ``..``; it must be refused, not normalised away.
    with pytest.raises(UnsafePathError):
        open_directory_absolute(tmp_path / "child" / ".." / "child")


def test_open_directory_nofollow_detects_replaced_identity(tmp_path, monkeypatch):
    target = tmp_path / "dir"
    target.mkdir()
    import ordessa_infrastructure.filesystem.directories as directories

    real_fstat = os.fstat

    def swapped_fstat(fd):
        info = real_fstat(fd)
        values = list(info)
        values[1] = info.st_ino + 1  # st_ino
        return os.stat_result(values)

    monkeypatch.setattr(directories.os, "fstat", swapped_fstat)
    with pytest.raises(DirectoryReplacedError):
        open_directory_nofollow(target)


def test_create_exclusive_mode_and_collision(tmp_path):
    root = _open_root(tmp_path)
    try:
        fd = create_exclusive_at(root, "out.bin", mode=0o640)
        os.write(fd, b"payload")
        os.close(fd)
        info = os.stat(tmp_path / "out.bin")
        assert stat.S_IMODE(info.st_mode) == 0o640
        assert (tmp_path / "out.bin").read_bytes() == b"payload"
        with pytest.raises(FileAlreadyExistsError):
            create_exclusive_at(root, "out.bin", mode=0o600)
    finally:
        os.close(root)


def test_read_regular_at_and_limit(tmp_path):
    root = _open_root(tmp_path)
    try:
        (tmp_path / "data.txt").write_bytes(b"hello")
        assert read_regular_at(root, "data.txt") == b"hello"
        assert read_regular_at(root, "data.txt", limit=5) == b"hello"
        with pytest.raises(UnsafeFileTypeError):
            read_regular_at(root, "data.txt", limit=4)
        # A symlink is refused, never followed.
        (tmp_path / "target.txt").write_bytes(b"secret")
        (tmp_path / "link.txt").symlink_to(tmp_path / "target.txt")
        with pytest.raises(UnsafeFileTypeError):
            open_regular_at(root, "link.txt")
    finally:
        os.close(root)


def test_borrowed_directory_fd_is_not_closed(tmp_path):
    root = _open_root(tmp_path)
    (tmp_path / "f.txt").write_bytes(b"x")
    try:
        assert read_regular_at(root, "f.txt") == b"x"
        # still open: fstat on the borrowed fd must succeed
        assert stat.S_ISDIR(os.fstat(root).st_mode)
    finally:
        os.close(root)


def test_explicit_file_mode_is_required_and_applied(tmp_path):
    root = _open_root(tmp_path)
    try:
        fd = create_exclusive_at(root, "private.bin", mode=0o600)
        os.close(fd)
        assert stat.S_IMODE((tmp_path / "private.bin").stat().st_mode) == 0o600
    finally:
        os.close(root)


def test_platform_without_nofollow_refuses(tmp_path, monkeypatch):
    root = _open_root(tmp_path)
    try:
        monkeypatch.delattr(os, "O_NOFOLLOW")
        with pytest.raises(PlatformUnsupportedError):
            open_directory_relative(root, "child")
        with pytest.raises(PlatformUnsupportedError):
            open_file_at(root, "f", os.O_RDONLY)
        with pytest.raises(PlatformUnsupportedError):
            create_exclusive_at(root, "g", mode=0o600)
    finally:
        os.close(root)


def test_open_file_at_adds_nofollow_and_checks_regular(tmp_path):
    root = _open_root(tmp_path)
    try:
        fd = create_exclusive_at(root, "regular", mode=0o600)
        os.close(fd)
        read = open_file_at(root, "regular", os.O_RDONLY, mode=0)
        try:
            assert stat.S_ISREG(os.fstat(read).st_mode)
        finally:
            os.close(read)
        (tmp_path / "d").mkdir()
        with pytest.raises(UnsafeFileTypeError):
            open_file_at(root, "d", os.O_RDONLY, mode=0)
    finally:
        os.close(root)


def test_components_reject_nul(tmp_path):
    for bad in ("a\x00b", "\x00", "x\x00"):
        assert not is_safe_component(bad), repr(bad)
    root = _open_root(tmp_path)
    try:
        with pytest.raises(UnsafePathError):
            open_regular_at(root, "a\x00b")
        with pytest.raises(UnsafePathError):
            create_exclusive_at(root, "a\x00b", mode=0o600)
    finally:
        os.close(root)


def test_read_regular_at_enforces_limit_on_growing_file(tmp_path, monkeypatch):
    """The opened size may be small while the file grows before it is read.

    Under-reporting ``st_size`` on the pre-check must not let the accumulated
    read exceed the limit.
    """
    import ordessa_infrastructure.filesystem.files as files_module

    root = _open_root(tmp_path)
    try:
        (tmp_path / "ten").write_bytes(b"0123456789")
        real_fstat = os.fstat

        def small_fstat(fd):
            info = real_fstat(fd)
            values = list(info)
            values[6] = 1  # st_size
            return os.stat_result(values)

        monkeypatch.setattr(files_module.os, "fstat", small_fstat)
        with pytest.raises(UnsafeFileTypeError):
            read_regular_at(root, "ten", limit=4)
    finally:
        monkeypatch.undo()
        os.close(root)


def test_fifo_is_refused_without_blocking(tmp_path):
    """Opening a FIFO read-only normally blocks until a writer appears.

    Run in a subprocess with a timeout so a regression fails fast instead of
    hanging the whole suite.
    """
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    code = (
        "import sys\n"
        "from ordessa_infrastructure.filesystem import (\n"
        "    open_directory_nofollow, read_regular_at, UnsafeFileTypeError)\n"
        f"root = open_directory_nofollow({str(tmp_path)!r})\n"
        "try:\n"
        "    read_regular_at(root, 'pipe')\n"
        "except UnsafeFileTypeError:\n"
        "    print('REJECTED'); sys.exit(0)\n"
        "print('NOT-REJECTED'); sys.exit(2)\n"
    )
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert "REJECTED" in completed.stdout
