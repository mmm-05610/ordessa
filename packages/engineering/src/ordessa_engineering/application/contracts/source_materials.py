"""Demand-side inputs for the original external Change/Review/Package owners.

These ports do not publish methods, authenticate reviewers, issue grants or
create an external artifact registry. Missing implementations refuse writes.
Source-only fixtures may implement them for controlled mechanism checks; they
are not production method publication or reviewer authority.
"""
from typing import ContextManager, Protocol

from .commands import CommandContext
from .transactions import UoWFactory
from ...domain.artifacts.provenance import SourceRef
from ...domain.artifacts.method_binding import MethodRef, ExactMethodResourceRef
from ...methods.definitions.models import MethodDefinition


class SourceMaterialPort(Protocol):
    factory: UoWFactory

    def read(self, context: CommandContext, ref: SourceRef) -> bytes:
        """Authorize this exact locator/version in context.scope and read bounded bytes.

        No directory/Git scan or latest-version substitution. The consumer also
        verifies the captured digest and length. Availability is separate from
        permission; a locator, actor DTO or digest grants neither.
        """
        ...


class MethodDeclarationGuard(Protocol):
    factory: UoWFactory

    def guard(self, context: CommandContext, method_ref: MethodRef) -> ContextManager[MethodDefinition]:
        """Resolve the exact admitted declaration and hold its control until COMMIT.

        Production implements the original publication/control checks. An
        unpublished candidate is not admitted by merely finding its directory.
        Schema-2 declarations never fall back to a compiled workflow.
        """
        ...

    def read_resource(self, context: CommandContext, ref: ExactMethodResourceRef) -> bytes:
        """Read exact immutable resource bytes under the active method guard.

        Match path/id/digest and method pin; never retrieve remote schema refs
        or infer policy by parsing natural-language criteria in the core.
        """
        ...

    def resource_ref(self, context: CommandContext, method_ref: MethodRef,
                     resource_id: str) -> ExactMethodResourceRef:
        """Resolve a declared ID under the exact active publication guard.

        Callers do not infer stored paths or inspect snapshot internals.
        """
        ...

    def preparation_roles(self, context: CommandContext, definition: MethodDefinition,
                          resource_refs: tuple[ExactMethodResourceRef, ...]) -> tuple[str, ...]:
        """Select the exact finite document roles required by this frozen method.

        Called under the same declaration/control guard. Core checks the role
        set and exact submitted references; it does not invent spec-kit policy,
        scan templates, or interpret natural-language criteria. Missing method
        policy refuses preparation.
        """
        ...
