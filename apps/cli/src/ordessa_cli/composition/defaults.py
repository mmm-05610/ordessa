"""Zero-configuration client target: the same root, token file and port as the Server.

A standalone `ordessa` may be invoked with no arguments at all. It then addresses
the one default instance: the C-01 data root (flag → environment → `$HOME/.ordessa`),
the token locator from the shared layout contract, and the product's default
loopback port. Nothing here invents a second configuration format or writes state;
an explicit `--config` always wins and never falls back to this path.
"""
from __future__ import annotations

from pathlib import Path

from ordessa_infrastructure.layout import DEFAULT_CLIENT_PORT, resolve_data_root, token_file
from ordessa_system_access_client import ClientError, Service, read_token_file


class DefaultTargetRefused(RuntimeError):
    """The default instance cannot be addressed; never silently turned into local mode."""

    code = "SERVER_UNREACHABLE"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def default_data_root() -> Path:
    return resolve_data_root().path


def default_service(*, data_root: str | None = None, port: int | None = None) -> Service:
    """The default instance's service descriptor (alias, endpoint, token)."""
    root = Path(data_root) if data_root is not None else default_data_root()
    if not root.is_absolute():
        raise DefaultTargetRefused('data root must be absolute')
    selected = DEFAULT_CLIENT_PORT if port is None else port
    if type(selected) is not int or not 0 < selected <= 65535:
        raise DefaultTargetRefused('port must be between 1 and 65535')
    try:
        token = read_token_file(str(token_file(root)))
    except ClientError as error:
        raise DefaultTargetRefused(
            f"no usable instance token under {root} ({error.code}); start `ordessa-server` "
            "for the default instance, or pass --state/--config explicitly") from None
    return Service('default', f"http://127.0.0.1:{selected}", token)


__all__ = ["DefaultTargetRefused", "default_data_root", "default_service"]
