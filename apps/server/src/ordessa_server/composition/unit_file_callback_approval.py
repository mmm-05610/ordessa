"""Explicit callback approval under the selected original Unit permission.

This optional product policy grants no Unit permission and provides no sandbox.
It approves configured file paths and an optional exact check command under
the current business guard, using only the native allow-once option. Units
still owns callback identity and file effects.
"""
from collections.abc import Mapping
from contextlib import nullcontext
from pathlib import Path

from ordessa_units.api import UnitApiRefused


class UnitFileCallbackApproval:
    def __init__(self, *, runtime, permission, environment_instance, allowed_paths=(),
                 allowed_relative_paths=(), scope_guard=None, approved_check_command=None):
        root = Path(permission.root_directory)
        if (not root.is_absolute() or root.resolve() != root or not root.is_dir()
                or permission.environment_identity != environment_instance.identity
                or not (allowed_paths or allowed_relative_paths)
                or scope_guard is not None and not callable(scope_guard)):
            raise UnitApiRefused('Explicit original Unit file approval scope required')
        paths = frozenset(Path(value) for value in allowed_paths)
        if any(not p.is_absolute() or p.resolve() != p
               or not p.is_relative_to(root) and scope_guard is None
               or any(part.is_symlink() for part in (p, *p.parents)) for p in paths):
            raise UnitApiRefused('Approved callback paths must belong to the selected directory')
        relative = frozenset(Path(value) for value in allowed_relative_paths)
        if any(p.is_absolute() or not p.parts or '..' in p.parts for p in relative):
            raise UnitApiRefused('Approved relative paths must remain in the original Unit cwd')
        if approved_check_command is not None:
            if (type(approved_check_command) is not str or not approved_check_command
                    or approved_check_command.strip() != approved_check_command
                    or not callable(scope_guard)
                    or any(ord(c) < 32 or ord(c) == 127 or c in ('\u2028', '\u2029')
                           for c in approved_check_command)):
                raise UnitApiRefused('Exact check command requires its original business scope guard')
            try:
                command_size = len(approved_check_command.encode('utf-8'))
            except UnicodeEncodeError as exc:
                raise UnitApiRefused('Exact check command must be valid UTF-8') from exc
            if command_size > 4096:
                raise UnitApiRefused('Exact check command exceeds its bounded scope')
        self.runtime, self.permission, self.environment = runtime, permission, environment_instance
        self.root, self.paths = root, paths
        self.relative = relative
        # Unit permission.root_directory bounds private runtime directories.
        # An external repository path additionally needs its original business
        # owner guard on every callback; a path DTO alone cannot extend scope.
        self.scope_guard = scope_guard
        self.approved_check_command = approved_check_command

    def _allowed(self, value, cwd):
        if type(value) is not str or not value:
            return False
        path = Path(value)
        if '..' in path.parts:
            return False
        path = path if path.is_absolute() else cwd / path
        targets = self.paths | frozenset(cwd / relative for relative in self.relative)
        return (path.resolve() in targets
                and not any(part.is_symlink() for part in (path, *path.parents)))

    def authorize(self, *, unit_ref, session_id, environment_identity, request_id, method, params):
        guard = (nullcontext() if self.scope_guard is None else self.scope_guard(
            unit_ref=unit_ref, session_id=session_id, method=method, params=params))
        with guard:
            return self._authorize(unit_ref=unit_ref, session_id=session_id,
                environment_identity=environment_identity, request_id=request_id,
                method=method, params=params)

    def _authorize(self, *, unit_ref, session_id, environment_identity, request_id, method, params):
        owner = self.runtime.unit_execution_owner
        if (owner.permission is not self.permission
                or environment_identity != self.environment.identity
                or type(request_id) not in (str, int) or not isinstance(params, Mapping)
                or params.get('sessionId') != session_id):
            raise UnitApiRefused('Callback differs from its selected original Unit permission')
        # Possession of the DTO is insufficient: the original owner rechecks
        # the retained handle, permission, Profile, Environment and live state.
        unit = self.runtime.units.get(unit_ref)
        owner.native_unit(unit, owner.authorization())
        if unit.snapshot().get('sessionId') != session_id:
            raise UnitApiRefused('Callback differs from its original Unit session')
        # The original Unit reservation owns cwd. The selected permission root
        # is a parent directory, not the native session's working directory.
        reservation = owner.records.owner_read_unit(unit_ref['unitId'])
        cwd = Path(reservation.facts['privateRootFacts']['cwd'])
        if (not cwd.is_absolute() or not cwd.is_relative_to(self.root) or cwd.resolve() != cwd
                or any(part.is_symlink() for part in (cwd, *cwd.parents))):
            raise UnitApiRefused('Original Unit cwd differs from its selected directory')
        if method in {'fs/read_text_file', 'fs/write_text_file'}:
            return self._allowed(params.get('path'), cwd)
        if method != 'session/request_permission':
            return False
        tool = params.get('toolCall')
        files = params.get('files')
        if params.get('approval') == 'command':
            return self._command_option(params, tool)
        if (params.get('approval') != 'file' or not isinstance(tool, Mapping)
                or tool.get('kind') not in {'read', 'edit'}
                or not isinstance(files, (list, tuple)) or not files):
            return None
        locations = tool.get('locations')
        if (not isinstance(locations, (list, tuple)) or not locations
                or any(not self._allowed(path, cwd) for path in files)
                or any(not isinstance(location, Mapping) or not self._allowed(location.get('path'), cwd)
                       for location in locations)):
            return None
        return self._once_option(params)

    @staticmethod
    def _once_option(params):
        options = params.get('options')
        if not isinstance(options, (list, tuple)):
            return None
        options = [option for option in options
                   if isinstance(option, Mapping) and option.get('kind') == 'allow_once'
                   and type(option.get('optionId')) is str and option['optionId']]
        return options[0]['optionId'] if len(options) == 1 else None

    def _command_option(self, params, tool):
        command = self.approved_check_command
        if (command is None or not isinstance(tool, Mapping) or tool.get('kind') != 'execute'
                or params.get('command') != command):
            return None
        raw = tool.get('rawInput')
        if not isinstance(raw, Mapping) or raw.get('command') != command:
            return None
        # The native command callback carries one fixed command. It cannot
        # combine that approval with a file, network or MCP request.
        for value in (params, raw):
            if any(value.get(key) not in (None, '', [], ()) for key in
                   ('files', 'host', 'protocol', 'port', 'mcpServer', 'mcpTool', 'commandActions')):
                return None
            if any(value.get(key) not in (None, '', [], ()) for key in
                   ('cwd', 'proposedExecpolicyAmendment', 'proposedNetworkPolicyAmendments')):
                return None
        if tool.get('locations') not in (None, [], ()):
            return None
        return self._once_option(params)
