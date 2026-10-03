"""The native-subagent-definitions domain plugin — one service, its wire face.

Owns the `assets.subagents.*` wire methods, the `DefinitionStore` directory and
the `DefinitionService` instance, registered through `server_plugin_api` and
activated by the plugin host (T13 / gate G21: the product enables **one**
service for this domain; nothing here keeps a second copy of the legacy
authorization edge alive — grants, roster, `run_subagent` and child-turn limits
stay with `ordessa_server_compat`, see `specs/011-q3-subagents/integration-request.md`
I-4, and this plugin never dispatches a subagent (spec FR12)).

When this plugin is not composed, its methods are honestly absent: not advertised
by `server.hello`, refused by dispatch as unknown. When it is composed but its
optional seams are not, it degrades the way rollout R07 requires — reads and
content CRUD work, a permission-bearing publish and every apply/invoke-shaped
call refuses with the missing seam named.

Port contract — this plugin **consumes** exactly three facts and **provides**
exactly one:

- `database` / `idempotency` are **not** requested: the domain store is
  file-backed (`store.py` owns the CAS rows and the operation receipts), so
  asking the host for storage primitives it never touches would be a false
  dependency. There is no service locator either — `contracts.md` keeps every
  cross-domain fact on a declared port.
- `assets.subagents.context@1` (`wire.CONTEXT_PORT`, optional) — the request
  authentication context: the server-attested principal, the server scope, the
  verified project binding, and the permission ceiling the service consults for
  every revision. Absent, `wire.DeploymentAttestation` attests one operator
  principal for the whole data root, binds no project or Profile and grants no
  permission — narrower than any real context, never a permissive default (SR-6).
- `assets.subagents.import_root@1` (`wire.IMPORT_ROOT_PORT`, optional) — the
  approved import location. Absent, the plugin's own directory under the data
  root; a client-named host path is never an input (§C1).
- `server.instance_id` (host facade) — the data root's process identity, used
  only to name the attested principal/scope of the default context.
- `authorizer_port_name` / `authorizer_conflict_types` (constructor inputs,
  forwarded to `wire.SubagentsWire` and on to the permissions seam) — the
  authorizer wiring §SR-13b row 4 / §SR-15 option 3 put on the **composition
  root**: this plugin may not import Q5's provider package to learn the port
  name or the authority's conflict types, so they arrive from here. Supplied,
  the seam classifies conflicts as conflicts; absent,
  `missing_production_collaborators()` names both gaps and the seam fails
  closed (`OPERATION_UNKNOWN`), never a stub authority and never "the port had
  no objection".
- provides `assets.subagents.service@1` — the one `DefinitionService` Profile,
  Chat and Settings consume, so the effective set is never re-derived twice
  (§C1 "供 Profile 与 Chat 使用同一个服务", §C2).

Data layout under the host's data root, one directory named by the plugin id,
never a CWD-relative or absolute user path::

    <data_root>/ordessa.assets-subagents/store/definitions/<id>/definition.json
    <data_root>/ordessa.assets-subagents/store/definitions/<id>/revisions/<n>.json
    <data_root>/ordessa.assets-subagents/store/receipts/<scope>/<key>.json
    <data_root>/ordessa.assets-subagents/approved-imports/     (import source)

Disposal drops this plugin's own references and touches nothing else: stored
definitions survive an unload, hide-not-delete (§C5), and the next activation of
this plugin reads the same rows back.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from server_plugin_api import (
    ServerPluginContext,
    ServerPluginDescriptor,
    ServerPluginRegistration,
)

from .service import DefinitionService
from .store import DefinitionStore
from .wire import (
    CONTEXT_PORT,
    IMPORT_ROOT_PORT,
    SERVICE_PORT,
    SubagentsWire,
    attestation_for,
    missing_authorizer_collaborators,
)

PLUGIN_ID = "ordessa.assets-subagents"

#: The domain's own subtree of the data root. Named by the plugin id so a
#: uninstall leaves an identifiable, auditable directory rather than loose files
#: (`AGENTS.md` rule 5: this layout is this domain's, versioned inside it).
DOMAIN_DIR = PLUGIN_ID

#: The store root and the approved import root inside that subtree.
STORE_DIR = "store"
IMPORT_DIR = "approved-imports"


class NativeSubagentsServerPlugin:
    """Native subagent definitions: the content library and its wire face."""

    def __init__(self, *, attestation: Any | None = None,
                 import_root: Any | None = None,
                 authorizer_port_name: str | None = None,
                 authorizer_conflict_types: Sequence[type[BaseException]] = ()) -> None:
        #: A controlled composition injects the seams here; `None` means
        #: "resolve them from the ports the host hands this plugin" — the
        #: explicit object replaces that resolution and nothing else.
        self._attestation_override = attestation
        self._import_root_override = import_root
        #: The §SR-15 authorizer wiring, injected and forwarded unchanged. `None`
        #: / empty are recorded as missing collaborators, never filled in with a
        #: port this plugin invented.
        self._authorizer_port_name = authorizer_port_name
        self._authorizer_conflict_types = tuple(authorizer_conflict_types or ())
        self._service: DefinitionService | None = None
        self._store: DefinitionStore | None = None

    def missing_production_collaborators(self) -> tuple[str, ...]:
        """The authorizer wiring this composition did not supply — checkable
        before `build()`, in the style of `apply.missing_production_collaborators()`."""
        return missing_authorizer_collaborators(
            port_name=self._authorizer_port_name,
            conflict_types=self._authorizer_conflict_types,
        )

    @property
    def service(self) -> DefinitionService | None:
        """The built service — None before `build()` and again after disposal,
        so a stopped round cannot be read through the plugin object."""
        return self._service

    def descriptor(self) -> ServerPluginDescriptor:
        return ServerPluginDescriptor(
            id=PLUGIN_ID, display_name="Native subagent definitions", version="1",
            # `requires` is empty on purpose: this domain installs without the
            # workspace, the harness, the permissions backend or the Profile —
            # the seams it would defer to are optional ports, resolved at call
            # time, and their absence is a named refusal not a startup failure.
            requires=(),
        )

    def build(self, context: ServerPluginContext) -> ServerPluginRegistration:
        """Compose this plugin's face, forwarding the authorizer wiring as given.

        `authorizer_port_name` / `authorizer_conflict_types` travel to the wire
        untouched (§SR-15 option 3): the seam they reach has no other source for
        them, and this method invents none — an un-supplied pair stays visible
        through `missing_production_collaborators()` /
        `SubagentsWire.missing_production_collaborators()`.
        """
        ports = context.ports
        domain_root = Path(context.data_root) / DOMAIN_DIR
        store = DefinitionStore(domain_root / STORE_DIR)
        attestation = self._resolve_attestation(ports)
        import_root = self._resolve_import_root(ports, domain_root)
        service = DefinitionService(store, authority=attestation)
        self._service = service
        self._store = store

        wire = SubagentsWire(
            service=service, attestation=attestation, import_root=import_root,
            #: A composed context is the only thing that can call itself a
            #: ceiling authority; the deployment default cannot grant one, and
            #: `SubagentsWire` refuses a permission-bearing publish while the
            #: claim would be unadjudicated (SR-6, R07).
            ceiling_authority_wired=(
                self._attestation_override is not None
                or ports.get(CONTEXT_PORT) is not None
            ),
            authorizer_port_name=self._authorizer_port_name,
            authorizer_conflict_types=self._authorizer_conflict_types,
            owner=PLUGIN_ID,
        )
        return ServerPluginRegistration(
            methods=wire.descriptors(),
            http_routes=(),
            provided_ports={SERVICE_PORT: service},
            # No start hook: this domain recovers nothing at startup — its rows
            # are CAS files and its receipts are queried by operation key.
            start_hooks=(),
            stop_hooks=(),
            disposal=self._dispose,
        )

    # -- seam resolution ----------------------------------------------------

    def _resolve_attestation(self, ports: Mapping[str, Any]) -> Any:
        if self._attestation_override is not None:
            return self._attestation_override
        return attestation_for(ports, str(ports.get("server.instance_id") or ""))

    def _resolve_import_root(self, ports: Mapping[str, Any],
                             domain_root: Path) -> Path:
        supplied = self._import_root_override
        if supplied is None:
            supplied = ports.get(IMPORT_ROOT_PORT)
        if supplied is None:
            return domain_root / IMPORT_DIR
        return Path(supplied() if callable(supplied) else supplied)

    # -- teardown -----------------------------------------------------------

    def _dispose(self) -> None:
        """Forget this plugin's own objects and nothing else.

        The store owns no connection (the host's `database` port is not even
        requested), the service owns no transport, and the files stay exactly
        where they are: removing a provider hides its definitions, it never
        deletes a user's data (§C5, contracts §C2 "provider 卸载时 … 保留数据").
        """
        self._service = None
        self._store = None
