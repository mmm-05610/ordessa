"""Narrow port for the declared generation step's native work.

The declared `prepare-spec-kit-package` step consumes qualified inputs plus the
released templates and *produces* a package; the native work runs on the
composition's existing Unit transport (freeze_input/send/capture, effect
handoff, records), never on the implementation dispatch line, which forbids
`generate_package` by design. The port is supplied by the composition; this
application layer only calls it.
"""

from typing import Protocol, runtime_checkable

REQUIRED_MATERIALS = ("criteria", "prompt", "spec-template", "plan-template",
                      "tasks-template", "baseline-template", "acceptance-template",
                      "change-map-template", "package-schema")
"""Exactly the resources the released `draft` step declares as its inputs."""

QUALIFIED_INPUTS = ("baseline", "candidate", "scope", "review", "method")
"""Exactly the qualified inputs the `qualify` step hands to `draft`."""


@runtime_checkable
class DeclaredGenerationPort(Protocol):
    """Generate from admitted Work inputs on the selected original Unit.

    The native ACP result contains one JSON object in its verified text output:
    package_id, the published prepared-package payload, and document_contents
    for spec/plan/tasks. Content hashes must match the payload's source captures;
    the host attributes the resulting record to the admitted context.
    """

    def __call__(self, context, binding, qualified_inputs: dict,
                 materials: dict, *, action_id: str, step_id: str,
                 profile_ref: object) -> dict: ...


__all__ = ["DeclaredGenerationPort", "REQUIRED_MATERIALS", "QUALIFIED_INPUTS"]
