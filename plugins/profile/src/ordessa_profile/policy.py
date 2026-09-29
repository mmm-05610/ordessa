"""Mechanism policy: configuration-surface rules per server realm (US1).

This service owns *which facets are enabled* and *whether users may write
session overrides*.  It never grants execution permission, never deletes
stored data, and never bypasses Harness/runtime authorization (G03/G04).
"""
from __future__ import annotations

import sqlite3
from typing import Any, Mapping

from . import repository as repo
from .contracts import MechanismPolicy
from .errors import ProfileError
from .sensitive import digest, json_dumps, json_loads


class PolicyService:
    def __init__(self, core) -> None:
        self.core = core

    # -- reads ---------------------------------------------------------
    def get(self, conn: sqlite3.Connection, realm: str) -> MechanismPolicy:
        row = conn.execute(
            "SELECT realm, revision, facet_enabled_json, allow_override_global,"
            " allow_per_facet_json FROM profile_mechanism_policy WHERE realm=?",
            (realm,),
        ).fetchone()
        if row is None:
            # Defaults keep existing behaviour: registered facets enabled,
            # user override writes allowed (data-model.md §5).
            return MechanismPolicy(
                realm=realm, revision=1, facet_enabled={},
                allow_user_override_writes_global=True,
                allow_user_override_writes={},
            )
        return MechanismPolicy(
            realm=row["realm"], revision=int(row["revision"]),
            facet_enabled=json_loads(row["facet_enabled_json"]),
            allow_user_override_writes_global=bool(row["allow_override_global"]),
            allow_user_override_writes=json_loads(row["allow_per_facet_json"]),
        )

    def get_public(self, realm: str) -> dict[str, Any]:
        with self.core.db.read() as conn:
            return self._public(self.get(conn, realm))

    def _public(self, policy: MechanismPolicy) -> dict[str, Any]:
        return {
            "realm": policy.realm,
            "revision": policy.revision,
            "facet_enabled": dict(policy.facet_enabled),
            "allow_user_override_writes_global":
                policy.allow_user_override_writes_global,
            "allow_user_override_writes": dict(policy.allow_user_override_writes),
        }

    # -- impact preview (PS05) ----------------------------------------
    def impact_preview(self, conn: sqlite3.Connection, realm: str,
                       disabling: tuple[str, ...]) -> dict[str, Any]:
        """Counts of profiles/sessions that keep data for facets about to be
        disabled.  Disabling hides the edit surface and may block a next
        turn; it never deletes anything."""
        per_facet: dict[str, dict[str, int]] = {}
        for facet_id in disabling:
            profile_rows = conn.execute(
                "SELECT COUNT(DISTINCT fv.profile_id) AS n FROM"
                " profile_facet_values fv JOIN profile_profiles p"
                " ON p.profile_id = fv.profile_id"
                " WHERE fv.facet_id=? AND p.realm=?",
                (facet_id, realm),
            ).fetchone()
            session_rows = conn.execute(
                "SELECT COUNT(DISTINCT s.session_uid) AS n FROM"
                " profile_session_overlays o JOIN profile_sessions s"
                " ON s.session_id = o.session_id WHERE o.facet_id=? AND s.realm=?",
                (facet_id, realm),
            ).fetchone()
            per_facet[facet_id] = {
                "profiles_with_values": int(profile_rows["n"]),
                "sessions_with_overlays": int(session_rows["n"]),
            }
        return {"disabling": per_facet}

    # -- CAS update ----------------------------------------------------
    def update(self, key: str, *, realm: str, expected_revision: int,
               patch: Mapping[str, Any], caller: str,
               preview: bool = False) -> dict[str, Any]:
        """CAS policy update.  ``patch`` keys:
        facet_enabled (map), allow_user_override_writes_global (bool),
        allow_user_override_writes (map).

        ``preview=True`` computes the same response (including the impact
        counts) without mutating anything and without consuming the
        idempotency key — the PS05 "show the impact before disabling" step.
        """
        if not isinstance(caller, str) or not caller:
            raise ProfileError(
                "PROFILE_VALUE_INVALID", "policy update requires a caller",
                status=422,
            )
        request = {
            "realm": realm, "expected_revision": expected_revision,
            "patch": _canonical_patch(patch), "caller": caller,
            "preview": preview,
        }
        if preview:
            # Dry run: no write, no idempotency consumption, revision unchanged.
            with self.core.db.read() as conn:
                current = self.get(conn, realm)
                if current.revision != expected_revision:
                    raise ProfileError(
                        "POLICY_REVISION_CONFLICT",
                        "Mechanism policy changed before the update",
                        status=409,
                    ).with_current(self._public(current))
                planned, disabling = self._plan_patch(conn, current, patch)
                return {
                    "policy": self._public(planned),
                    "impact": self.impact_preview(conn, realm, disabling),
                    "preview": True,
                }
        with self.core.db.transaction() as conn:
            prior = repo.idempotency_check(
                conn, f"policy.update:{realm}", key, digest(request))
            if prior:
                return prior["response"]
            current = self.get(conn, realm)
            if current.revision != expected_revision:
                raise ProfileError(
                    "POLICY_REVISION_CONFLICT",
                    "Mechanism policy changed before the update",
                    status=409,
                ).with_current(self._public(current))
            updated, disabling = self._plan_patch(conn, current, patch)
            new_facet_enabled = dict(updated.facet_enabled)
            new_allow_per_facet = dict(updated.allow_user_override_writes)
            new_global = updated.allow_user_override_writes_global
            updated = MechanismPolicy(
                realm=realm, revision=current.revision + 1,
                facet_enabled=new_facet_enabled,
                allow_user_override_writes_global=new_global,
                allow_user_override_writes=new_allow_per_facet,
            )
            timestamp = self.core.timestamp()
            conn.execute(
                "INSERT INTO profile_mechanism_policy(realm, revision,"
                " facet_enabled_json, allow_override_global,"
                " allow_per_facet_json, updated_at) VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(realm) DO UPDATE SET revision=excluded.revision,"
                " facet_enabled_json=excluded.facet_enabled_json,"
                " allow_override_global=excluded.allow_override_global,"
                " allow_per_facet_json=excluded.allow_per_facet_json,"
                " updated_at=excluded.updated_at",
                (
                    realm, updated.revision,
                    json_dumps(dict(updated.facet_enabled)),
                    1 if updated.allow_user_override_writes_global else 0,
                    json_dumps(dict(updated.allow_user_override_writes)),
                    timestamp,
                ),
            )
            response = {
                "policy": self._public(updated),
                "impact": self.impact_preview(conn, realm, disabling),
            }
            repo.idempotency_insert(
                conn, f"policy.update:{realm}", key, digest(request), 200,
                response, timestamp,
            )
            return response


    def _plan_patch(self, conn, current: MechanismPolicy,
                    patch: Mapping[str, Any]):
        """Validate a patch against ``current`` and return the planned policy
        plus the facets it would disable.  Pure computation, no writes."""
        new_facet_enabled = dict(current.facet_enabled)
        new_allow_per_facet = dict(current.allow_user_override_writes)
        new_global = current.allow_user_override_writes_global
        disabling: tuple[str, ...] = ()
        for field_name, value in patch.items():
            if field_name == "facet_enabled":
                if not isinstance(value, Mapping):
                    raise ProfileError(
                        "PROFILE_VALUE_INVALID",
                        "facet_enabled patch must be an object", status=422,
                    )
                for facet_id, enabled in value.items():
                    if not isinstance(enabled, bool):
                        raise ProfileError(
                            "PROFILE_VALUE_INVALID",
                            f"facet_enabled[{facet_id!r}] must be boolean",
                            status=422,
                        )
                    was_enabled = current.facet_enabled_for(facet_id)
                    new_facet_enabled[facet_id] = enabled
                    if was_enabled and not enabled:
                        disabling = (*disabling, facet_id)
            elif field_name == "allow_user_override_writes_global":
                if not isinstance(value, bool):
                    raise ProfileError(
                        "PROFILE_VALUE_INVALID",
                        "allow_user_override_writes_global must be boolean",
                        status=422,
                    )
                new_global = value
            elif field_name == "allow_user_override_writes":
                if not isinstance(value, Mapping):
                    raise ProfileError(
                        "PROFILE_VALUE_INVALID",
                        "allow_user_override_writes patch must be an object",
                        status=422,
                    )
                for facet_id, allowed in value.items():
                    if not isinstance(allowed, bool):
                        raise ProfileError(
                            "PROFILE_VALUE_INVALID",
                            f"allow_user_override_writes[{facet_id!r}]"
                            " must be boolean", status=422,
                        )
                new_allow_per_facet[facet_id] = allowed
            else:
                raise ProfileError(
                    "PROFILE_VALUE_INVALID",
                    f"unknown policy patch field {field_name!r}",
                    status=422,
                )
        planned = MechanismPolicy(
            realm=current.realm, revision=current.revision,
            facet_enabled=new_facet_enabled,
            allow_user_override_writes_global=new_global,
            allow_user_override_writes=new_allow_per_facet,
        )
        return planned, disabling


def _canonical_patch(patch: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(patch, Mapping):
        raise ProfileError(
            "PROFILE_VALUE_INVALID", "policy patch must be an object",
            status=422,
        )
    return {str(k): patch[k] for k in sorted(patch)}
