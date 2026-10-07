"""Migration engines for the Skills domain (tasks.md T07).

`profile_bindings` implements the dry-run-first migration of the legacy
`server_profile_assets` skill bindings into the assignments domain tables
(additive/parallel until Z1 publishes the real `assets.skills` facet —
specs/011-q1-skills/api-requests.md §G3), with plan/apply/verify/rollback
and the user-data confirmation guard. This package migrates `skill` rows
only; every other asset kind stays with its old business owner
(plan.md 原有 Assets-Skill 迁移) and is proven untouched by the G08/G09
test pair.
"""
from .profile_bindings import (
    CLASSIFY_MIGRATE,
    DEFAULT_SERVER_SCOPE,
    MigrationEntry,
    MigrationError,
    MigrationPlan,
    REFUSE_NO_GATE,
    REFUSE_PROFILE_UNKNOWN,
    REFUSE_UNAPPROVED,
    SKIP_ALREADY_MIGRATED,
    SKIP_FOREIGN_KIND,
    apply,
    plan,
    profile_principal,
    profile_skill_entries,
    rollback,
    verify,
)

__all__ = [
    "CLASSIFY_MIGRATE", "DEFAULT_SERVER_SCOPE", "MigrationEntry",
    "MigrationError", "MigrationPlan", "REFUSE_NO_GATE",
    "REFUSE_PROFILE_UNKNOWN", "REFUSE_UNAPPROVED",
    "SKIP_ALREADY_MIGRATED", "SKIP_FOREIGN_KIND", "apply", "plan",
    "profile_principal", "profile_skill_entries", "rollback", "verify",
]
