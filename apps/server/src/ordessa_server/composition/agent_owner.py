"""Single Agent owner composition for the default Server product.

No default authority is manufactured here.  A caller may opt in with the
trusted authority/evidence ports listed below; without them the product keeps
the Agent provider unselected and its effect capabilities unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
import sqlite3
from contextlib import closing
from typing import Any, Callable

from ordessa_agents.public import (
    AgentManager, Records, InteractionService, ProfileService, HarnessCatalog,
)
from ordessa_server_plugin_api import OwnedRootBinding, RootOwnershipError
from ordessa_server.composition.root_ownership import _is_issued_owned_root_binding


class AgentOwnerUnavailable(RuntimeError):
    code = "AGENT_OWNER_UNAVAILABLE"


@dataclass(frozen=True)
class AgentOwnerInputs:
    """Explicit original services and restricted external ports; no EnvironmentUse."""
    profile_service: ProfileService
    harness_catalog: HarnessCatalog
    endpoint_resolver: Any
    preparation_resolver: Any
    lifecycle_authority: Any
    interaction_authority: Any
    method_factory: Callable[[Any], Any]
    close: Callable[[], None] | None = None


@dataclass
class AssembledAgentOwner:
    manager: AgentManager
    interactions: InteractionService
    records: Records
    profile_service: ProfileService
    harness_catalog: HarnessCatalog
    method_factory: Callable[[Any], Any]
    close_callback: Callable[[], None] | None = None
    _revoked: bool = False

    def revoke(self):
        if self._revoked:return
        self._revoked=True
        try:
            if self.close_callback is not None:self.close_callback()
        finally:self.records.close()


def _validate_inputs(inputs):
    if (type(inputs) is not AgentOwnerInputs
            or type(inputs.profile_service) is not ProfileService
            or type(inputs.harness_catalog) is not HarnessCatalog
            or not callable(inputs.method_factory)):
        raise AgentOwnerUnavailable('original Profile service, pinned Harness catalog and method assembly required')
    required={'endpoint_resolver':('resolve',),'preparation_resolver':('resolve',),
        'lifecycle_authority':('principal_scope','check_start','check_lifecycle_write','check_read_instance'),
        'interaction_authority':('principal_scope','check_read_binding','check_read_turn','check_send')}
    for name,methods in required.items():
        if any(not callable(getattr(getattr(inputs,name),method,None)) for method in methods):
            raise AgentOwnerUnavailable('Agent external port '+name+' is incomplete')
    if inputs.close is not None and not callable(inputs.close):
        raise AgentOwnerUnavailable('owner close callback is invalid')


def _expected_binding(store_path: Path | str, root_port) -> OwnedRootBinding:
    if not callable(getattr(root_port, "bind_owned_root", None)):
        raise AgentOwnerUnavailable("host root ownership proof is unavailable")
    store = Path(store_path)
    root = store.parent.parent
    if store != root / "state" / "core.sqlite":
        raise AgentOwnerUnavailable("Agent owner must use the existing Environment store path")
    child = root / "state" / "agent-owner" / "agent-instances.sqlite"
    try:
        binding = root_port.bind_owned_root(root_path=root, store_path=store,
                                            child_path=child)
        if not _is_issued_owned_root_binding(binding):
            raise AgentOwnerUnavailable("host returned an invalid root ownership proof")
        binding.validate_for(root_path=root, store_path=store, child_path=child)
    except (RootOwnershipError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise AgentOwnerUnavailable("host root ownership proof is invalid") from exc
    return binding


def records_path_for(store_path: Path | str, binding: OwnedRootBinding) -> Path:
    if not _is_issued_owned_root_binding(binding):
        raise AgentOwnerUnavailable("host root ownership proof was not issued by the Server")
    store = Path(store_path)
    root = store.parent.parent
    return root / "state" / "agent-owner" / "agent-instances.sqlite"


def preflight_records(store_path: Path | str, binding: OwnedRootBinding) -> Path:
    """Validate a fresh or original SDK ledger before opening the product core DB."""
    if not _is_issued_owned_root_binding(binding):
        raise AgentOwnerUnavailable("host root ownership proof was not issued by the Server")
    path = records_path_for(store_path, binding)
    try:
        binding.validate_for(root_path=path.parents[2], store_path=store_path,
                             child_path=path)
        store_artifacts = {Path(store_path), Path(str(store_path) + "-wal"),
                           Path(str(store_path) + "-shm")}
        journal_artifacts = {path, Path(str(path) + "-wal"), Path(str(path) + "-shm")}
        directories = {path.parents[2], path.parents[1], path.parent}
        for candidate in (*directories, *store_artifacts, *journal_artifacts):
            try:
                info = candidate.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode):
                raise AgentOwnerUnavailable("Agent owner path cannot contain symlinks")
            if candidate in journal_artifacts and (
                    not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077):
                raise AgentOwnerUnavailable('Agent records and sidecars must be private regular files')
            if candidate in directories and not stat.S_ISDIR(info.st_mode):
                raise AgentOwnerUnavailable("Agent owner parent must be a directory")
            if candidate == path.parent and info.st_mode & 0o077:
                raise AgentOwnerUnavailable("Agent owner directory must be private")
            if candidate in store_artifacts and not stat.S_ISREG(info.st_mode):
                raise AgentOwnerUnavailable("Environment store paths must be regular files")
    except AgentOwnerUnavailable:
        raise
    except Exception as exc:
        raise AgentOwnerUnavailable("Agent owner root proof is no longer current") from exc
    if not path.exists() and any(p.exists() for p in journal_artifacts if p!=path):
        raise AgentOwnerUnavailable('orphaned Agent record sidecars require explicit reconciliation')
    if path.exists():_validate_existing_records(path)
    return path


def _validate_existing_records(path):
    # Read-only shape validation; never adopt historical C4/Unit schema or infer
    # a missing row from a failed/foreign database. Same SDK operations stay on
    # their ORIGINAL rows and keep their unknown/reserved state on reopen.
    try:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            expected=('request_id','operation','principal','target','request_digest','endpoint_json',
                'status','operation_ref','payload','turn_id')
            columns=tuple(row[1] for row in db.execute('PRAGMA table_info(operations)'))
            if tables!={'operations'} or columns!=expected:
                raise AgentOwnerUnavailable('existing records are not the original Agent SDK schema')
    except sqlite3.Error as exc:
        raise AgentOwnerUnavailable('existing Agent records are unreadable') from exc


def _open_existing_records(path,binding,store_path):
    binding.validate_for(root_path=path.parents[2],store_path=store_path,child_path=path)
    fd=os.open(path,os.O_RDWR|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd);actual=path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077
                or (info.st_dev,info.st_ino)!=(actual.st_dev,actual.st_ino)):
            raise AgentOwnerUnavailable('existing Agent record identity differs')
        _validate_existing_records(path)
        binding.validate_for(root_path=path.parents[2],store_path=store_path,child_path=path)
        return fd,(info.st_dev,info.st_ino)
    except BaseException:
        os.close(fd);raise


def _open_fresh_journal(path: Path, binding: OwnedRootBinding,
                        store_path: Path | str) -> tuple[int, tuple[int, int]]:
    if not _is_issued_owned_root_binding(binding):
        raise AgentOwnerUnavailable("host root ownership proof was not issued by the Server")
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise AgentOwnerUnavailable("safe exclusive journal creation is unavailable on this platform")
    root = path.parents[2]
    binding.validate_for(root_path=root, store_path=store_path, child_path=path)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    state_fd = owner_fd = None
    created_fd = None
    created_identity = None
    try:
        state_fd = os.open("state", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                           dir_fd=root_fd)
        try:
            os.mkdir("agent-owner", mode=0o700, dir_fd=state_fd)
        except FileExistsError:
            pass
        owner_fd = os.open("agent-owner", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                           dir_fd=state_fd)
        owner_info = os.fstat(owner_fd)
        if owner_info.st_mode & 0o077:
            raise AgentOwnerUnavailable("Agent owner directory must be private")
        binding.validate_for(root_path=root, store_path=store_path, child_path=path)
        created_fd = os.open("agent-instances.sqlite", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=owner_fd)
        os.fchmod(created_fd, 0o600)
        info = os.fstat(created_fd)
        created_identity = (info.st_dev, info.st_ino)
        path_info = os.stat("agent-instances.sqlite", dir_fd=owner_fd, follow_symlinks=False)
        if stat.S_ISLNK(path_info.st_mode) or (path_info.st_dev, path_info.st_ino) != created_identity:
            raise AgentOwnerUnavailable("exclusive Agent journal identity changed")
        binding.validate_for(root_path=root, store_path=store_path, child_path=path)
        return created_fd, created_identity
    except BaseException:
        if owner_fd is not None and created_identity is not None:
            try:
                current = os.stat("agent-instances.sqlite", dir_fd=owner_fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) == created_identity:
                    for suffix in ("-wal", "-shm", ""):
                        try:
                            os.unlink("agent-instances.sqlite" + suffix, dir_fd=owner_fd)
                        except FileNotFoundError:
                            pass
            except OSError:
                pass
        if created_fd is not None:
            os.close(created_fd)
        raise
    finally:
        if owner_fd is not None:
            os.close(owner_fd)
        if state_fd is not None:
            os.close(state_fd)
        os.close(root_fd)



class _RootBoundPort:
    """Fence the original external port with the SAME held host root proof.

    Dynamic exposure preserves unavailable methods; this is not a new authority
    or a compatibility API. No root/permission lock crosses response waiting.
    """
    _CHECKS=frozenset({'principal_scope','check_start','check_lifecycle_write','check_instance_lifecycle','check_read_instance',
        'check_read_binding','check_read_turn','check_send','check_native_dispatch','check_read_native_operation'})
    def __init__(self,base,binding,store_path,error):
        self._base=base;self._binding=binding;self._store_path=store_path;self._error=error
    def _current(self):
        try:self._binding.validate_for(root_path=self._binding.root_path,store_path=self._store_path,child_path=self._binding.child_path)
        except Exception:raise self._error('PRODUCT_ROOT_CHANGED') from None
    def __getattr__(self,name):
        value=getattr(self._base,name) # Missing original methods remain absent.
        if name in {'guard_native_dispatch','guard_instance_lifecycle'}:
            from contextlib import contextmanager
            @contextmanager
            def guarded(*args,**kwargs):
                self._current()
                with value(*args,**kwargs):
                    self._current();yield
            return guarded
        if name in self._CHECKS:
            def checked(*args,**kwargs):
                self._current();return value(*args,**kwargs)
            return checked
        return value

def assemble_agent_owner(environment, inputs: AgentOwnerInputs,
                          binding: OwnedRootBinding) -> AssembledAgentOwner:
    """Product construction only; original Agent owns all online records/effects.

    Environment supplies a host-owned path, never an Agent issuer/store/Use.
    The historical operations.sqlite is neither opened nor upgraded.
    """
    _validate_inputs(inputs)
    store_path=getattr(environment,'store_path',None)
    path=preflight_records(store_path,binding)
    created=not path.exists()
    fd,identity=(_open_fresh_journal(path,binding,store_path) if created
        else _open_existing_records(path,binding,store_path))
    records=None
    try:
        records=Records(path)
        info=path.lstat()
        if stat.S_ISLNK(info.st_mode) or (info.st_dev,info.st_ino)!=identity:
            raise AgentOwnerUnavailable('Agent record identity changed while opening')
        binding.validate_for(root_path=path.parents[2],store_path=store_path,child_path=path)
        from ordessa_agents.sdk.manager import ManagerRefused
        from ordessa_agents.sdk.interactions import InteractionsRefused
        lifecycle=_RootBoundPort(inputs.lifecycle_authority,binding,store_path,ManagerRefused)
        interaction=_RootBoundPort(inputs.interaction_authority,binding,store_path,InteractionsRefused)
        manager=AgentManager(inputs.endpoint_resolver,records,profile_service=inputs.profile_service,
            harness_resolver=inputs.harness_catalog,preparation_resolver=inputs.preparation_resolver,
            lifecycle_authority=lifecycle)
        source=InteractionService(records,interaction,inputs.endpoint_resolver,
            native_prompts=inputs.harness_catalog.prompt_handlers())
        return AssembledAgentOwner(manager,source,records,inputs.profile_service,
            inputs.harness_catalog,inputs.method_factory,inputs.close)
    except BaseException:
        if records is not None:records.close()
        if created:_remove_created_journal(path,identity)
        raise
    finally:os.close(fd)


def _remove_created_journal(path: Path, identity: tuple[int, int]) -> None:
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or (info.st_dev, info.st_ino) != identity:
            return
        for candidate in (Path(str(path) + "-wal"), Path(str(path) + "-shm"), path):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
    except OSError:
        return


__all__ = ["AgentOwnerInputs", "AgentOwnerUnavailable", "AssembledAgentOwner",
           "assemble_agent_owner"]
