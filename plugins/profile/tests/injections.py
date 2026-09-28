"""Counterexample injections (constitution IV evidence).

Each named injection deliberately breaks exactly one load-bearing behaviour
of the installed ``ordessa_profile`` modules. The runner
``run_counterexamples.sh`` executes each gate under its injection and expects
the gate to FAIL — proving every gate can discriminate. Never set
``PROFILE_COUNTEREXAMPLE`` for normal runs.
"""
from __future__ import annotations

import os


def apply_counterexample() -> None:
    name = os.environ.get("PROFILE_COUNTEREXAMPLE")
    if not name:
        return

    from ordessa_profile import repository as repo
    from ordessa_profile import resolution, sensitive
    from ordessa_profile import sessions as sessions_mod
    from ordessa_profile.core import ProfileCore
    from ordessa_profile.facets import FacetRegistry, validate_provider_shape
    from ordessa_profile.migration import import_legacy as orig_import
    from ordessa_profile.profiles import ProfileService

    if name == "version_ignored":
        # FR-002: stale expected_version is silently accepted.
        def no_version_check(self, conn, *, profile_id, expected_version,
                             assignments, bump_revision_to=None):
            self.core.require_profile(conn, profile_id)
            sets = [f"{n}=?" for n in assignments]
            values = list(assignments.values())
            sets.append("version=version+1")
            sets.append("updated_at=?")
            params = (*values, self.core.timestamp(), profile_id)
            if bump_revision_to is not None:
                sets.append("current_revision=?")
                params = (*values, self.core.timestamp(), bump_revision_to,
                          profile_id)
            conn.execute(
                f"UPDATE profile_profiles SET {', '.join(sets)} "
                f"WHERE profile_id=?", params)
            return self.core.require_profile(conn, profile_id)
        ProfileService._mutate = no_version_check

    elif name == "idempotency_off":
        # FR-002: repeated requests re-mutate.
        repo.idempotency_check = lambda *a, **k: None

    elif name == "facet_last_wins":
        # US4.3: duplicate facet declarations overwrite instead of conflict.
        def last_wins(self, provider):
            validate_provider_shape(provider)
            self._providers[provider.facet_id] = provider
        FacetRegistry.register = last_wins

        def register_core(self, provider):
            validate_provider_shape(provider)
            existing = self.registry.get(provider.facet_id)
            self.registry.register(provider)
            if existing is provider:
                return None
            return self.reload_provider(provider)
        ProfileCore.register_provider = register_core

    elif name == "unload_deletes":
        # FR-005/SC-004: unloading a provider deletes its stored values.
        def deleting_unload(self, provider):
            self.registry.unregister(provider)
            with self.db.transaction() as conn:
                conn.execute(
                    "DELETE FROM profile_facet_values WHERE facet_id=?",
                    (provider.facet_id,))
        ProfileCore.unregister_provider = deleting_unload

    elif name == "required_defaults":
        # US4.6: a required-but-absent item is silently skipped.
        sessions_mod.check_required = lambda resolution, required: None

    elif name == "overlay_masks_facet":
        # FR-017/US3.6: an overlay masks its whole facet, not just its item.
        original = sessions_mod.resolve_session_items

        def coarse_mask(conn, **kw):
            result = original(conn, **kw)
            overlays = repo.session_overlays(conn, kw["session_id"])
            facets = {r["facet_id"] for r in overlays}
            overlay_items = {(r["facet_id"], r["item_id"]) for r in overlays}
            result.items = [
                i for i in result.items
                if i["facet_id"] not in facets
                or (i["facet_id"], i["item_id"]) in overlay_items
            ]
            return result
        sessions_mod.resolve_session_items = coarse_mask

    elif name == "overlay_writes_profile":
        # FR-016/D-001: session overlays write back into the Profile.
        def writes_profile(conn, *, session_id, facet_id, item_id, value_json,
                           facet_version, timestamp):
            row = conn.execute(
                "SELECT profile_id, current_revision FROM profile_sessions "
                "WHERE session_id=?", (session_id,)).fetchone()
            repo.upsert_facet_value(
                conn, profile_id=row["profile_id"],
                config_revision=int(row["current_revision"]),
                facet_id=facet_id, item_id=item_id, value_json=value_json,
                facet_version=facet_version, timestamp=timestamp)
        repo.upsert_overlay = writes_profile

    elif name == "partial_apply":
        # FR-008/FR-022: the switch stops clearing the overlay layer.
        repo.clear_overlays = lambda conn, session_id: None

    elif name == "assume_switched":
        # FR-010/US2.4 (v2): unknown port outcomes are treated as confirmed —
        # success is assumed without proof.
        real = sessions_mod.SessionService._handle_apply_outcome

        def patched(self, *args, outcome=None, **kwargs):
            receipt = getattr(outcome, "receipt", None)
            if receipt is None:
                from ordessa_profile.contracts import AppliedReceipt
                receipt = AppliedReceipt(
                    operation_id=kwargs.get("operation_id", "assumed"),
                    session_ref=kwargs["session_ref"],
                    runtime_generation="assumed",
                    config_digest="sha256:assumed",
                    profile_id="assumed", profile_revision=1,
                    overlay_revision=None, policy_revision=1,
                    provider_generations={}, evidence_kind="assumed",
                    confirmed_at=self.core.timestamp())
            return real(self, *args, outcome=sessions_mod.ApplyConfirmed(
                state="confirmed", receipt=receipt), **kwargs)

        sessions_mod.SessionService._handle_apply_outcome = patched

    elif name == "select_any_target":
        # FR-006/US2.5: cross-Harness and archived selections are accepted.
        def accept_any(self, conn, session, profile_id):
            return self.core.require_profile(conn, profile_id)
        sessions_mod.SessionService._validate_target = accept_any

    elif name == "secrets_allowed":
        # FR-011: secret-carrying keys are stored verbatim.
        sensitive.reject_sensitive_keys = lambda value: None
        sessions_mod.reject_sensitive_keys = lambda value: None
        import ordessa_profile.profiles as profiles_mod
        profiles_mod.reject_sensitive_keys = lambda value: None
        resolution.reject_sensitive_keys = lambda value: None

    elif name == "migration_lossy":
        # spec §现有行为保留: imported revisions collapse to 1.
        orig_insert = repo.insert_revision

        def clamped_insert(conn, *, profile_id, config_revision, created_at):
            orig_insert(conn, profile_id=profile_id, config_revision=1,
                        created_at=created_at)
        repo.insert_revision = clamped_insert

        def lossy(source_db_path, *, target):
            try:
                return orig_import(source_db_path, target=target)
            finally:
                repo.insert_revision = orig_insert
        import ordessa_profile.migration as migration
        migration.import_legacy = lossy

    else:  # pragma: no cover
        raise RuntimeError(f"unknown counterexample injection: {name}")
