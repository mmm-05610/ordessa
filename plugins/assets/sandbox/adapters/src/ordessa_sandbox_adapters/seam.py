"""The adapter-side compiled output and the BOUND Harness C3 seam.

Status after the `harness-api` checkpoint (record
``specs/011-plugin-rollout/checkpoints/harness-api.json``, implementation
``61966e3118``, ref ``refs/heads/codex/011-harness-api-ready``, merged into this
lane as ``d3f026904e``): ``plugins/harness/api`` (``ordessa_harness_api``,
py.typed, standalone wheel) IS a published ``publicExports`` entry of that
READY record, and ``publicExports.harnessApiExports`` names every C3 apply
symbol this seam binds — ``SetField``, ``ResetField``, ``InvokeAction``,
``IntentSet``, ``IntentSource``, ``TargetHandle``, ``FieldPath``, plus
``BindSecret``, ``MountContent``, ``ContentRef`` and ``RemoveOwnedContent``.
``tests/test_c3_seam.py`` re-checks the record and the symbol set on every run
and fails if the record is missing or not READY: the binding below is
checkpoint-backed, not merely importable.

What the binding does:

* ``CompiledFieldIntent.to_harness_c3()`` returns the platform's own intent
  object — a real ``ordessa_harness_api.intents.SetField`` / ``ResetField`` /
  ``InvokeAction`` — attributed with a real ``IntentSource(facet_id, item_id,
  contribution_version)`` over the ``TargetHandle`` the host issued, and
  ``CompiledIntent.to_harness_c3()`` assembles them into a real ``IntentSet``.
* the guards are the platform's. ``FieldPath`` refuses ``.``, ``..`` and any
  separator-bearing segment and ``SetField`` refuses a secret-bearing field name
  ("secret-bearing field must use BindSecret"); both raise the platform's
  ``ContractError`` and this package keeps no parallel guard that could drift
  from them (``tests/test_c3_platform_guards.py``).

What is still NOT claimed: producing an intent is not applying it. The strongest
write proof this tree backs is the controlled C4 service fixture (L2, named in
``matrix.py``); the record's own limitations keep instance generation and an
operation-bound native receipt absent, so every production effect statement
stays ``Unknown``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Union

from ordessa_harness_api.intents import (
    FieldPath,
    IntentSet,
    IntentSource,
    InvokeAction,
    ResetField,
    SetField,
    TargetHandle,
)
from ordessa_sandbox_api import NativeSandboxIntent

from .points import SANDBOX_FACET_ID, SANDBOX_FACET_SCHEMA_VERSION

__all__ = ["CompiledFieldIntent", "HARNESS_C3_APPLY_INTENTS",
           "HARNESS_C3_INTENT_KINDS", "KIND_INVOKE_ACTION", "KIND_RESET_FIELD",
           "KIND_SET_FIELD", "UnsupportedCompiledKind",
           "sandbox_contribution_version", "sandbox_item_id"]

#: The C3 apply intents §C2 allows this facet to emit: the *sealed*
#: ``SetField/ResetField/InvokeAction`` set. A shell command, a raw path write or
#: a free-form JSON patch has no representation here at all, and
#: ``MountContent``/``RemoveOwnedContent``/``BindSecret`` stay unused by this
#: facet because the sandbox config facet owns no content and no secret.
HARNESS_C3_APPLY_INTENTS = (SetField, ResetField, InvokeAction)


class UnsupportedCompiledKind(ValueError):
    """Asking this seam to bind a kind it does not implement.

    A programming refusal, never a stand-in for an apply: it cannot be reached
    with a kind drawn from the platform vocabulary.
    """


def _kind_literal(cls: type) -> str:
    """The platform's own ``kind`` literal, read off the published class."""
    default = cls.__dataclass_fields__["kind"].default
    if not isinstance(default, str) or not default:
        raise RuntimeError(f"{cls.__name__} exposes no platform kind literal")
    return default


#: {"set-field", "reset-field", "invoke-action"} — derived from the platform
#: classes, so this package never keeps a second spelling that can drift.
HARNESS_C3_INTENT_KINDS = frozenset(
    _kind_literal(cls) for cls in HARNESS_C3_APPLY_INTENTS)

KIND_SET_FIELD = _kind_literal(SetField)
KIND_RESET_FIELD = _kind_literal(ResetField)
KIND_INVOKE_ACTION = _kind_literal(InvokeAction)


def sandbox_contribution_version() -> str:
    """The ``contribution_version`` an IntentSource of this facet carries."""
    return SANDBOX_FACET_SCHEMA_VERSION


def sandbox_item_id(harness_id: str) -> str:
    """The facet item id one brand's intents are attributed to.

    The platform requires ``IntentSource.item_id`` to equal the applied
    ``DesiredFragment.item_id`` and the ``compile`` hook never receives the
    fragment, so this facet publishes one deterministic item per harness; a
    caller builds its fragment with the same value.
    """
    return f"{SANDBOX_FACET_ID}.{harness_id}"


@dataclass(frozen=True)
class CompiledFieldIntent:
    """One adapter-emitted native-config field, plus the intent it came from.

    This is the *pre-binding* record of the business decision (which field,
    which value, which kind, on which server-issued target, from which business
    intent); :meth:`to_harness_c3` turns it into the platform's intent. It
    carries no shell or path-write capability.
    """

    field_path_segments: tuple[str, ...]
    value: Any
    kind: str
    intent: NativeSandboxIntent
    target: TargetHandle
    item_id: Optional[str] = None
    baseline_rule: Optional[str] = None
    expected_observation: Optional[str] = None

    def __post_init__(self) -> None:
        # shape gates this record needs for itself ONLY. Deliberately not a
        # path/secret guard: FieldPath and SetField refuse those in the
        # platform, and their ContractError must reach the caller untouched.
        if isinstance(self.field_path_segments, str) or \
                not isinstance(self.field_path_segments, tuple):
            raise ValueError("field_path_segments must be a tuple of segments")
        segments = tuple(self.field_path_segments)
        if not segments or any(not isinstance(seg, str) or not seg.strip()
                               for seg in segments):
            raise ValueError("field_path_segments must be non-empty text segments")
        object.__setattr__(self, "field_path_segments", segments)
        if self.kind not in HARNESS_C3_INTENT_KINDS:
            raise ValueError(
                f"kind {self.kind!r} is not one of the Harness C3 intent kinds "
                f"{sorted(HARNESS_C3_INTENT_KINDS)}")
        if not isinstance(self.intent, NativeSandboxIntent):
            raise ValueError("a compiled field must carry its source intent")
        # `TargetHandle` is the server-issued opaque handle from the
        # AdapterContext; a bare string is not a handle and no generation is
        # ever invented in this package.
        if not isinstance(self.target, TargetHandle):
            raise ValueError("a compiled field must carry the server-issued "
                             "TargetHandle it was compiled against")
        if self.item_id is None:
            object.__setattr__(self, "item_id",
                               sandbox_item_id(self.intent.harness_id))

    @property
    def field_path(self) -> str:
        return ".".join(self.field_path_segments)

    @property
    def source(self) -> IntentSource:
        """The platform attribution of this field: facet, item, version."""
        return IntentSource(SANDBOX_FACET_ID, self.item_id,
                            sandbox_contribution_version())

    def to_harness_c3(self) -> Union[SetField, ResetField, InvokeAction]:
        """Build the real ``ordessa_harness_api`` intent for this field.

        Malformed shape against the platform contract — a path-flavoured
        segment, a secret-bearing field name, a missing or unknown baseline
        rule, an action without a declared expected observation — raises the
        platform's own ``ContractError``. This seam adds no guard of its own and
        never returns a stand-in.
        """
        source = self.source
        handle = self.target
        # FieldPath validates its own segments; passing them straight through
        # is the point — the platform is the path authority.
        field_path = FieldPath(self.field_path_segments)
        if self.kind == KIND_SET_FIELD:
            return SetField(source, handle, field_path, self.value)
        if self.kind == KIND_RESET_FIELD:
            # `baseline_rule` is checked by the platform DTO, not re-checked here
            return ResetField(source, handle, field_path, self.baseline_rule)
        if self.kind == KIND_INVOKE_ACTION:
            return InvokeAction(source, self.field_path,
                                sandbox_contribution_version(), self.value,
                                self.expected_observation)
        raise UnsupportedCompiledKind(
            f"{self.kind!r} binds to no Harness C3 apply intent; refusing to "
            "invent one")

    def to_harness_c3_set(self) -> IntentSet:
        """This single field as the platform's sealed intent set."""
        return IntentSet((self.to_harness_c3(),))
