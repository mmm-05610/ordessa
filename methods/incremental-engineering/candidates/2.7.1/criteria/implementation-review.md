# Implementation and independent review criteria

An implementation report identifies the exact package and caller-supplied profile reference, changed paths, verification evidence, and unresolved results. A separate reviewer evaluates the report against the package acceptance criteria and returns an explicit review result. These are human-readable criteria, not machine-interpreted rules.

For one operation, a passed independent review closes the operation. A rejected review may produce one explicit rework request and a new implementation report for a further independent review. Cancellation closes as cancelled. Missing, malformed, or indeterminate review evidence closes as unknown; unknown is never silently retried or promoted to passed. This declaration does not impose a project-wide phase or create an execution loop.
