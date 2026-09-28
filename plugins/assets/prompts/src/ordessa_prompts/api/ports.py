"""Ports this domain consumes from cooperating domains (pure protocols).

The Prompts domain never imports Profile or Harness implementations; it
declares here the *shape* it will call when those products compose, and
refuses dependent operations (SCOPE_REFUSED / DEPENDENCY_UNAVAILABLE)
when the port is absent (contracts.md §1, G06/G08).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PromptProfileAuthorization(Protocol):
    """The public Profile authorisation port for profile-scoped content.

    `is_authorized(caller_subject, profile_id)` answers whether the
    current service-context caller may create or resolve content that is
    private to `profile_id`. The answer must come from the Profile
    domain's own state; a client-declared identity in a request is never
    consulted (FR03/G06). When no such port is composed, every
    profile-scoped request refuses while the public library keeps
    working (G08).
    """

    def is_authorized(self, caller_subject: str, profile_id: str) -> bool: ...
