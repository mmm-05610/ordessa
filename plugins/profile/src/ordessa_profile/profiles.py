"""Profile management use cases (US1 + facet-value storage, contracts/core-api.md)."""
from __future__ import annotations

import sqlite3
import unicodedata
from typing import Any, Sequence

from . import repository as repo
from .errors import ProfileError
from .resolution import resolve_profile_items
from .sensitive import digest, json_dumps, json_loads, reject_sensitive_keys


def normalize_display_name(name: str) -> str:
    """PM03: Unicode NFC + trim + casefold comparison key for names."""
    return unicodedata.normalize("NFC", name).strip().casefold()


def profile_view(row: dict[str, Any]) -> dict[str, Any]:
    """Non-secret identity projection; deliberately carries no credential,
    permission or facet-business fields (FR-001/FR-011/FR-014)."""
    return {
        "profile_id": row["profile_id"],
        "version": int(row["version"]),
        "display_name": row["display_name"],
        "harness_id": row["harness_id"],
        "current_revision": int(row["current_revision"]),
        "archived_at": row["archived_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "realm": row["realm"] if "realm" in row.keys() else "local",
    }


class ProfileService:
    def __init__(self, core) -> None:
        self.core = core

    # -- helpers -----------------------------------------------------
    def _idempotent(
        self, conn: sqlite3.Connection, scope: str, key: str,
        request: dict[str, Any],
    ) -> dict[str, Any] | None:
        return repo.idempotency_check(conn, scope, key, digest(request))

    def _mutate(
        self, conn: sqlite3.Connection, *, profile_id: str,
        expected_version: int, assignments: dict[str, Any],
        bump_revision_to: int | None = None,
    ) -> dict[str, Any]:
        row = self.core.require_profile(conn, profile_id)
        if int(row["version"]) != expected_version:
            raise ProfileError(
                "PROFILE_VERSION_CONFLICT",
                "Profile changed before the update",
                status=409,
            ).with_current(profile_view(row))
        sets = [f"{name}=?" for name in assignments]
        values = list(assignments.values())
        sets.append("version=version+1")
        sets.append("updated_at=?")
        params = (*values, self.core.timestamp(), profile_id)
        if bump_revision_to is not None:
            sets.append("current_revision=?")
            params = (*values, self.core.timestamp(), bump_revision_to, profile_id)
        conn.execute(
            f"UPDATE profile_profiles SET {', '.join(sets)} WHERE profile_id=?",
            params,
        )
        return self.core.require_profile(conn, profile_id)

    # -- US1 ---------------------------------------------------------
    def create(self, key: str, *, harness_id: str, display_name: str,
               realm: str = "local") -> dict[str, Any]:
        if not isinstance(display_name, str) or not display_name.strip():
            raise ProfileError(
                "PROFILE_VALUE_INVALID", "display_name must be a non-empty string",
                status=422,
            )
        if not self.core.harnesses.exists(harness_id):
            raise ProfileError(
                "HARNESS_UNKNOWN", "Requested Harness is not configured", status=404,
            )
        request = {"harness_id": harness_id, "display_name": display_name,
                   "realm": realm}
        with self.core.db.transaction() as conn:
            prior = self._idempotent(conn, "profiles.create", key, request)
            if prior:
                return prior["response"]
            self._require_free_name(conn, realm=realm, harness_id=harness_id,
                                    display_name=display_name)
            profile_id = self.core.mint_id("profile")
            timestamp = self.core.timestamp()
            repo.insert_profile(
                conn, profile_id=profile_id, version=1,
                display_name=display_name, harness_id=harness_id, revision=1,
                archived_at=None, created_at=timestamp, updated_at=timestamp,
                realm=realm,
            )
            repo.insert_revision(
                conn, profile_id=profile_id, config_revision=1,
                created_at=timestamp,
            )
            row = self.core.require_profile(conn, profile_id)
            response = profile_view(row)
            repo.idempotency_insert(
                conn, "profiles.create", key, digest(request), 201, response,
                timestamp,
            )
            return response

    def _require_free_name(self, conn, *, realm: str, harness_id: str,
                           display_name: str,
                           exclude_profile_id: str | None = None) -> None:
        normalized = normalize_display_name(display_name)
        for existing_name, existing_id in repo.active_profile_names(
            conn, realm=realm, harness_id=harness_id,
        ):
            if existing_id == exclude_profile_id:
                continue
            if normalize_display_name(existing_name) == normalized:
                raise ProfileError(
                    "NAME_CONFLICT",
                    "an active profile with this name already exists on "
                    "this Harness (Unicode NFC/trim/casefold aware)",
                    status=409,
                ).with_current({
                    "profile_id": existing_id, "display_name": existing_name,
                })

    def get(self, profile_id: str) -> dict[str, Any]:
        with self.core.db.read() as conn:
            return profile_view(self.core.require_profile(conn, profile_id))

    def list(self, *, include_archived: bool = False,
             realm: str | None = None) -> list[dict[str, Any]]:
        with self.core.db.read() as conn:
            rows = [
                row for row in repo.list_profiles(
                    conn, include_archived=include_archived)
                if realm is None or row["realm"] == realm
            ]
            return [profile_view(row) for row in rows]

    def rename(self, key: str, *, profile_id: str, expected_version: int,
               display_name: str) -> dict[str, Any]:
        if not isinstance(display_name, str) or not display_name.strip():
            raise ProfileError(
                "PROFILE_VALUE_INVALID", "display_name must be a non-empty string",
                status=422,
            )
        request = {
            "profile_id": profile_id, "expected_version": expected_version,
            "display_name": display_name,
        }
        with self.core.db.transaction() as conn:
            prior = self._idempotent(
                conn, f"profiles.rename:{profile_id}", key, request,
            )
            if prior:
                return prior["response"]
            current = self.core.require_profile(conn, profile_id)
            if current["display_name"] != display_name:
                self._require_free_name(
                    conn, realm=current["realm"],
                    harness_id=current["harness_id"],
                    display_name=display_name, exclude_profile_id=profile_id)
            row = self._mutate(
                conn, profile_id=profile_id, expected_version=expected_version,
                assignments={"display_name": display_name},
            )
            response = profile_view(row)
            repo.idempotency_insert(
                conn, f"profiles.rename:{profile_id}", key, digest(request),
                200, response, self.core.timestamp(),
            )
            return response

    def archive(self, key: str, *, profile_id: str,
                expected_version: int) -> dict[str, Any]:
        request = {"profile_id": profile_id, "expected_version": expected_version}
        with self.core.db.transaction() as conn:
            prior = self._idempotent(
                conn, f"profiles.archive:{profile_id}", key, request,
            )
            if prior:
                return prior["response"]
            row = self.core.require_profile(conn, profile_id)
            assignments = (
                {"archived_at": row["archived_at"]}
                if row["archived_at"] is not None
                else {"archived_at": self.core.timestamp()}
            )
            updated = self._mutate(
                conn, profile_id=profile_id, expected_version=expected_version,
                assignments=assignments,
            )
            response = profile_view(updated)
            repo.idempotency_insert(
                conn, f"profiles.archive:{profile_id}", key, digest(request),
                200, response, self.core.timestamp(),
            )
            return response

    def restore(self, key: str, *, profile_id: str,
                expected_version: int) -> dict[str, Any]:
        """PM05: restore an archived profile.  An active name conflict must
        be resolved by renaming first — the restore never renames silently."""
        request = {"profile_id": profile_id, "expected_version": expected_version}
        with self.core.db.transaction() as conn:
            prior = self._idempotent(
                conn, f"profiles.restore:{profile_id}", key, request,
            )
            if prior:
                return prior["response"]
            row = self.core.require_profile(conn, profile_id)
            if row["archived_at"] is None:
                raise ProfileError(
                    "PROFILE_VALUE_INVALID", "Profile is not archived",
                    status=422,
                )
            self._require_free_name(
                conn, realm=row["realm"], harness_id=row["harness_id"],
                display_name=row["display_name"],
                exclude_profile_id=profile_id)
            updated = self._mutate(
                conn, profile_id=profile_id, expected_version=expected_version,
                assignments={"archived_at": None},
            )
            response = profile_view(updated)
            repo.idempotency_insert(
                conn, f"profiles.restore:{profile_id}", key, digest(request),
                200, response, self.core.timestamp(),
            )
            return response

    # -- facet values on a profile (US4 storage side) -----------------
    def set_facet_values(self, key: str, *, profile_id: str,
                         expected_version: int,
                         values: Sequence[dict[str, Any]]) -> dict[str, Any]:
        request = {
            "profile_id": profile_id, "expected_version": expected_version,
            "values": [
                {"facet_id": v["facet_id"], "item_id": v["item_id"],
                 "value": v["value"]} for v in values
            ],
        }
        with self.core.db.transaction() as conn:
            prior = self._idempotent(
                conn, f"profiles.set_facet_values:{profile_id}", key, request,
            )
            if prior:
                return prior["response"]
            row = self.core.require_profile(conn, profile_id)
            if row["archived_at"] is not None:
                raise ProfileError(
                    "PROFILE_ARCHIVED", "Profile is archived", status=409,
                )
            if int(row["version"]) != expected_version:
                raise ProfileError(
                    "PROFILE_VERSION_CONFLICT",
                    "Profile changed before the update", status=409,
                ).with_current(profile_view(row))
            prepared: list[tuple[str, str, Any, str]] = []
            for item in values:
                facet_id = item["facet_id"]
                item_id = item["item_id"]
                value = item["value"]
                provider = self.core.registry.require(facet_id)
                if self.core._is_v2_provider(provider):
                    self._validate_v2_item(provider, row, facet_id, item_id,
                                           value)
                    facet_version = provider.descriptor().schema_version
                else:
                    if not provider.applies_to(row["harness_id"]):
                        raise ProfileError(
                            "FACET_NOT_APPLICABLE",
                            f"facet {facet_id} does not apply to harness "
                            f"{row['harness_id']}",
                            status=409,
                        ).with_item(f"{facet_id}/{item_id}")
                    if item_id not in provider.item_ids:
                        raise ProfileError(
                            "FACET_VALUE_INVALID",
                            f"unknown item {item_id} for facet {facet_id}",
                            status=422,
                        ).with_item(f"{facet_id}/{item_id}")
                    reject_sensitive_keys(value)
                    try:
                        provider.validate_value(item_id, value)
                    except ProfileError:
                        raise
                    except (TypeError, ValueError) as exc:
                        raise ProfileError(
                            "FACET_VALUE_INVALID", str(exc), status=422,
                        ).with_item(f"{facet_id}/{item_id}") from exc
                    facet_version = provider.facet_version
                json_dumps(value)  # refuse non-serialisable values early
                prepared.append((facet_id, item_id, value, facet_version))
            new_revision = int(row["current_revision"]) + 1
            timestamp = self.core.timestamp()
            repo.insert_revision(
                conn, profile_id=profile_id, config_revision=new_revision,
                created_at=timestamp,
            )
            repo.copy_revision_values(
                conn, profile_id=profile_id,
                from_revision=int(row["current_revision"]),
                to_revision=new_revision, timestamp=timestamp,
            )
            for facet_id, item_id, value, facet_version in prepared:
                repo.upsert_facet_value(
                    conn, profile_id=profile_id, config_revision=new_revision,
                    facet_id=facet_id, item_id=item_id,
                    value_json=json_dumps(value), facet_version=facet_version,
                    timestamp=timestamp,
                )
            updated = self._mutate(
                conn, profile_id=profile_id, expected_version=expected_version,
                assignments={}, bump_revision_to=new_revision,
            )
            response = profile_view(updated)
            repo.idempotency_insert(
                conn, f"profiles.set_facet_values:{profile_id}", key,
                digest(request), 200, response, timestamp,
            )
            return response

    def _validate_v2_item(self, provider, row, facet_id, item_id,
                          value) -> None:
        """v2 storage validation: descriptor lookup, schema and provider
        validate.  Unsupported facets refuse; unknown applicability stores
        honestly (application-time blocks it, storage does not fake that)."""
        from .contracts import Applicability, validate_value_against_schema
        descriptor = provider.descriptor()
        item = descriptor.item(item_id)
        if item is None:
            raise ProfileError(
                "FACET_VALUE_INVALID",
                f"unknown item {item_id} for facet {facet_id}",
                status=422,
            ).with_item(f"{facet_id}/{item_id}")
        applicability = provider.applicability(
            {"harness_id": row["harness_id"]})
        if applicability is Applicability.UNSUPPORTED:
            raise ProfileError(
                "FACET_NOT_APPLICABLE",
                f"facet {facet_id} does not apply to harness "
                f"{row['harness_id']}",
                status=409,
            ).with_item(f"{facet_id}/{item_id}")
        reject_sensitive_keys(value)
        try:
            validate_value_against_schema(
                dict(item.value_schema), value, where=item_id)
        except ProfileError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProfileError(
                "FACET_VALUE_INVALID", str(exc), status=422,
            ).with_item(f"{facet_id}/{item_id}") from exc
        violations = provider.validate({item_id: value}, {})
        if violations:
            first = violations[0]
            raise ProfileError(
                "FACET_VALUE_INVALID", first.message, status=422,
            ).with_item(f"{facet_id}/{item_id}")

    # -- reads --------------------------------------------------------
    def revisions(self, profile_id: str) -> list[int]:
        with self.core.db.read() as conn:
            self.core.require_profile(conn, profile_id)
            return [int(r["config_revision"])
                    for r in repo.revision_rows(conn, profile_id)]

    def facet_values(self, profile_id: str, *,
                     config_revision: int | None = None) -> list[dict[str, Any]]:
        with self.core.db.read() as conn:
            row = self.core.require_profile(conn, profile_id)
            revision = (
                int(row["current_revision"])
                if config_revision is None else config_revision
            )
            return [
                {
                    "facet_id": r["facet_id"], "item_id": r["item_id"],
                    "value": json_loads(r["value_json"]),
                    "facet_version": r["facet_version"],
                    "quarantined": bool(r["quarantined"]),
                    "updated_at": r["updated_at"],
                }
                for r in repo.facet_values_at(conn, profile_id, revision)
            ]

    def settings_projection(self, profile_id: str) -> dict[str, Any]:
        """Settings page projection: only registered *and* applicable facets
        appear; retained values of absent providers never surface here
        (FR-005, US1.4, US4.2/4.4)."""
        with self.core.db.read() as conn:
            row = self.core.require_profile(conn, profile_id)
            facets: list[dict[str, Any]] = []
            for provider in sorted(
                self.core.registry.registered(),
                key=lambda p: p.facet_id,
            ):
                if not provider.applies_to(row["harness_id"]):
                    continue
                items = []
                for stored in repo.facet_values_at(
                    conn, profile_id, int(row["current_revision"]),
                ):
                    if stored["facet_id"] != provider.facet_id:
                        continue
                    items.append({
                        "item_id": stored["item_id"],
                        "value": json_loads(stored["value_json"]),
                        "needs_migration": bool(stored["quarantined"]),
                        "facet_version_written": stored["facet_version"],
                    })
                facets.append({
                    "facet_id": provider.facet_id,
                    "title": provider.title(),
                    "facet_version": provider.facet_version,
                    "declared_items": list(provider.item_ids),
                    "items": sorted(items, key=lambda i: i["item_id"]),
                })
            return {
                "profile_id": profile_id,
                "harness_id": row["harness_id"],
                "current_revision": int(row["current_revision"]),
                "facets": facets,
            }

    def resolution_preview(self, profile_id: str, *,
                           harness_id: str | None = None) -> dict[str, Any]:
        """Base-resolution of the latest revision (no session overlays)."""
        with self.core.db.read() as conn:
            row = self.core.require_profile(conn, profile_id)
            resolution = resolve_profile_items(
                conn, profile_id=profile_id,
                harness_id=harness_id or row["harness_id"],
                config_revision=int(row["current_revision"]),
                provider_lookup=self.core.provider_lookup,
            )
            return {
                "items": resolution.items,
                "unavailable": resolution.unavailable,
                "digest": resolution.source_digest(),
            }
