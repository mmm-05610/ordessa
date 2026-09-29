"""Internal, non-published compile builders that emit the REAL C3 contract types.

Demotion note (SR-1b, CA2): this module used to own a second sealed intent
vocabulary (``TargetSlot`` / Q3 ``MountContent`` / ``SetRebuildClassOption`` /
``InvokeSubagent`` / Q3 ``IntentSet``). `harness-api` is published now
(checkpoint ``codex/011-harness-api-ready``), so two vocabularies cannot both
survive integration: the old types are **deleted**, and every artefact this
package produces is an ``ordessa_harness_api`` DTO. Nothing here is a public
cross-tree shape — the public shape is the API package's.

What stays (deliberately stricter than the contract, per
`docs/design/native-subagents/contracts.md` §C3 and capability-matrix.md):

* :func:`_check_token` — a bare-identifier grammar. The real validators
  (`TargetHandle`, `FieldPath`, `_relative_name`) refuse path separators and
  traversal, but NOT `~`, shell metacharacters, spaces or control bytes; a
  value like ``"~/.claude/agents"`` is a legal `FieldPath` segment upstream,
  so Q3 layers its own token check over every string before it reaches a
  contract constructor (no path, no shell, no `~`, no cwd — ever);
* digest binding: :func:`build_mount` computes the `ContentRef` digest from
  the bytes it stages, and a caller-supplied digest must stamp them
  (the old 「digest is bound to content」 rule survives);
* :func:`build_invoke_action` cannot be constructed without a non-empty
  invokable-fact evidence tuple (G11/G17: no evidence, no invoke);
* :func:`build_rebuild_class_option` — the published contract has NO
  rebuild-class option intent (`SetField` claims a file target and is
  applyable in place; `agents`/`setting_sources` at the Claude pin are
  rebuild-class, capability-matrix C-6), so this builder *always refuses*:
  the gap is reported to C0 (SR-3b-2), and no private side channel is
  invented;
* the owner question (§C3 「注册 owner 由宿主授予」) is structural, not
  conventional: `IntentSource` has no owner field at all
  (`ordessa_harness_api/intents.py:17-25`), the owner is stamped by the
  carrier (`ordessa_harness/application/configuration_service.py:198`
  `AuthorizedIntents(view.owner, …)`) and the merge authority *rejects* any
  intent whose source facet/item/version differs from the host-authorized
  submission (`ordessa_harness/materialization/intent_merge.py:166-173`).
  :func:`compile_all` therefore accepts a host-injected ``IntentSource`` and
  never constructs one: it validates the injected source's type exactly,
  refuses foreign facets, and stamps that same object on every intent.

:func:`compile_all` still produces the intents of the *complete* managed
collection in one shot (§C3 「一次性编译完整目标集合，不逐项拼补丁」): the
one-shot property in the real contract comes from the host materialising a
whole private generation per apply (`materialize_generation` publishes one
complete directory and there is *no hot apply*), and refusals here still
happen before any intent object exists.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from ordessa_harness_api import (
    AdapterContext, BindSecret, ContentRef, FieldPath, IntentSet, IntentSource,
    InvokeAction, MountContent, RemoveOwnedContent, TargetHandle,
)
from ordessa_harness_api.schema import looks_secret_name

from .. import decoder, digest, errors, limits

#: The facet this package may ever emit intents for. A source naming any
#: other facet is refused: Q3's builder cannot be reused to forge intents
#: attributed to somebody else's facet (§C3 owner-grant direction).
FACET_ID = "assets.native-subagents"

#: Filename == agent name, per the pinned Claude/Codex entry rules
#: (capability-matrix.md §Claude/§Codex, harness-adapters.md §格式映射).
NATIVE_NAME_PATTERN = r"[a-z0-9][a-z0-9._-]{0,63}"
NATIVE_NAME_RE = re.compile(r"\A" + NATIVE_NAME_PATTERN + r"\Z")

#: Layout inside the host-owned directory target. The first segment is the
#: stable claim prefix C0's FieldClaim machinery matches against
#: (`configuration_service._has_claim`: directory claims match the leading
#: segments of `relative_name`), so a complete managed set is one
#: `MountContent` per item sharing the ("agents",) claim.
MOUNT_DIRECTORY = "agents"

_SHELL_METACHARS = frozenset(" ;|&$<>(){}[]*?!~`'\"\\")


def _refuse(what: str, detail: str, *, code: str = errors.DEFINITION_INVALID) -> errors.DomainError:
    return errors.DomainError(code, detail=f"{what}: {detail}")


def _check_token(
    value: Any,
    *,
    what: str,
    pattern: re.Pattern[str] | None = None,
    code: str = errors.DEFINITION_INVALID,
) -> str:
    """A bare identifier: never a path, never a shell string, never control bytes.

    Stricter than the real validators on purpose: `FieldPath` and
    `_relative_name` only police separators and traversal, so Q3 adds the
    no-`~` / no-shell / no-space / no-control-byte layer itself before any
    string reaches a contract constructor.
    """
    if not isinstance(value, str):
        raise _refuse(what, "must be a plain string", code=code)
    if not value:
        raise _refuse(what, "must be non-empty", code=code)
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise _refuse(what, "control bytes are never allowed in an intent token", code=code)
    if len(value) > 128:
        raise _refuse(what, "intent tokens are bounded to 128 characters", code=code)
    if value.startswith("-"):
        raise _refuse(what, "flag-shaped tokens are refused", code=code)
    if decoder.is_path_shaped(value):
        raise _refuse(what, "a path-shaped value cannot be an intent token", code=code)
    if _SHELL_METACHARS.intersection(value):
        raise _refuse(what, "shell-shaped characters are not expressible here", code=code)
    if pattern is not None and pattern.fullmatch(value) is None:
        raise _refuse(what, f"must match the token grammar {pattern.pattern}", code=code)
    return value


def safe_field_path(segments: Sequence[str]) -> FieldPath:
    """A `FieldPath` no segment of which is path-, `~`- or shell-shaped.

    The real `FieldPath` already refuses `""`, `"."`, `".."`, `/` and `\\`
    (`ordessa_harness_api/intents.py:41-50`); this wrapper adds Q3's stricter
    per-segment grammar so nothing like `"~/.claude"` can ride through as a
    single dot-containing segment.
    """
    if isinstance(segments, (str, bytes)) or not isinstance(segments, Sequence):
        raise _refuse("field_path", "must be a sequence of segments")
    checked = tuple(_check_token(segment, what="field_path segment")
                    for segment in segments)
    return FieldPath(checked)


# -- host-granted source and context admission --------------------------------


def validate_source(source: Any) -> IntentSource:
    """Accept ONLY a host-injected, exactly-typed `IntentSource` for this facet.

    There is deliberately no way to obtain a source from inside this module:
    it is a parameter, never a default. A subclass or a look-alike object is
    refused (type identity, not duck typing), and a source naming another
    facet cannot use this builder — Q3 emits intents for
    ``assets.native-subagents`` only. The owner is nowhere in the shape:
    `IntentSource` has no owner field, and C0 stamps the carrier-granted
    owner outside the intent (`intent_merge.AuthorizedIntents.owner`,
    supplied from `view.owner` in `configuration_service._compile`).
    """
    if type(source) is not IntentSource:
        raise _refuse(
            "source",
            "an IntentSource granted by the host/registration context is "
            "required; this builder never constructs or defaults one and "
            "accepts no look-alike (design: 注册 owner 由宿主授予)",
            code=errors.TARGET_CONFLICT,
        )
    if source.facet_id != FACET_ID:
        raise _refuse(
            "source.facet_id",
            f"{source.facet_id!r} is not {FACET_ID!r}: this adapter may only "
            "emit intents for its own facet, never claim another contributor's",
            code=errors.TARGET_CONFLICT,
        )
    _check_token(source.item_id, what="source.item_id", code=errors.TARGET_CONFLICT)
    _check_token(source.contribution_version, what="source.contribution_version",
                 code=errors.TARGET_CONFLICT)
    return source


def validate_context(context: Any) -> AdapterContext:
    if not isinstance(context, AdapterContext):
        raise _refuse(
            "context",
            "the target is expressed by an injected AdapterContext "
            "(server-issued TargetHandles); raw paths, slot enums or "
            "handle strings are not accepted (design: 目标由 Harness 所有)",
            code=errors.TARGET_CONFLICT,
        )
    return context


def select_content_target(context: AdapterContext, *, harness_id: str) -> TargetHandle:
    """Pick the single directory/content target the generation mounts into.

    The handle is COPIED from the host-issued descriptor — the adapter
    cannot name, invent or re-point a target, and a host that issues no
    private-generation target simply makes compilation refuse.
    """
    candidates = [target for target in context.targets
                  if target.kind == "directory" and target.codec == "content"]
    if not candidates:
        raise _refuse(
            "context.targets",
            f"no content-coded directory target was issued for harness "
            f"{harness_id!r}; Q3 never derives a target from a name",
            code=errors.TARGET_CONFLICT,
        )
    if len(candidates) > 1:
        raise _refuse(
            "context.targets",
            "exactly one private-generation content target may be issued per "
            f"facet compile, got {len(candidates)}",
            code=errors.TARGET_CONFLICT,
        )
    handle = candidates[0].handle
    _check_token(handle.handle_id, what="target handle_id", pattern=NATIVE_NAME_RE,
                 code=errors.TARGET_CONFLICT)
    return handle


def select_environment_target(context: AdapterContext) -> TargetHandle:
    """Environment target for secret bindings, or a typed refusal."""
    candidates = [target for target in context.targets
                  if target.kind == "environment" and target.codec == "environment"]
    if not candidates:
        raise _refuse(
            "context.targets",
            "a secret binding needs a host-issued environment target; without "
            "one a credential has no legal destination and is never emitted",
            code=errors.TARGET_CONFLICT,
        )
    if len(candidates) > 1:
        raise _refuse(
            "context.targets",
            f"exactly one environment target may back secret bindings, got {len(candidates)}",
            code=errors.TARGET_CONFLICT,
        )
    handle = candidates[0].handle
    _check_token(handle.handle_id, what="environment handle_id", code=errors.TARGET_CONFLICT)
    return handle


# -- builders over the real intent types ---------------------------------------


def mount_relative_name(native_name: str, *, suffix: str = ".md",
                        directory: str = MOUNT_DIRECTORY) -> str:
    """`<directory>/<native_name><suffix>` — always two clean segments."""
    _check_token(directory, what="mount directory segment")
    _check_token(native_name, what="native_name", pattern=NATIVE_NAME_RE)
    if re.fullmatch(r"\A\.[a-z0-9]{1,10}\Z", suffix or "") is None:
        raise _refuse("mount suffix", "must be a short lowercase file extension like '.md'")
    relative = f"{directory}/{native_name}{suffix}"
    # The real MountContent re-checks this via `_relative_name`; assert the
    # segment split Q3 relies on for its claim prefix:
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise _refuse("relative_name", "normalized segments only")
    return relative


def mount_native_name(mount: MountContent, *, suffix: str = ".md",
                      directory: str = MOUNT_DIRECTORY) -> str:
    """Inverse of :func:`mount_relative_name` for verify/matching."""
    prefix = f"{directory}/"
    if not mount.relative_name.startswith(prefix) or "/" in mount.relative_name[len(prefix):]:
        raise errors.DomainError(
            errors.TARGET_CONFLICT,
            detail=f"mount {mount.relative_name!r} is outside the managed "
                   f"{prefix!r} layout this adapter compiles",
        )
    stem = mount.relative_name[len(prefix):]
    if not stem.endswith(suffix):
        raise errors.DomainError(
            errors.TARGET_CONFLICT,
            detail=f"mount {mount.relative_name!r} does not carry this "
                   f"adapter's {suffix!r} document suffix",
        )
    return stem[: -len(suffix)]


def build_mount(source: IntentSource, target: TargetHandle, *, native_name: str,
                content: str, content_digest: str | None = None,
                suffix: str = ".md",
                directory: str = MOUNT_DIRECTORY) -> MountContent:
    """A real `MountContent` whose `ContentRef` digest stamps the content.

    `ContentRef` is content-addressed EXTERNAL storage in C0's model: the
    service resolves `reference` against the runtime's `content` map and
    verifies size + sha256 before publishing bytes
    (`ordessa_harness/materialization/private_generation.py:268-277`,
    `data = content.get(ref)`). The adapter never carries document bytes in
    the intent — the reference is the hex digest itself, so the same content
    is the same address.
    """
    _check_token(native_name, what="native_name", pattern=NATIVE_NAME_RE)
    if not isinstance(target, TargetHandle):
        raise _refuse("target", "must be a host-issued TargetHandle",
                      code=errors.TARGET_CONFLICT)
    if not isinstance(content, str) or not content:
        raise _refuse("content", "must be a non-empty string")
    if any(ord(ch) < 0x20 for ch in content if ch not in "\t\n\r"):
        raise _refuse("content", "control bytes other than tab/newline/CR are refused")
    try:
        encoded = content.encode("utf-8")
    except UnicodeEncodeError as exc:  # lone surrogates etc.
        raise _refuse("content", "must be strictly utf-8 encodable text") from exc
    hex_sha = hashlib.sha256(encoded).hexdigest()
    if content_digest is not None:
        if not digest.is_digest(content_digest):
            raise _refuse("content_digest", "must be a `sha256:<64hex>` digest")
        if content_digest != digest.bytes_digest(encoded):
            raise _refuse("content_digest", "does not stamp the mounted content")
    relative = mount_relative_name(native_name, suffix=suffix, directory=directory)
    return MountContent(
        source=source,
        target=target,
        relative_name=relative,
        immutable_content_ref=ContentRef(reference=hex_sha, sha256=hex_sha,
                                         size=len(encoded)),
        mode="read-only",
    )


def build_remove(source: IntentSource, target: TargetHandle, *, native_name: str,
                 suffix: str = ".md", directory: str = MOUNT_DIRECTORY) -> RemoveOwnedContent:
    """A real `RemoveOwnedContent` — removes ONLY what the owner snapshot says
    this facet owns (contracts.md §C5 / FR09): C0's merge and materializer
    key ownership on the host-granted owner, not on any adapter-declared
    field (`intent_merge.py:218-220`, `private_generation.py:278-287`)."""
    if not isinstance(target, TargetHandle):
        raise _refuse("target", "must be a host-issued TargetHandle",
                      code=errors.TARGET_CONFLICT)
    relative = mount_relative_name(native_name, suffix=suffix, directory=directory)
    return RemoveOwnedContent(source=source, target=target, relative_name=relative)


def build_secret_binding(source: IntentSource, target: TargetHandle, *, slot: str,
                         secret_ref: str) -> BindSecret:
    """Route a credential through the REAL `BindSecret` channel (FR05/G09).

    Only an opaque, host-issued reference may be bound — never a value. A
    definition that merely *declares* a credential is still refused by
    :func:`scan_credential_bearing_fields` before this builder is ever
    reached: a user declaration is not a host grant.
    """
    if not isinstance(target, TargetHandle):
        raise _refuse("target", "must be a host-issued TargetHandle",
                      code=errors.TARGET_CONFLICT)
    _check_token(slot, what="secret slot")
    _check_token(secret_ref, what="secret_ref")
    return BindSecret(source=source, target=target, slot=slot, secret_ref=secret_ref)


def build_invoke_action(source: IntentSource, *, native_name: str,
                        action_id: str, schema_version: str,
                        invokable_evidence: Sequence[str]) -> InvokeAction:
    """A real `InvokeAction`, constructible only WITH invokable-fact evidence.

    `expected_observation` (the contract's "what must be seen to confirm"
    field, `ordessa_harness_api/intents.py:169-193`) carries the joined
    evidence references; an empty or non-tuple evidence is a refusal, because
    G17 forbids an invocation action without a proven control entry. The host
    merge additionally demands an explicit action grant
    (`configuration_service._has_claim` returns False for every
    `InvokeAction`), so this builder can never smuggle an invoke through.
    """
    _check_token(native_name, what="native_name", pattern=NATIVE_NAME_RE,
                 code=errors.NATIVE_ENTRY_UNAVAILABLE)
    if isinstance(invokable_evidence, (str, bytes)) or not isinstance(invokable_evidence, tuple):
        raise _refuse(
            "invokable_evidence", "must be a tuple of evidence references",
            code=errors.NATIVE_ENTRY_UNAVAILABLE,
        )
    if not invokable_evidence:
        raise _refuse(
            "invokable_evidence",
            "an invoke intent requires at least one concrete invokable-fact "
            "evidence reference (G17: no proven control entry, no action)",
            code=errors.NATIVE_ENTRY_UNAVAILABLE,
        )
    for entry in invokable_evidence:
        _check_token(entry, what="invokable_evidence entry",
                     code=errors.NATIVE_ENTRY_UNAVAILABLE)
    _check_token(action_id, what="action_id", code=errors.NATIVE_ENTRY_UNAVAILABLE)
    _check_token(schema_version, what="schema_version",
                 code=errors.NATIVE_ENTRY_UNAVAILABLE)
    expected = ";".join(_check_token(e, what="invokable_evidence entry",
                                     code=errors.NATIVE_ENTRY_UNAVAILABLE)
                        for e in invokable_evidence)
    return InvokeAction(source, action_id, schema_version, {"native_name": native_name},
                        expected)


def build_rebuild_class_option(option_key: Any, value: Any = None) -> Any:
    """ALWAYS refuses: the published contract cannot express rebuild-class.

    At `@agentclientprotocol/claude-agent-acp@0.81.2` the `agents` and
    `setting_sources` keys are rebuild-class (capability-matrix C-6: applying
    them forces a Query rebuild), so an in-place option intent must not exist.
    The real vocabulary's only option-shaped intent is `SetField` — which
    targets a structured FILE and is applied by regenerating it, with no
    rebuild-class semantics anywhere in `ordessa_harness_api` — so mapping
    `agents` onto it would silently claim a hot-applyable file field and
    exceed Q3's directory-only claims. Per the task's gap rule this stays a
    refusal with a named gap (SR-3b-2 asks C0 for either a typed rebuild-class
    intent or a proved `settingSources`-read mount root); the mounts Q3 emits
    are path (b)'s input, and whether the private root is read stays unknown
    until wired.
    """
    raise _refuse(
        "rebuild_class_option",
        f"option {option_key!r} is rebuild-class at the pin and the published "
        "harness-api vocabulary has no rebuild-class option intent: emitting "
        "it as SetField would claim an in-place apply, which C-6 disproves; "
        "refused until SR-3b-2 lands (no private side channel)",
    )


def scan_credential_bearing_fields(item: "ManagedItem") -> None:
    """FR05/G09: a definition carrying a credential-shaped key is refused.

    This keeps the existing refusal (a mere declaration is not a host grant —
    never auto-converted into `BindSecret`) and names the credential key,
    reusing the published contract's own classifier
    (`ordessa_harness_api.schema.looks_secret_name`) on top of Q3's
    decoder-side credential grammar.
    """
    revision = item.revision
    for group_name in ("retained_native_fields", "isolation", "limits"):
        group = getattr(revision, group_name, {}) or {}
        if not isinstance(group, Mapping):
            continue
        for key in group:
            if looks_secret_name(str(key)) or decoder.is_credential_named(str(key)):
                raise errors.DomainError(
                    errors.DEFINITION_INVALID, item_id=item.definition.definition_id,
                    detail=(f"field {group_name}.{key} is credential-shaped: a "
                            "definition may not carry or name a credential "
                            "(FR05/G09); credentials reach a generation only "
                            "through a host-granted BindSecret binding, and a "
                            "declaration is not a grant"),
                )


# -- collection model ----------------------------------------------------------


@dataclass(frozen=True)
class ManagedItem:
    """One definition plus the frozen revision whose content is compiled."""

    definition: Any
    revision: Any

    def __post_init__(self) -> None:
        from .. import dto

        if not isinstance(self.definition, dto.AgentDefinition):
            raise TypeError("ManagedItem.definition must be a dto.AgentDefinition")
        if not isinstance(self.revision, dto.DefinitionRevision):
            raise TypeError("ManagedItem.revision must be a dto.DefinitionRevision")

    @property
    def native_name(self) -> str:
        return self.definition.slug


def discovery_diagnostics(native_names: frozenset[str] | None) -> tuple[str, ...]:
    """Compile-time diagnostics, kept OUT of the intent set on purpose.

    The real `IntentSet` carries no diagnostics field (`ordessa_harness_api`
    `intents.py:199-208`), so Q3's 「native discovery unknown」 note is exposed
    through this pure helper for the caller's own record, and the absence of
    a diagnostics channel is registered as a seam observation (SR gap list).
    """
    if native_names is None:
        return (
            "native-discovery=unknown: collision against unmanaged native "
            "definitions could not be checked; reported as Unknown, never as "
            "'absent' (contracts.md §C1 inspectNative -> Unknown)",
        )
    return ()


def compile_all(
    revisions: Sequence[ManagedItem],
    context: Any,
    source: Any,
    *,
    render: Callable[[ManagedItem], str],
    suffix: str = ".md",
    directory: str = MOUNT_DIRECTORY,
    native_names: frozenset[str] | None = None,
    stage_content: Callable[[str, bytes], None] | None = None,
    secret_bindings: Sequence[tuple[str, str]] = (),
) -> IntentSet:
    """Compile the *complete* managed collection into a REAL `IntentSet`.

    Targets and ownership are injected, never invented: `context` is the
    host-granted :class:`ordessa_harness_api.AdapterContext` (the mount
    targets are the server-issued `TargetHandle`s inside it) and `source` is
    the host-injected :class:`IntentSource` stamped unchanged on every
    intent. Every shared guard — context/source admission, caps, name
    grammar, credential scan, compilability (a revision carrying
    `retained_native_fields` is NEVER silently dropped), digest stamping and
    name collision — runs before the first intent object exists.

    `stage_content` is the host's content-staging sink: C0 resolves a
    `ContentRef.reference` out of the runtime snapshot's `content` map
    (`private_generation.py:271`), but the published `ConfigurationAdapter`
    protocol has no port for the adapter to hand over document bytes — that
    missing staging port is a reported gap; Q3 only ever calls the injected
    sink and never stores content in an intent.
    """
    checked_context = validate_context(context)
    checked_source = validate_source(source)
    target = select_content_target(checked_context, harness_id=checked_context.installation.harness_id)
    if isinstance(revisions, (ManagedItem, str, bytes)) or not isinstance(revisions, Sequence):
        raise errors.DomainError(
            errors.DEFINITION_INVALID, detail="revisions must be a sequence of ManagedItem",
        )
    items = tuple(revisions)
    if len(items) > limits.MAX_ENABLED_DEFINITIONS:
        raise errors.DomainError(
            errors.DEFINITION_INVALID,
            detail=f"collection exceeds MAX_ENABLED_DEFINITIONS={limits.MAX_ENABLED_DEFINITIONS}",
        )

    descriptions = sum(len(i.definition.description.encode("utf-8")) for i in items
                       if isinstance(i, ManagedItem))
    if descriptions > limits.MAX_AGGREGATE_DESCRIPTION_BYTES:
        raise errors.DomainError(
            errors.DEFINITION_INVALID,
            detail="aggregate description exceeds MAX_AGGREGATE_DESCRIPTION_BYTES",
        )

    prepared: dict[str, str] = {}
    for item in items:
        if not isinstance(item, ManagedItem):
            raise errors.DomainError(
                errors.DEFINITION_INVALID, detail="every collection entry must be a ManagedItem",
            )
        name = _check_token(item.native_name, what="native_name", pattern=NATIVE_NAME_RE)
        item_id = item.definition.definition_id
        if not digest.is_digest(item.revision.content_digest):
            raise errors.DomainError(
                errors.DEFINITION_INVALID, item_id=item_id,
                detail="revision.content_digest must be a `sha256:<64hex>` digest",
            )
        scan_credential_bearing_fields(item)
        if not decoder.is_compilable(item.revision):
            if item.revision.retained_native_fields:
                retained = ", ".join(sorted(item.revision.retained_native_fields))
                raise errors.DomainError(
                    errors.DEFINITION_INVALID, item_id=item_id,
                    detail=(f"revision retains unmapped native field(s) [{retained}] and is "
                            "NOT compilable; retained fields are refused, never dropped"),
                )
            raise errors.DomainError(
                errors.DEFINITION_INVALID, item_id=item_id,
                detail="revision has no source approval and is not compilable",
            )
        body_bytes = len(item.revision.role_body.encode("utf-8"))
        if body_bytes > limits.MAX_ROLE_BODY_BYTES:
            raise errors.DomainError(
                errors.DEFINITION_INVALID, item_id=item_id,
                detail="role_body exceeds MAX_ROLE_BODY_BYTES",
            )
        if not item.definition.description:
            raise errors.DomainError(
                errors.DEFINITION_INVALID, item_id=item_id,
                detail="description is required: it reaches the native agent catalog",
            )
        if name in prepared:
            raise errors.DomainError(
                errors.NATIVE_NAME_CONFLICT, item_id=name,
                detail="two managed definitions compile to the same native name",
            )
        if native_names is not None and name in native_names:
            raise errors.DomainError(
                errors.NATIVE_NAME_CONFLICT, item_id=name,
                detail="collides with a natively discovered definition of the same name "
                       "(G13: diagnosed before apply, never last-wins)",
            )
        content = render(item)
        if not isinstance(content, str):
            raise errors.DomainError(
                errors.DEFINITION_INVALID, item_id=item_id,
                detail="the brand document builder must return a str",
            )
        prepared[name] = content

    mounts: list[MountContent] = []
    for name in sorted(prepared):
        mount = build_mount(checked_source, target, native_name=name,
                            content=prepared[name], suffix=suffix,
                            directory=directory)
        if stage_content is not None:
            stage_content(mount.immutable_content_ref.reference,
                          prepared[name].encode("utf-8"))
        mounts.append(mount)

    emitted: list[Any] = list(mounts)
    if secret_bindings:
        env_target = select_environment_target(checked_context)
        for slot, secret_ref in secret_bindings:
            emitted.append(build_secret_binding(checked_source, env_target,
                                                slot=slot, secret_ref=secret_ref))
    # The real IntentSet re-validates membership (`intents.py:199-208`):
    # anything that is not one of the six contract intents is a
    # construction error — Q3's deleted vocabulary cannot re-enter here.
    return IntentSet(tuple(emitted))
