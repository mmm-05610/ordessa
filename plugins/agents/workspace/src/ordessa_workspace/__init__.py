"""Ordessa Workspace domain plugin.

Owns the workspace records, the environment authority (local/WSL/SSH), the
five `workspaces.*` wire methods and the workspace REST surface. Programs
against `ordessa_server_plugin_api` plus the Server's generic vocabulary
(`ordessa_server.errors`, `.records`, `.ids`, `.wire`) — never against the
host's business modules.
"""
__all__ = ["WorkspaceRecords", "WorkspaceService", "WslConnectionPort"]


def __getattr__(name):
    # Pure binding contracts do not activate storage/plugin services at import.
    if name=='WorkspaceRecords':
        from .records import WorkspaceRecords
        return WorkspaceRecords
    if name in {'WorkspaceService','WslConnectionPort'}:
        from . import service
        return getattr(service,name)
    raise AttributeError(name)
