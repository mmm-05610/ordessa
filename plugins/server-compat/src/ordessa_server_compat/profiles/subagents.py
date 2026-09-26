"""Order 65 A/B: who may call whom, and the two tools that carry it.

The delegation model is deliberately the desktop's shape, not a new one: a
parent Profile holds **explicit authorization edges** (none by default), and a
single generic tool pair carries the work - `list_subagents` for detail and
`run_subagent` to run one - with the roster summary embedded in the
description so one call is enough. Four rules are this module's own:

* **visibility derives from authorization and never replaces it**: an
  unauthorized Profile appears nowhere - not even as "unavailable" - and the
  caller must re-resolve at call time even when the model "remembers" a name
  from an older context;
* **optional arguments only narrow**: a caller may tighten a child's model
  slot, permission or limits, never widen them (order 60's rule, restated);
* **a cycle is refused by name, a deep chain is not**: one role may hand work
  on for as long as the chain never returns to a role already waiting inside it
  - that alone would deadlock, so it is the refusal that survives ruling R-0016,
  which revoked 65's depth ceiling and its "a child gets no run tool" default;
  the bound that remains is the ≤ 4 calls per turn;
* **no grants, no tools**: a Profile with no edges gets neither tool
  materialised - a pair of always-failing tools is worse than none.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

MAX_SUBAGENT_DESCRIPTION_CHARS = 160
MAX_ROSTER_ENTRIES = 32
MAX_INLINE_NAMES = 8
DEFAULT_TURNS_LIMIT = 4
DEFAULT_TIMEOUT_SECONDS = 600          # the order's ten minutes
MAX_TIMEOUT_SECONDS = 600
MIN_DESCRIPTION_WORDS = 3
MAX_DESCRIPTION_WORDS = 5

_LIST_TOOL_NAME = "list_subagents"
_RUN_TOOL_NAME = "run_subagent"
_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")


class DelegationError(RuntimeError):
    """A typed refusal of one delegation act."""

    def __init__(self, code: str, message: str, *, available: Sequence[str] = ()) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.available = tuple(available)


# -- A: authorization -------------------------------------------------------

def grant_edges(rows: Iterable[Mapping[str, Any]]) -> dict[str, set[str]]:
    """The grant table as parent -> children, from the ledger rows."""
    edges: dict[str, set[str]] = {}
    for row in rows:
        edges.setdefault(str(row["parent_profile_id"]), set()).add(
            str(row["child_profile_id"]))
    return edges


def resolve_roster(
    *, parent_id: str, edges: Mapping[str, set[str]],
    profiles: Sequence[Mapping[str, Any]], availability: Mapping[str, str] | None = None,
    workspace_of: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """The authorized roster, each entry with its availability state.

    Only granted Profiles appear. `availability` maps a child id to a typed
    unavailability reason; a child that is not available is still *listed*
    (the parent is authorized to know it exists) but marked, so the tool can
    say why a call would fail instead of failing blind.

    Order 138 (`65:83`, ops `R-0070 ①`): `workspace_of` maps a child id to the
    workspace it currently operates in; the entry carries that as the contract's
    `workspace` field so the roster is the *visible* face of the same-workspace
    authorization, and the delegation act can filter candidates by the parent's
    workspace. Absent (a caller without session access) ⇒ the field is ``None``.
    """
    granted = edges.get(str(parent_id), set())
    roster: list[dict[str, Any]] = []
    for profile in profiles:
        profile_id = str(profile["id"])
        if profile_id not in granted or profile_id == str(parent_id):
            continue
        roster.append({
            "profileId": profile_id,
            "name": profile["name"],
            "harness": profile["harness_type"],
            "description": (profile.get("description") or "")[:MAX_SUBAGENT_DESCRIPTION_CHARS],
            "available": (availability or {}).get(profile_id) is None,
            "reason": (availability or {}).get(profile_id),
            "workspace": (workspace_of or {}).get(profile_id),
        })
        if len(roster) >= MAX_ROSTER_ENTRIES:
            break
    return roster


def has_delegation(edges: Mapping[str, set[str]], profile_id: str) -> bool:
    """Whether this Profile gets the tools at all (no grants, no tools)."""
    return bool(edges.get(str(profile_id)))


def check_cycle(chain: Sequence[str]) -> None:
    """Refuse the one shape a delegation chain may never take: a repeated role.

    `chain` is the ancestry the server read off the ledger plus the child about
    to be started. Depth is not a ceiling here (ruling R-0016 revoked 65's);
    a role that appears twice is the case that actually harms - it would be
    waiting on a call that is waiting on it.
    """
    if len(set(chain)) != len(chain):
        raise DelegationError(
            "SUBAGENT_CYCLE",
            "the delegation chain closes a cycle on a role already waiting in it",
        )


# -- B: the two tools -------------------------------------------------------

def tool_definitions(
    *, roster: Sequence[Mapping[str, Any]], include_run: bool = True,
) -> list[dict[str, Any]]:
    """The MCP tool pair, with the roster summary embedded in `run_subagent`.

    A Profile with no grants gets an empty list (the tools are not
    materialised). `include_run=False` asks for the list tool alone; it is not
    what a child sees by default - whether a child may delegate is decided by
    its own grants (ruling R-0016 revoked 65's "a child gets no run tool" rule).
    """
    if not roster:
        return []
    summary = "; ".join(
        f"{entry['name']} ({entry['harness']}): {entry['description'] or 'no description'}"
        for entry in roster
    )[:MAX_ROSTER_ENTRIES * MAX_SUBAGENT_DESCRIPTION_CHARS]
    tools: list[dict[str, Any]] = [{
        "name": _LIST_TOOL_NAME,
        "description": (
            "List the subagents this role is authorized to call, with their "
            "harness, availability and description. Authorized entries only."
        ),
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string"}}, "additionalProperties": False},
    }]
    if include_run:
        tools.append({
            "name": _RUN_TOOL_NAME,
            "description": (
                "Run one authorized subagent as an independent execution and "
                "return its bounded final summary. Provide a self-contained "
                "prompt (state what to return, and whether it is research or a "
                "code change). The subagent has fresh context: it cannot see "
                "this conversation, and its result is not visible to the user - "
                "relay it. Authorized subagents: " + summary
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "subagent": {"type": "string",
                                 "description": "the authorized subagent's name"},
                    "description": {"type": "string",
                                    "description": "a 3-5 word label"},
                    "prompt": {"type": "string",
                               "description": "a self-contained task statement"},
                    "task_id": {"type": "string",
                                "description": "continue a previous subagent session"},
                    "model": {"type": "string"},
                    "permission": {"type": "string", "enum": ["default", "plan"]},
                    "timeout": {"type": "integer"},
                    "max_turns": {"type": "integer"},
                },
                "required": ["subagent", "description", "prompt"],
                "additionalProperties": False,
            },
        })
    return tools


def validate_run_arguments(
    arguments: Mapping[str, Any], *, roster: Sequence[Mapping[str, Any]],
    child_limits: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one `run_subagent` call; refusals inline the available names.

    The named refusals carry the *authorized* names only (bounded), so a model
    that guessed wrong can correct itself in one hop without learning anything
    about Profiles it may not call.
    """
    names = [str(entry["name"]) for entry in roster]
    if not roster:
        raise DelegationError(
            "SUBAGENT_NOT_AUTHORIZED", "this role has no authorized subagents",
        )
    if set(arguments) - {"subagent", "description", "prompt", "task_id", "model",
                         "permission", "timeout", "max_turns"}:
        raise DelegationError(
            "SUBAGENT_ARGUMENT_INVALID",
            f"unknown arguments: {sorted(set(arguments) - {'subagent', 'description', 'prompt'})}",
            available=names,
        )
    subagent = arguments.get("subagent")
    if subagent not in names:
        # The refusal names nothing the caller did not already say: echoing the
        # guess back would let a model probe which names exist.
        raise DelegationError(
            "SUBAGENT_NOT_AUTHORIZED",
            "the requested subagent is not among this role's authorized subagents",
            available=names[:MAX_INLINE_NAMES],
        )
    description = arguments.get("description")
    if not isinstance(description, str):
        raise DelegationError("SUBAGENT_ARGUMENT_INVALID", "description is required",
                              available=names[:MAX_INLINE_NAMES])
    words = description.split()
    if not MIN_DESCRIPTION_WORDS <= len(words) <= MAX_DESCRIPTION_WORDS:
        raise DelegationError(
            "SUBAGENT_ARGUMENT_INVALID",
            f"description must be {MIN_DESCRIPTION_WORDS}-{MAX_DESCRIPTION_WORDS} words",
            available=names[:MAX_INLINE_NAMES],
        )
    prompt = arguments.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 32_000:
        raise DelegationError("SUBAGENT_ARGUMENT_INVALID", "prompt must be self-contained text",
                              available=names[:MAX_INLINE_NAMES])
    validated: dict[str, Any] = {"subagent": subagent, "description": description,
                                 "prompt": prompt}
    limits = dict(child_limits or {})
    permission = arguments.get("permission")
    if permission is not None:
        if permission not in {"default", "plan"}:
            raise DelegationError("SUBAGENT_PERMISSION_WIDENED",
                                  "permission may only name a narrower preset")
        allowed = limits.get("permissions")
        if allowed is not None and permission not in allowed:
            raise DelegationError(
                "SUBAGENT_PERMISSION_WIDENED",
                "the requested preset is wider than the subagent's own rules allow",
            )
        validated["permission"] = permission
    model = arguments.get("model")
    if model is not None:
        allowed_models = limits.get("models")
        if not isinstance(model, str) or (allowed_models is not None and model not in allowed_models):
            raise DelegationError(
                "SUBAGENT_MODEL_WIDENED",
                "the requested model is not one the subagent may use",
            )
        validated["model"] = model
    timeout = arguments.get("timeout", DEFAULT_TIMEOUT_SECONDS)
    if (isinstance(timeout, bool) or not isinstance(timeout, int)
            or not 1 <= timeout <= MAX_TIMEOUT_SECONDS):
        raise DelegationError(
            "SUBAGENT_TIMEOUT_INVALID",
            f"timeout must be 1..{MAX_TIMEOUT_SECONDS} seconds (ten minutes)",
            available=names[:MAX_INLINE_NAMES],
        )
    validated["timeout"] = timeout
    max_turns = arguments.get("max_turns", DEFAULT_TURNS_LIMIT)
    if (isinstance(max_turns, bool) or not isinstance(max_turns, int)
            or not 1 <= max_turns <= DEFAULT_TURNS_LIMIT):
        raise DelegationError(
            "SUBAGENT_TURNS_INVALID",
            f"max_turns must be 1..{DEFAULT_TURNS_LIMIT}",
            available=names[:MAX_INLINE_NAMES],
        )
    validated["max_turns"] = max_turns
    task_id = arguments.get("task_id")
    if task_id is not None:
        if not isinstance(task_id, str) or not task_id:
            raise DelegationError("SUBAGENT_ARGUMENT_INVALID", "task_id must be a handle",
                                  available=names[:MAX_INLINE_NAMES])
        validated["task_id"] = task_id
    return validated


def inline_available(error: DelegationError) -> dict[str, Any]:
    """The refusal as the tool returns it: typed, with the names inlined."""
    payload: dict[str, Any] = {"error": error.code, "message": error.message}
    if error.available:
        payload["available"] = list(error.available[:MAX_INLINE_NAMES])
    return payload
