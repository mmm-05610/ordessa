"""Ordessa Workspace domain plugin.

Owns the workspace records, the environment authority (local/WSL/SSH), the
five `workspaces.*` wire methods and the workspace REST surface. Programs
against `server_plugin_api` plus the Server's generic vocabulary
(`ordessa_server.errors`, `.records`, `.ids`, `.wire`) — never against the
host's business modules.
"""
from ordessa_workspace.records import WorkspaceRecords
from ordessa_workspace.service import WorkspaceService, WslConnectionPort

__all__ = ["WorkspaceRecords", "WorkspaceService", "WslConnectionPort"]
