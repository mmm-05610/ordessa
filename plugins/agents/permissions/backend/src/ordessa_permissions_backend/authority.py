"""`PermissionsAuthority` - the read surface over the authorization facts.

One class, two fact sources, zero new stores (PE1-1): the settled-allow
grants this plugin's own `ApprovalFacts` already persists (read through its
`authority_grant_rows` projection) and the current intent revisions the
`PolicyRepository` already persists. Every `AuthorityRecord` answers *who /
approved what / at which scope / until when / in which state*; nothing here
rules on an operation - `Authorizer` (the `permissions.authorizer@1` port)
stays the only verdict, and a listing that contains a record is never a
licence to proceed.

Honesty rules this module implements (and the tests pin):

* absence is a fact: an empty tuple means "no effective authorization fact is
  recorded", `lookup` answers `None`, and nothing is defaulted to allow;
* a person the store never recorded stays `None` (`requestedBy` /
  `decidedBy` are nullable columns added by PE1; no row is invented);
* state is derived from stored facts alone - `revoked` beats `consumed`
  beats `expired` beats `active` - and only `active` records are listed;
  `lookup` is where an expired or revoked fact is read AS such;
* intent rules are configuration facts, not session facts: a rule record
  never answers a session-scoped query, because no session id is stored with
  a rule and none is invented;
* a malformed query input (non-text filter, naive timestamp, malformed
  digest) is refused with the package's schema code, never on an empty world.

The wire projection of this surface is the read-only
`permissions.authority.query` method (`plugin.py`); this class is also the
object composed under the `permissions.authority.query@1` provided port.
"""
from __future__ import annotations

import datetime as dt
import fnmatch
from typing import Any, Mapping

from ordessa_permissions_api import (
    AUTHORITY_QUERY_PORT,
    AUTHORITY_QUERY_PORT_VERSION,
    AuthorityRecord,
    AuthorityScope,
    AuthoritySourceKind,
    AuthorityStateKind,
    PolicyRefusal,
    TOOL_KEYS,
)
from server_plugin_api import WireError

from .facts import ApprovalFacts
from .policies import PolicyRepository

__all__ = ["AUTHORITY_METHOD", "AUTHORITY_OPTIONAL_PARAMS", "AUTHORITY_QUERY_PORT",
           "AUTHORITY_QUERY_PORT_VERSION", "PermissionsAuthority"]

#: The read-only wire method that projects this surface (plugin.py registers
#: it; the guard test binds this literal to that module's source text).
AUTHORITY_METHOD = "permissions.authority.query"
#: exact wire/1 shape: nothing is required; every optional param is an
#: operation filter or the single-fact `factRef` narrow. The host's dispatch
#: wall refuses every other param; `query` never re-implements that refusal.
AUTHORITY_OPTIONAL_PARAMS: frozenset[str] = frozenset(
    {"factRef", "tool", "target", "sessionId", "principal", "operationDigest"})

_MAX_TEXT = 512


def _moment(value: Any, *, source: str) -> dt.datetime:
    """The query's clock: an aware datetime, an ISO string, or None for now."""
    if value is None:
        return dt.datetime.now(dt.timezone.utc)
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value)
        except ValueError:
            raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID", source=source,
                                target="unparseable timestamp") from None
    if not isinstance(value, dt.datetime) or value.tzinfo is None \
            or value.utcoffset() is None:
        raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID", source=source,
                            target=None if isinstance(value, str)
                            else type(value).__name__)
    return value


def _filter_text(value: Any, *, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_TEXT \
            or any(c in value for c in "\x00\r\n"):
        raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID",
                            source=f"authority.query ({name})",
                            target=None if isinstance(value, str)
                            else type(value).__name__)
    return value


def _digest_filter(value: Any) -> str | None:
    text = _filter_text(value, name="operationDigest")
    if text is None:
        return None
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID",
                            source="authority.query (operationDigest)",
                            target="not a lowercase hex digest")
    return text


class PermissionsAuthority:
    """The `permissions.authority.query@1` implementation (facts, not rulings).

    `policies=None` is the honest grants-only state: the grant ledger still
    answers, rule-derived records are simply never produced, and the wire
    projection reports the narrowed surface rather than pretending rules were
    read from a store that is not wired.
    """

    def __init__(self, facts: ApprovalFacts,
                 policies: PolicyRepository | None = None) -> None:
        self._facts = facts
        self._policies = policies

    # -- the port surface -------------------------------------------------------

    def effective_for_operation(self, *, tool: Any = None, target: Any = None,
                                session_id: Any = None, principal: Any = None,
                                operation_digest: Any = None,
                                now: Any = None) -> tuple[AuthorityRecord, ...]:
        """Active records that speak about the asked operation. Grants match
        on exact digest / tool / target / session / person; current allow
        rules match on tool (and target pattern) but never on a session,
        because no rule carries one."""
        moment = _moment(now, source="authority.query (now)")
        tool_q = _filter_text(tool, name="tool")
        target_q = _filter_text(target, name="target")
        session_q = _filter_text(session_id, name="sessionId")
        principal_q = _filter_text(principal, name="principal")
        digest_q = _digest_filter(operation_digest)
        records: list[AuthorityRecord] = []
        for row in self._grant_rows():
            if session_q is not None and row["sessionId"] != session_q:
                continue
            if digest_q is not None and row["operationDigest"] != digest_q:
                continue
            if tool_q is not None and row["toolKey"] != tool_q:
                continue
            if target_q is not None and row["target"] != target_q:
                continue
            if principal_q is not None and principal_q not in (
                    row["principal"], row["decidedBy"]):
                continue
            record = self._grant_record(row, moment)
            if record is not None and record.effective:
                records.append(record)
        if session_q is None and digest_q is None:
            # a digest-narrowed query asks about ONE operation; rule facts
            # carry no operation digest and so cannot answer it - excluded
            # rather than returned as if they did
            for record in self._rule_records(moment):
                if not record.effective:
                    continue
                if tool_q is not None and record.tool != tool_q:
                    continue
                if target_q is not None and not self._rule_target_matches(
                        record, target_q):
                    continue
                if principal_q is not None and record.approved_by != principal_q:
                    continue
                records.append(record)
        return tuple(sorted(records, key=lambda item: item.authority_id))

    def effective_for_session(self, session_id: str,
                              *, now: Any = None) -> tuple[AuthorityRecord, ...]:
        """Active grant records attributed to exactly this session. Another
        session's records never surface (two-session isolation), and rules
        are never folded in (they carry no session identity to match)."""
        moment = _moment(now, source="authority.query (now)")
        named = _filter_text(session_id, name="sessionId")
        if named is None:
            raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID",
                                source="authority.query (sessionId)",
                                target="None")
        records: list[AuthorityRecord] = []
        for row in self._grant_rows():
            if row["sessionId"] != named:
                continue
            record = self._grant_record(row, moment)
            if record is not None and record.effective:
                records.append(record)
        return tuple(sorted(records, key=lambda item: item.authority_id))

    def effective_for_user(self, principal: str,
                           *, now: Any = None) -> tuple[AuthorityRecord, ...]:
        """Active records a person is named on: grants they requested or
        approved, and allow-rule exceptions they issued. A record with no
        attributable person is never folded in."""
        moment = _moment(now, source="authority.query (now)")
        named = _filter_text(principal, name="principal")
        if named is None:
            raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID",
                                source="authority.query (principal)",
                                target="None")
        records: list[AuthorityRecord] = []
        for row in self._grant_rows():
            if named not in (row["principal"], row["decidedBy"]):
                continue
            record = self._grant_record(row, moment)
            if record is not None and record.effective:
                records.append(record)
        for record in self._rule_records(moment):
            if record.effective and record.approved_by == named:
                records.append(record)
        return tuple(sorted(records, key=lambda item: item.authority_id))

    def lookup(self, fact_ref: str,
               *, now: Any = None) -> AuthorityRecord | None:
        """One authorization fact by its reference (the approval id, or the
        `intentId@revision#index` spelling of a current allow rule), whatever
        its recorded state - or `None` when no authorization fact answers to
        that reference. This is where an expired or revoked grant is read AS
        expired or revoked; the listings above only ever contain active ones."""
        moment = _moment(now, source="authority.query (now)")
        ref = _filter_text(fact_ref, name="factRef")
        if ref is None:
            raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID",
                                source="authority.query (factRef)",
                                target="None")
        for row in self._grant_rows():
            if row["approvalId"] == ref:
                return self._grant_record(row, moment)
        rule_ref = self._rule_record_for_ref(ref, moment)
        return rule_ref

    def revoke(self, approval_id: str, *, reason: str,
               now: Any = None) -> AuthorityRecord | None:
        """Revoke one settled-allow grant through the store's own writer; the
        settled decision stands and the revocation is an additive fact. The
        record in its new `revoked` state is returned, or `None` when no
        settled-allow grant answers to that id - deny/open/invalid rows are
        refused, never silently accepted. `reason` is required text: a
        revocation without a stated reason is exactly the unattributable
        fact this surface refuses to record."""
        moment = _moment(now, source="authority.revoke (now)")
        checked_id = _filter_text(approval_id, name="approvalId")
        if checked_id is None:
            raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID",
                                source="authority.revoke (approvalId)",
                                target="None")
        checked_reason = _filter_text(reason, name="reason")
        if checked_reason is None:
            raise PolicyRefusal("PERMISSION_AUTHORIZATION_INVALID",
                                source="authority.revoke (reason)",
                                target="None")
        if not self._facts.revoke(checked_id, reason=checked_reason, now=moment):
            return None
        for row in self._grant_rows():
            if row["approvalId"] == checked_id:
                return self._grant_record(row, moment)
        return None

    # -- the wire projection (read-only, describe discipline) -------------------

    def availability(self) -> tuple[bool, str | None]:
        """The hello question only, never a dispatch gate (order 097): an
        unreadable store answers honestly and the handler still returns the
        honest empty body."""
        try:
            self._facts.authority_grant_rows()
        except Exception:
            return False, ("AUTHORITY_STORE_UNREADABLE: the approval-fact"
                           " store could not be read")
        return True, None

    def query(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """The `permissions.authority.query` body: closed shape
        `{ready, records}`, every record the frozen 13-field `AuthorityRecord`
        projection. `factRef` narrows to that one fact (0/1 records); the
        other optional params are the operation filters. A store that cannot
        be read answers `ready: false` with empty records - never a fabricated
        fact, and nothing in this body grants anything."""
        if not isinstance(params, Mapping):
            raise WireError("INVALID_REQUEST", "params must be an object")
        try:
            ready = self.availability()[0]
        except Exception:
            # readiness is derived, never assumed: a failing source is False
            # (the describe projection's own convention)
            ready = False
        try:
            if not ready:
                # an unreadable store is the honest empty answer, stated -
                # never a half-read that could be mistaken for a full world
                return {"ready": False, "records": []}
            fact_ref = params.get("factRef")
            if fact_ref is not None:
                record = self.lookup(fact_ref)
                records = [] if record is None else [record.as_record()]
            else:
                found = self.effective_for_operation(
                    tool=params.get("tool"), target=params.get("target"),
                    session_id=params.get("sessionId"),
                    principal=params.get("principal"),
                    operation_digest=params.get("operationDigest"))
                records = [record.as_record() for record in found]
        except PolicyRefusal as refusal:
            # The message names the layer and the stable code only - never
            # the value that was refused.
            raise WireError("INVALID_REQUEST",
                            f"authority query refused ({refusal.code})") from refusal
        return {"ready": ready, "records": records}

    # -- grant-derived records -----------------------------------------------------

    def _grant_rows(self) -> list[dict[str, Any]]:
        return self._facts.authority_grant_rows()

    def _grant_record(self, row: dict[str, Any],
                      moment: dt.datetime) -> AuthorityRecord | None:
        """Project one settled-allow row; `None` for a row that cannot vouch
        for its own bindings (no tool key recorded - it can never answer an
        operation query, and inventing a tool would be worse than silence)."""
        tool = row["toolKey"]
        if not isinstance(tool, str) or tool not in TOOL_KEYS:
            return None
        expires_at = _parse_stamp(row["expiresAt"])
        if row["revokedAt"] is not None:
            state = AuthorityStateKind.REVOKED
        elif row["consumedAt"] is not None:
            state = AuthorityStateKind.CONSUMED
        elif expires_at is not None and moment > expires_at:
            state = AuthorityStateKind.EXPIRED
        else:
            state = AuthorityStateKind.ACTIVE
        return AuthorityRecord.of(
            source=AuthoritySourceKind.APPROVAL_GRANT,
            scope=AuthorityScope.SESSION,
            tool=tool,
            state=state,
            fact_ref=row["approvalId"],
            target=row["target"],
            operation_digest=row["operationDigest"],
            requested_by=row["principal"],
            approved_by=row["decidedBy"],
            granted_at=_parse_stamp(row["grantedAt"]),
            expires_at=expires_at,
            revision=row["version"],
        )

    # -- rule-derived records --------------------------------------------------------

    def _rule_records(self, moment: dt.datetime) -> tuple[AuthorityRecord, ...]:
        if self._policies is None:
            return ()
        built: list[AuthorityRecord] = []
        for raw in self._policies.intents_current_records():
            built.extend(record for record in self._rules_of_intent(raw, moment)
                         if record is not None)
        return tuple(built)

    def _rule_record_for_ref(self, ref: str,
                             moment: dt.datetime) -> AuthorityRecord | None:
        if self._policies is None or "@" not in ref or "#" not in ref:
            return None
        intent_id, _, rest = ref.partition("@")
        revision_text, _, index_text = rest.partition("#")
        if not intent_id or not revision_text.isdigit() or not index_text.isdigit():
            return None
        for raw in self._policies.intents_current_records():
            if raw.get("intentId") != intent_id \
                    or raw.get("revision") != int(revision_text):
                continue
            rules = raw.get("rules")
            index = int(index_text)
            if not isinstance(rules, list) or index >= len(rules):
                return None
            aligned = self._rules_of_intent(raw, moment)
            return aligned[index] if index < len(aligned) else None
        return None

    def _rules_of_intent(self, raw: dict[str, Any],
                         moment: dt.datetime) -> list[AuthorityRecord | None]:
        """Project one current intent's rules, ALIGNED to the stored rule
        list (`None` wherever the stored rule is no authorization fact: a
        deny/ask rule, an undeclared tool key, a foreign scope, or an
        exception whose provenance does not vouch). The alignment is what
        makes the `intentId@revision#index` reference in `lookup` point at
        the rule it names. A record that cannot be vouched for contributes
        nothing rather than a guess; the describe projection is the lane
        that reports broken records."""
        try:
            intent_id = raw["intentId"]
            revision = raw["revision"]
            rules = raw["rules"]
        except (KeyError, TypeError):
            return []
        if not isinstance(intent_id, str) or not isinstance(revision, int) \
                or not isinstance(rules, list):
            return []
        scope_map = {"session": AuthorityScope.SESSION,
                     "project": AuthorityScope.PROFILE,
                     "user": AuthorityScope.USER}
        scope = scope_map.get(raw.get("scope"))
        built: list[AuthorityRecord | None] = []
        for index, rule in enumerate(rules):
            record: AuthorityRecord | None = None
            if isinstance(rule, dict) and scope is not None \
                    and rule.get("action") == "allow":
                record = self._rule_record(intent_id, revision, index, scope,
                                           rule, moment)
            built.append(record)
        return built

    @staticmethod
    def _rule_record(intent_id: str, revision: int, index: int,
                     scope: AuthorityScope, rule: dict[str, Any],
                     moment: dt.datetime) -> AuthorityRecord | None:
        tool = rule.get("key")
        if not isinstance(tool, str) or tool not in TOOL_KEYS:
            return None
        pattern = rule.get("pattern")
        if pattern is not None and not isinstance(pattern, str):
            return None
        approved_by: str | None = None
        expires_at: dt.datetime | None = None
        authorization = rule.get("authorization")
        if authorization is not None:
            if not isinstance(authorization, dict):
                return None
            issuer = authorization.get("issuer")
            if not isinstance(issuer, str) or authorization.get("verified") is not True:
                return None
            if authorization.get("ceilingRevision") is None:
                return None
            approved_by = issuer
            expires_at = _parse_stamp(authorization.get("expiresAt"))
        state = AuthorityStateKind.EXPIRED \
            if expires_at is not None and moment > expires_at \
            else AuthorityStateKind.ACTIVE
        return AuthorityRecord.of(
            source=AuthoritySourceKind.POLICY_RULE,
            scope=scope,
            tool=tool,
            state=state,
            fact_ref=f"{intent_id}@{revision}#{index}",
            target=pattern,
            operation_digest=None,
            requested_by=None,
            approved_by=approved_by,
            granted_at=None,
            expires_at=expires_at,
            revision=revision,
        )

    @staticmethod
    def _rule_target_matches(record: AuthorityRecord, target: str) -> bool:
        """A rule without a pattern is a standing tool-level allow and speaks
        about every target; a patterned rule answers via the same glob
        semantics the rule was stored under (`fnmatchcase`, as the API's
        TargetMatcher)."""
        if record.target is None:
            return True
        return fnmatch.fnmatchcase(target, record.target)


def _parse_stamp(value: Any) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None \
            else parsed.replace(tzinfo=dt.timezone.utc)
    if isinstance(value, dt.datetime):
        return value if value.tzinfo is not None \
            else value.replace(tzinfo=dt.timezone.utc)
    return None
