"""T06-migration — guards that the SR-1b contract swap did not lose a prohibition.

This file exists because the guard suites (`test_prohibitions_t03g.py`,
`test_boundaries_t03b.py`) used to pin **Q3's own** intent vocabulary —
`TargetSlot`, a local `MountContent`, `SetRebuildClassOption`, `InvokeSubagent`,
a local `IntentSet`, a local `TargetDescriptor` — written before the Harness
contract existed. `harness-api` was published and consumed, the local vocabulary
was **deleted**, and the adapters now emit only real
`ordessa_harness_api` types (`IntentSet`, `MountContent`, `ContentRef`,
`TargetHandle`, `FieldPath`, `BindSecret`, `IntentSource`, `AdapterContext`,
`ConfigurationAdapter`).

A migration is only honest if the *prohibition* survives the *rename*, so these
tests pin the four claims that the deleted vocabulary used to carry by shape and
can now only carry by behaviour, per `specs/011-q3-subagents/api-requests.md`
§"SR-1b FINAL answers" and §SR-12/SR-13:

* **no second sealed vocabulary** (CA2): nothing in this package may define or
  re-export a look-alike intent type, and no test may still need the deleted
  names — a deleted guard that nobody misses is a lost guard;
* **whole-generation rebuild, never a patch series** (SR-1b FINAL (a)): one
  `IntentSet` of `MountContent` per complete collection, and this domain emits
  no in-place `SetField` and no `ResetField` — the materializer implements only
  `remove-key` (`private_generation.py:259-263`), so routing a reset through it
  would be a silent no-op;
* **FR09 removal is `RemoveOwnedContent`** (SR-1b FINAL (b)), keyed to the
  carrier-granted owner and bounded to this facet's own relative names — never a
  name outside the grant, which is what makes "the user's native file is
  unreachable" true at the intent level and not only on the filesystem;
* **a declared credential stays refused while a host-granted binding becomes
  `BindSecret`** (FR05/G09 with the official channel): the refusal is not
  softened by the new type existing, and a credential without a host-issued
  environment target has no legal destination at all.

Evidence level: L1. Every guard has an inline capability probe, and the
executable-mount guard runs across **all three brand faces**, not just the one
that emits today.
"""
from __future__ import annotations

import ast
import dataclasses
import hashlib
import os
from pathlib import Path
from typing import Any

import pytest
from ordessa_harness_api import (
    AdapterContext, BindSecret, ContentRef, ContractError, FieldPath,
    Installation, IntentSet, IntentSource, InvokeAction, MountContent,
    RemoveOwnedContent, ResetField, SetField, TargetDescriptor, TargetHandle,
)

TESTS_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = TESTS_DIR.parent
PKG_DIR = PACKAGE_DIR / "src" / "ordessa_assets_subagents"

#: The intent/target **value** types the published contract owns. This package
#: may import and emit them; it may never define one, and may never re-export a
#: local substitute under the same name (SR-1b CA2: two sealed vocabularies
#: cannot both survive integration).
CONTRACT_OWNED_NAMES: frozenset[str] = frozenset({
    "IntentSet", "IntentSource", "TargetHandle", "FieldPath",
    "MountContent", "RemoveOwnedContent", "SetField", "ResetField",
    "BindSecret", "InvokeAction", "ContentRef", "AdapterContext",
    "TargetDescriptor",
})

#: The one contract name this package also uses as a *base class*: C0's
#: `ConfigurationAdapter` is a Protocol (structural typing), so Q3's
#: `adapters.base.ConfigurationAdapter` is an implementation of it, not a second
#: sealed shape. Registered explicitly so the collision stays visible — and so
#: the guard below checks the implementation really satisfies the protocol
#: instead of waving it through.
PROTOCOL_NAMES_WITH_LOCAL_IMPLEMENTATION: frozenset[str] = frozenset({
    "ConfigurationAdapter",
})

#: Names that existed *only* in Q3's deleted local vocabulary. Any surviving use
#: — in source or in a test — is a guard that was never actually migrated.
DELETED_LOCAL_NAMES: frozenset[str] = frozenset({
    "TargetSlot", "SetRebuildClassOption", "InvokeSubagent",
})

SHA = "sha256:" + "ab" * 32


# -- helpers ----------------------------------------------------------------


def source_files(root: Path) -> list[Path]:
    files = sorted(path for path in root.rglob("*.py")
                   if "__pycache__" not in path.parts)
    assert files, f"no python files under {root} — the guard would be blind"
    return files


def bound_names(tree: ast.Module) -> set[str]:
    """Module-level and class-level binding names defined *here*."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(getattr(t, "id", "") for t in node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            names.add(getattr(node.target, "id", ""))
    return names


def called_names(source: str) -> set[str]:
    """Every name invoked as a constructor/call, including `mod.Ctor(...)`."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                found.add(func.id)
            elif isinstance(func, ast.Attribute):
                found.add(func.attr)
    return found


def make_item(slug: str = "guard-reviewer", *, definition_id: str = "d-guard",
              description: str = "reviews diffs read-only",
              body: str = "Cite file and line for every finding.",
              **revision_kwargs) -> Any:
    from ordessa_assets_subagents import dto
    from ordessa_assets_subagents.adapters import intents

    revision_kwargs.setdefault("source", dto.SourceApproval(
        "user-upload", "upload/guard-reviewer.md", SHA, "u:guardian",
        "2026-09-28T10:00:00+00:00"))
    revision = dto.DefinitionRevision(definition_id, 1, SHA, body, **revision_kwargs)
    definition = dto.AgentDefinition("server:guard", definition_id, slug,
                                     "Guard reviewer", description, "public", "local")
    return intents.ManagedItem(definition, revision)


def directory_context(handles: tuple[TargetHandle, ...], *, harness: str = "claude",
                      with_environment: bool = False) -> AdapterContext:
    from ordessa_assets_subagents.adapters import claude

    targets = [TargetDescriptor(one, "directory", "content", "instance",
                                (("agents",),), ("restore-owned-baseline",))
               for one in handles]
    if with_environment:
        targets.append(TargetDescriptor(
            TargetHandle("assets-native-subagents-claude-environment", 1),
            "environment", "environment", "instance"))
    return AdapterContext(
        tuple(targets),
        Installation(harness, None, claude.CLAUDE_ADAPTER_SEMVER, "fixture:migration"),
        "acp", "instance", "fixture:capability",
    )


def source(item_id: str = "d-guard", *, facet: str | None = None) -> IntentSource:
    from ordessa_assets_subagents.adapters import intents

    return IntentSource(intents.FACET_ID if facet is None else facet, item_id, "v1")


# -- 1. no second sealed vocabulary, and no test still needs the old one -----


def test_no_module_of_this_package_defines_a_contract_owned_intent_type():
    """CA2, package-wide: the deleted vocabulary may not come back anywhere.

    `test_adapter_intents_t06.py` pins this for the producing module; this guard
    covers the whole package *including* the `adapters/__init__.py` re-export
    surface, because a re-export that silently points at a local class is the
    exact way a duplicate contract survives review.
    """
    offenders: list[str] = []
    for path in source_files(PKG_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        defined = (bound_names(tree)
                   & (CONTRACT_OWNED_NAMES | PROTOCOL_NAMES_WITH_LOCAL_IMPLEMENTATION))
        # an import binding is not a definition; `bound_names` only reports
        # class/def/assign forms, so a re-export line is clean by construction
        for name in sorted(defined - PROTOCOL_NAMES_WITH_LOCAL_IMPLEMENTATION):
            offenders.append(f"{path.relative_to(PKG_DIR)}: defines {name}")
    assert offenders == [], (
        "SR-1b: two sealed intent vocabularies cannot both survive integration — "
        "these names belong to ordessa_harness_api:\n" + "\n".join(offenders))
    assert bound_names(ast.parse(
        (PKG_DIR / "adapters/base.py").read_text(encoding="utf-8"))) & (
        CONTRACT_OWNED_NAMES | PROTOCOL_NAMES_WITH_LOCAL_IMPLEMENTATION
    ) == set(PROTOCOL_NAMES_WITH_LOCAL_IMPLEMENTATION), (
        "the registered name collision changed shape; re-read the protocol guard "
        "below before widening it")

    # capability: the same scan does report a redefinition
    synthetic = "class MountContent:\n    pass\n\nSetField = object\n"
    assert bound_names(ast.parse(synthetic)) & CONTRACT_OWNED_NAMES == {
        "MountContent", "SetField"}, "the definition scan is blind"

    # and the live re-exports really are the contract's objects
    from ordessa_assets_subagents import adapters

    for name in sorted(CONTRACT_OWNED_NAMES):
        exported = getattr(adapters, name, None)
        if exported is None:
            continue  # not re-exported at all is legal; a look-alike is not
        module = getattr(exported, "__module__", "") or ""
        assert module.startswith("ordessa_harness_api"), (
            f"adapters.{name} is re-exported from {module!r}, not the contract")


def test_the_local_configuration_adapter_base_really_implements_the_protocol():
    """The registered exception, checked instead of assumed.

    `adapters.base.ConfigurationAdapter` keeps the contract's *name* because C0's
    is a Protocol; that is only harmless if the local base actually provides the
    protocol surface. If it ever drifts, the shared name stops being an
    implementation and becomes the second vocabulary CA2 warned about.
    """
    from ordessa_assets_subagents.adapters import base as adapters_base
    from ordessa_harness_api import ConfigurationAdapter as ContractProtocol

    for member in sorted(getattr(ContractProtocol, "__annotations__", {}) or ()):
        assert hasattr(adapters_base.ConfigurationAdapter, member), member
    protocol_members = {"descriptor", "assess", "compile", "verify"}
    missing = sorted(name for name in protocol_members
                     if not hasattr(adapters_base.ConfigurationAdapter, name))
    assert missing == [], f"the local base no longer implements the protocol: {missing}"
    # compile is the face that must hand back the real contract type
    from ordessa_assets_subagents.adapters import ClaudeAdapter

    produced = ClaudeAdapter().compile(
        directory_context((TargetHandle("assets-native-subagents-claude-generation", 1),)),
        [make_item()], source())
    assert type(produced) is IntentSet, type(produced)
    assert IntentSet.__module__.startswith("ordessa_harness_api")


def test_the_deleted_local_vocabulary_has_no_consumer_left():
    """The old slot/option/invoke types are gone; nothing may still ask for them.

    A name that only ever appeared in prose is fine (this file included), so the
    scan is over code nodes — identifiers, attributes and keywords — of every
    test and source module in the package.
    """
    usages: list[str] = []
    for path in source_files(PACKAGE_DIR / "tests") + source_files(PKG_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in DELETED_LOCAL_NAMES:
                usages.append(f"{path.name}: identifier {node.id}")
            elif isinstance(node, ast.Attribute) and node.attr in DELETED_LOCAL_NAMES:
                usages.append(f"{path.name}: attribute .{node.attr}")
            elif isinstance(node, ast.keyword) and node.arg == "target_slot":
                usages.append(f"{path.name}: keyword target_slot=")
    assert usages == [], (
        "these belong to the intent vocabulary deleted at SR-1b; a test that "
        "still names one is a guard that was never migrated, and a source that "
        "names one is a reintroduction:\n" + "\n".join(usages))

    # capability: the scan catches a re-planted consumer
    planted = (
        "from ordessa_assets_subagents.adapters import TargetSlot\n\n"
        "def f():\n    return TargetSlot.PRIVATE_GENERATION_CLAUDE\n"
    )
    caught = []
    tree = ast.parse(planted)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in DELETED_LOCAL_NAMES:
            caught.append(node.id)
    assert caught == ["TargetSlot"], "the deleted-name scan is blind"


# -- 2. whole-generation rebuild: one set, no in-place patch, no reset -------


def test_this_domain_emits_no_setfield_and_no_resetfield_anywhere():
    """SR-1b FINAL (a)+(b): completeness comes from a whole-generation rebuild.

    The deleted local vocabulary had `SetRebuildClassOption`; the real contract
    has `SetField`/`ResetField`, and neither may be used as a substitute:
    `SetField` claims a *file* and is applyable in place, which capability-
    matrix C-6 disproves for the rebuild-class keys, and the materializer
    implements only the `remove-key` baseline rule, so a `ResetField` would be
    accepted by the DTO and quietly unsupported on the apply side. The compile
    faces emit mounts only; removal is `RemoveOwnedContent`.
    """
    constructions: list[str] = []
    for path in source_files(PKG_DIR):
        source_text = path.read_text(encoding="utf-8")
        hits = called_names(source_text) & {"SetField", "ResetField"}
        if hits:
            constructions.append(f"{path.relative_to(PKG_DIR)}: {sorted(hits)}")
    assert constructions == [], (
        "nothing may route an in-place option or a reset through those types "
        "(api-requests.md §SR-1b FINAL, §SR-12 G-2/G-4):\n"
        + "\n".join(constructions))

    from ordessa_assets_subagents.adapters import ClaudeAdapter, compile_all

    handle = TargetHandle("assets-native-subagents-claude-generation", 4)
    context = directory_context((handle,))
    granted = source()
    item = make_item()
    for produced in (ClaudeAdapter().compile(context, [item], granted),
                     compile_all([item], context, granted,
                                 render=lambda one: f"# {one.native_name}\n")):
        kinds = {type(one) for one in produced.intents}
        assert kinds == {MountContent}, kinds
        assert all(one.target is handle for one in produced.intents)
        assert len(produced.intents) == 1

    # a complete collection is ONE set with one mount per item — never a
    # per-item patch series the caller would have to keep ordered
    three = [make_item(slug=f"reviewer-{i}", definition_id=f"d-{i}") for i in range(3)]
    complete = compile_all(three, context, granted,
                           render=lambda one: f"# {one.native_name}\n")
    assert len(complete.intents) == 3
    assert {one.relative_name for one in complete.intents} == {
        f"agents/reviewer-{i}.md" for i in range(3)}
    assert len({one.target for one in complete.intents}) == 1

    # capability: the constructor scan does report the forbidden shapes
    assert called_names("intent = ResetField(source, target, path, 'remove-key')\n") \
        == {"ResetField"}
    assert called_names("x = SetField(\n    source=source,\n    target=target,\n"
                        "    field_path=path,\n    typed_value=1,\n)\n") == {"SetField"}

    # and the contract itself would accept a legal-but-unsupported reset, which
    # is exactly why this refusal is Q3's to keep
    ResetField(source=granted, target=handle, field_path=FieldPath(("agents",)),
               baseline_rule="restore-owned-baseline")


# -- 3. FR09 removal is RemoveOwnedContent, bounded to this facet's grant ----


def test_removal_addresses_only_this_facets_own_relative_names():
    """FR09 at the intent level: a removal names a managed item, never a file.

    The old shape guaranteed it (a slot enum plus a bare native name); the real
    guarantee is `RemoveOwnedContent.relative_name` inside the grant prefix,
    plus the interpreter `mount_native_name`, which is what verify/reset use to
    decide "ours". Ownership itself is not in the intent at all — the host keys
    it to the carrier-granted owner (`intent_merge.py:218-220`), so an adapter
    cannot declare what it owns.
    """
    from ordessa_assets_subagents import errors
    from ordessa_assets_subagents.adapters import intents

    handle = TargetHandle("assets-native-subagents-claude-generation", 4)
    granted = source()
    removal = intents.build_remove(granted, handle, native_name="guard-reviewer")
    assert type(removal) is RemoveOwnedContent
    assert removal.relative_name == "agents/guard-reviewer.md"
    assert not os.path.isabs(removal.relative_name)

    # nothing outside the managed layout can be read back as ours
    for outside in ("settings/x.md", "agents/x.toml", "hooks/a.md"):
        smuggled = MountContent(
            source=granted, target=handle, relative_name=outside,
            immutable_content_ref=intents.build_mount(
                granted, handle, native_name="guard-reviewer",
                content="# x\n").immutable_content_ref,
            mode="read-only",
        )
        with pytest.raises(errors.DomainError) as info:
            intents.mount_native_name(smuggled)
        assert info.value.code == errors.TARGET_CONFLICT, outside

    # the intent carries no owner/declared-facet field of its own
    assert {f.name for f in dataclasses.fields(RemoveOwnedContent)} == {
        "source", "target", "relative_name", "kind"}, RemoveOwnedContent.__doc__

    # capability: a relative name that would escape is refused upstream too
    for escape in ("../x.md", "/etc/x.md", "agents/../x.md", "agents\\x.md"):
        with pytest.raises(ContractError):
            RemoveOwnedContent(source=granted, target=handle, relative_name=escape)


# -- 4. the executable-mount prohibition spans every face -------------------


def test_no_compile_face_in_this_domain_can_mount_executable_content():
    """`MountContent.mode` is a real two-value literal; only `read-only` is
    reachable here, for **every** brand face, not just the emitting one.

    A refusal-only face (codex, pi) trivially satisfies "no executable mount",
    so the probe also requires the refusal to be a named domain error: a face
    that stopped producing intents altogether would otherwise turn this guard
    green by deletion (the failure mode verification.md warns about).
    """
    from ordessa_assets_subagents import errors
    from ordessa_assets_subagents.adapters import (
        ClaudeAdapter, CodexAdapter, PiAdapter,
    )

    handle = TargetHandle("assets-native-subagents-claude-generation", 4)
    codex_handle = TargetHandle("assets-native-subagents-codex-generation", 4)
    claude_context = directory_context((handle,))
    codex_context = directory_context((codex_handle,), harness="codex")
    item = make_item()
    granted = source()

    emitted = ClaudeAdapter().compile(claude_context, [item], granted)
    assert {type(one) for one in emitted.intents} == {MountContent}
    assert {one.mode for one in emitted.intents} == {"read-only"}

    for face, context, label in ((CodexAdapter(), codex_context, "CodexAdapter"),
                                 (PiAdapter(), claude_context, "PiAdapter")):
        with pytest.raises(errors.DomainError) as refused:
            face.compile(context, [item], granted)
        assert refused.value.code, label
        assert not isinstance(refused.value, AssertionError), label

    # capability: the mode literal really is open upstream, so the guard above
    # is the only thing between this domain and a mounted executable
    executable = MountContent(
        source=granted, target=handle, relative_name="agents/x.md",
        immutable_content_ref=_ref(b"#!/bin/sh\n"), mode="executable")
    assert executable.mode == "executable"


def _ref(data: bytes) -> ContentRef:
    digest = hashlib.sha256(data).hexdigest()
    return ContentRef(reference=digest, sha256=digest, size=len(data))


# -- 5. a declared credential stays refused; a granted binding is BindSecret -


def test_a_definition_declared_credential_is_refused_but_a_host_binding_becomes_bindsecret():
    """FR05/G09 against the real channel (SR-1b: `BindSecret` now exists).

    The official channel did not soften the prohibition: a credential *named by
    a definition* is still refused, because a declaration is not a grant. Only a
    host-injected binding, aimed at a host-issued environment target, becomes a
    `BindSecret` — and with no environment target the credential has no legal
    destination, so nothing is emitted at all.
    """
    from ordessa_assets_subagents import errors
    from ordessa_assets_subagents.adapters import ClaudeAdapter, compile_all, intents

    handle = TargetHandle("assets-native-subagents-claude-generation", 4)
    plain = directory_context((handle,))
    granted = source()

    # (a) a declaration is refused — and refused *before* any intent exists
    for credential_key in ("api_key", "apiKey", "password", "access_token",
                           "private_key"):
        item = make_item(retained_native_fields={credential_key: "x"},
                         definition_id=f"d-{credential_key}")
        with pytest.raises(errors.DomainError) as info:
            compile_all([item], plain, granted, render=lambda one: "# x\n")
        assert info.value.code == errors.DEFINITION_INVALID, credential_key
        with pytest.raises(errors.DomainError):
            ClaudeAdapter().compile(plain, [item], granted)
        with pytest.raises(errors.DomainError):
            intents.scan_credential_bearing_fields(item)

    # (b) the same value as a host-granted binding is legal, and is a BindSecret
    with_environment = directory_context((handle,), with_environment=True)
    produced = compile_all(
        [make_item()], with_environment, granted, render=lambda one: "# x\n",
        secret_bindings=(("model-api-key", "secret-ref-workspace-1"),))
    kinds = [type(one) for one in produced.intents]
    assert MountContent in kinds and BindSecret in kinds, kinds
    binding = next(one for one in produced.intents if isinstance(one, BindSecret))
    assert type(binding) is BindSecret
    assert binding.source is granted
    granted_environment = [one for one in with_environment.targets
                           if one.handle is binding.target]
    assert granted_environment and granted_environment[0].kind == "environment", \
        granted_environment
    assert binding.slot == "model-api-key" and binding.secret_ref == "secret-ref-workspace-1"
    # ... and the binding carries a *reference*, never the secret value
    assert "-----BEGIN" not in repr(produced.intents)

    # (c) without an environment target the credential has nowhere to go
    with pytest.raises(errors.DomainError) as no_destination:
        compile_all([make_item()], plain, granted, render=lambda one: "# x\n",
                    secret_bindings=(("model-api-key", "secret-ref-1"),))
    assert no_destination.value.code == errors.TARGET_CONFLICT

    # capability: the contract's own routing rule still bites a plaintext field
    with pytest.raises(ContractError):
        SetField(source=granted, target=handle,
                 field_path=FieldPath(("model_api_key",)), typed_value="sk-live")
    with pytest.raises(ContractError):
        SetField(source=granted, target=handle, field_path=FieldPath(("env", "token")),
                 typed_value="sk-live")

    # and an invoke intent is unconstructible without an invokable fact (G17)
    with pytest.raises(errors.DomainError):
        intents.build_invoke_action(granted, native_name="guard-reviewer",
                                    action_id="native-subagent.invoke",
                                    schema_version="v1", invokable_evidence=())
    assert type(intents.build_invoke_action(
        granted, native_name="guard-reviewer", action_id="native-subagent.invoke",
        schema_version="v1", invokable_evidence=("acp-control-observation-1",))
        is InvokeAction)
