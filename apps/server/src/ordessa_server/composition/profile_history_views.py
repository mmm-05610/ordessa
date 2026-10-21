"""Public read port for explicit historical Profile rendering on one Environment.

This port binds the existing Agent ProfileService. It creates no Store, owner,
registry, filesystem reader or automatic historical fallback.
"""
from __future__ import annotations

from ordessa_agents.profiles import (
    HistoricalProfileIdentityMismatch, ProfileAccessRefused, ProfileRevisionRef,
)
from ordessa_units.public import composed_profile_service
from ordessa_server.bootstrap.migrations.harness_profile_projection import (
    HistoricalHarnessRef, project_imported_historical_revision,
)


class EnvironmentHistoricalProfileViews:
    def __init__(self, environment):
        # Agent owner itself verifies that this service was already composed.
        self._profiles = composed_profile_service(environment)
        self._environment_namespace = environment.environment_id

    def select_current(self, modern_ref: ProfileRevisionRef,
                       historical_ref: HistoricalHarnessRef):
        """Return old bytes only when the exact modern ref is still current.

        ProfileService performs read ACL and archived selection under its
        original Environment lock. The explicit projection reader rechecks
        old ref, digest, disabled flag and immutable imported provenance.
        """
        if type(modern_ref) is not ProfileRevisionRef or type(historical_ref) is not HistoricalHarnessRef:
            raise TypeError("fixed modern and historical Profile references required")
        if modern_ref.environment_namespace != self._environment_namespace:
            raise HistoricalProfileIdentityMismatch("foreign Environment Profile reference")
        current = self._profiles.select_current(modern_ref.profile_id)
        if current.ref != modern_ref:
            raise ProfileAccessRefused("Profile revision is no longer current")
        view = project_imported_historical_revision(
            revision=current, expected=historical_ref)
        if view.envelope()["disabled"]:
            raise ProfileAccessRefused("historical Profile is disabled")
        return view


def historical_profile_views(environment) -> EnvironmentHistoricalProfileViews:
    """Produce a view port bound to the already selected Environment service."""
    return EnvironmentHistoricalProfileViews(environment)
