"""T05 / G06 — scope and authorisation boundaries.

Required counter-examples (verification.md G06):
* Profile A's private content must not be resolvable through Profile B;
* switching Server/data domain must not read the same id through to other
  content ("同 ID 串读");
* a client self-declared identity is never consulted — the service context
  and the Profile authorisation port decide.

Gates: G06. Requirements: FR03, FR05.
"""
from __future__ import annotations

import base64

import pytest

from ordessa_prompts.api import (
    PromptError,
    PromptRecord,
    PromptScope,
    body_digest,
)
from ordessa_prompts.backend.records import PromptRecords
from ordessa_prompts.backend.service import PromptsService
from ordessa_prompts.backend.storage import PromptsStore

CANARY = "CANARY-ALPHA-PRIVATE-must-not-leak"


class Port:
    """The public Profile authorisation port shape (api/ports.py)."""

    def __init__(self, allowed: "set[str]") -> None:
        self.allowed = set(allowed)
        self.calls: list[tuple[str, str]] = []

    def is_authorized(self, caller_subject: str, profile_id: str) -> bool:
        self.calls.append((caller_subject, profile_id))
        return profile_id in self.allowed


def _service(store: PromptsStore, subject: str,
             port: "Port | None") -> PromptsService:
    return PromptsService(PromptRecords(store), server_scope="server-A",
                          subject_provider=lambda: subject,
                          profile_authorization=port)


@pytest.fixture()
def two_profile_clients(tmp_path):
    """One Server data domain, two callers, each authorised for one profile."""
    store = PromptsStore(tmp_path / "scope" / "prompts.db")
    alpha_port = Port({"alpha"})
    beta_port = Port({"beta"})
    alpha = _service(store, "operator-alpha", alpha_port)
    beta = _service(store, "operator-beta", beta_port)
    try:
        yield alpha, beta, alpha_port, beta_port, store
    finally:
        store.close()


def _profile_prompt(service: PromptsService, profile_id: str, body: bytes,
                    title: str, key: str) -> str:
    return service.create(kind="instruction",
                          scope={"kind": "profile", "profileId": profile_id},
                          title=title, description=None, body=body,
                          operation_key=key)["id"]


# -- A's private content is invisible to B -------------------------------------

def test_profile_private_content_created_by_alpha_is_refused_to_beta(
        two_profile_clients):
    alpha, beta, alpha_port, beta_port, _store = two_profile_clients
    prompt_id = _profile_prompt(alpha, "alpha", CANARY.encode(), CANARY, "k-alpha")

    # alpha sees its own private content
    head = alpha.get(prompt_id)
    assert base64.b64decode(head["bodyBase64"]) == CANARY.encode()
    assert ("operator-alpha", "alpha") in alpha_port.calls

    for description, call in (
        ("get", lambda: beta.get(prompt_id)),
        ("getRevision", lambda: beta.get_revision(prompt_id)),
        ("update", lambda: beta.update(prompt_id, expected_metadata_version=1,
                                       expected_latest_revision=1,
                                       patch={"title": "hijacked"},
                                       operation_key="k-beta-update")),
        ("clone", lambda: beta.clone(prompt_id, target_scope={"kind": "library"},
                                     title="stolen", operation_key="k-beta-clone")),
        ("archive", lambda: beta.archive(prompt_id, expected_metadata_version=1,
                                        operation_key="k-beta-archive")),
        ("exportText", lambda: beta.export_text(prompt_id)),
        ("resolveSnapshot", lambda: beta.resolve_snapshot(
            {"instructions": [{"promptId": prompt_id}]})),
        ("preview", lambda: beta.preview({"instructions": [{"promptId": prompt_id}]})),
    ):
        with pytest.raises(PromptError) as exc:
            call()
        assert exc.value.code == "SCOPE_REFUSED", f"{description}: {exc.value}"
        assert CANARY not in str(exc.value), f"{description} leaked content: {exc.value}"
        assert "bodyBase64" not in str(exc.value)

    # B never even reaches the stored bytes, so no body is read out
    assert beta_port.calls, "the port was consulted for B"
    assert ("operator-beta", "alpha") in beta_port.calls, (
        f"B's lookup did not consult the port with its own subject: {beta_port.calls}")

    # ... and the record is untouched by every refusal
    unchanged = alpha.get(prompt_id)
    assert unchanged["title"] == CANARY and unchanged["metadataVersion"] == 1
    assert base64.b64decode(unchanged["bodyBase64"]) == CANARY.encode()


def test_beta_cannot_list_or_resolve_alphas_private_titles(two_profile_clients):
    alpha, beta, _pa, _pb, _store = two_profile_clients
    prompt_id = _profile_prompt(alpha, "alpha", b"alpha body", CANARY, "k-a")

    # an unscoped list is the public library: profile-private rows never appear
    unscoped = beta.list()
    assert prompt_id not in [item["id"] for item in unscoped["items"]]
    assert all(CANARY not in item["title"] for item in unscoped["items"])
    # neither does alpha's own unscoped list leak it to a different caller
    alpha_unscoped = alpha.list()
    assert prompt_id not in [item["id"] for item in alpha_unscoped["items"]], (
        "profile-private content must only come back from a named profile scope")

    # naming the profile you ARE authorised for is the only way in
    as_alpha = alpha.list(scope={"kind": "profile", "profileId": "alpha"})
    assert prompt_id in [item["id"] for item in as_alpha["items"]]
    with pytest.raises(PromptError) as exc:
        beta.list(scope={"kind": "profile", "profileId": "alpha"})
    assert exc.value.code == "SCOPE_REFUSED"


def test_library_content_stays_readable_from_a_profile_only_context(
        two_profile_clients):
    alpha, beta, _pa, pb, _store = two_profile_clients
    shared = alpha.create(kind="instruction", scope={"kind": "library"},
                          title="public", description=None, body=b"public body",
                          operation_key="k-public")["id"]
    selection = {"instructions": [{"promptId": shared}]}
    assert base64.b64decode(beta.get(shared)["bodyBase64"]) == b"public body"
    assert shared in [item["id"] for item in
                      beta.list(scope={"kind": "library"})["items"]]
    snapshot = beta.resolve_snapshot(selection)
    assert snapshot.resolved[0].body == b"public body"
    assert beta.preview(selection)["revisions"] == {shared: 1}
    # the port is never consulted for public content (no needless coupling)
    assert pb.calls == []


def test_authorisation_is_per_profile_id_not_a_prefix_match(tmp_path):
    store = PromptsStore(tmp_path / "prefix" / "prompts.db")
    port = Port({"alpha-x"})
    service = _service(store, "operator-1", port)
    with pytest.raises(PromptError) as exc:
        service.create(kind="instruction",
                       scope={"kind": "profile", "profileId": "alpha"},
                       title="t", description=None, body=b"body",
                       operation_key="k-prefix")
    assert exc.value.code == "SCOPE_REFUSED"
    assert ("operator-1", "alpha") in port.calls
    # and the near-miss profile id does work
    created = service.create(kind="instruction",
                             scope={"kind": "profile", "profileId": "alpha-x"},
                             title="t", description=None, body=b"body",
                             operation_key="k-prefix-ok")
    assert created["scope"] == {"kind": "profile", "profileId": "alpha-x"}
    store.close()


def test_a_malformed_profile_id_refuses_before_the_port_is_consulted(tmp_path):
    store = PromptsStore(tmp_path / "malformed" / "prompts.db")
    port = Port({"alpha"})
    service = _service(store, "operator-1", port)
    for bad in ("", "../alpha", "ALPHA", "a" * 64 + ".x", None):
        port.calls.clear()
        with pytest.raises(PromptError) as exc:
            service.create(kind="instruction",
                           scope={"kind": "profile", "profileId": bad},
                           title="t", description=None, body=b"body",
                           operation_key=f"k-bad-{abs(hash(str(bad)))}")
        assert exc.value.code == "INVALID_CONTENT", exc.value
        assert port.calls == [], "an unparseable profile id must not reach the port"
    store.close()


# -- no port at all: profile work refuses, library works (G08 support) ---------

def test_without_the_authorisation_port_profile_work_refuses_and_the_library_stands(
        tmp_path, library_service):
    with pytest.raises(PromptError) as exc:
        library_service.create(kind="instruction",
                               scope={"kind": "profile", "profileId": "alpha"},
                               title="t", description=None, body=b"body",
                               operation_key="k-nap")
    assert exc.value.code == "DEPENDENCY_UNAVAILABLE"
    # the refusal is typed and pre-application: nothing was written
    assert library_service.list()["items"] == []
    public = library_service.create(kind="instruction", scope={"kind": "library"},
                                    title="public", description=None,
                                    body=b"public body", operation_key="k-lib")
    assert public["scope"] == {"kind": "library"}
    assert len(library_service.list()["items"]) == 1


# -- two Server data domains never read through --------------------------------

def test_the_same_minted_id_in_two_data_domains_resolves_to_two_different_bodies(
        tmp_path):
    """Resource identity is (serverScope, id): two store files that happen to
    hold the same id must never read through to each other (G06)."""
    shared_id = "prompt_shared-0001"

    def build(name: str, body: bytes) -> "tuple[PromptsStore, PromptsService]":
        path = tmp_path / name / "prompts.db"
        store = PromptsStore(path)
        records = PromptRecords(store, id_factory=lambda: shared_id)
        service = PromptsService(records, server_scope=f"server-{name}",
                                 subject_provider=lambda: f"operator-{name}")
        outcome, response = records.create(
            kind="instruction", scope=PromptScope("library"), title=name,
            description=None, body=body,
            idempotency=(f"operator-{name}|create|library", "k-shared",
                         {"body": body}))
        assert outcome == "applied" and response["id"] == shared_id
        return store, service

    store_a, server_a = build("domain-a", b"body of domain A")
    store_b, server_b = build("domain-b", b"body of domain B")
    try:
        assert base64.b64decode(server_a.get(shared_id)["bodyBase64"]) == (
            b"body of domain A")
        assert base64.b64decode(server_b.get(shared_id)["bodyBase64"]) == (
            b"body of domain B")
        snapshot_a = server_a.resolve_snapshot(
            {"instructions": [{"promptId": shared_id}]})
        snapshot_b = server_b.resolve_snapshot(
            {"instructions": [{"promptId": shared_id}]})
        assert snapshot_a.server_scope == "server-domain-a"
        assert snapshot_b.server_scope == "server-domain-b"
        assert snapshot_a.resolved[0].body != snapshot_b.resolved[0].body
        assert snapshot_a.content_digest != snapshot_b.content_digest
        # the digests match the bodies actually stored in each domain
        assert snapshot_a.resolved[0].sha256 == body_digest(b"body of domain A")
        assert snapshot_b.resolved[0].sha256 == body_digest(b"body of domain B")
    finally:
        store_a.close()
        store_b.close()


def test_a_store_file_never_opens_another_domain_by_id(tmp_path):
    path_a = tmp_path / "a" / "prompts.db"
    path_b = tmp_path / "b" / "prompts.db"
    store_a = PromptsStore(path_a)
    store_b = PromptsStore(path_b)
    service_a = _service(store_a, "op", None)
    service_b = _service(store_b, "op", None)
    try:
        created = service_a.create(kind="instruction", scope={"kind": "library"},
                                   title="only in A", description=None,
                                   body=b"A body", operation_key="k-a-only")
        with pytest.raises(PromptError) as exc:
            service_b.get(created["id"])
        assert exc.value.code == "NOT_FOUND"
        assert str(store_a.path) != str(store_b.path)
    finally:
        store_a.close()
        store_b.close()


# -- identity comes from the context, never from the request --------------------

def test_a_request_declared_identity_is_ignored(plugin_registration, tmp_path):
    _, _, handlers = plugin_registration
    store = PromptsStore(tmp_path / "wire" / "prompts.db")
    records = PromptRecords(store)
    created = handlers["prompts.create"]({
        "requestId": "r" * 12, "kind": "instruction",
        "scope": {"kind": "library"}, "title": "claimed identity",
        "body": base64.b64encode(b"wire body").decode(), "operationKey": "k-id",
        # a hostile client claiming somebody else's identity:
        "owner": "root", "subject": "another-operator",
        "callerSubject": "profile:alpha", "profileId": "alpha"})
    assert created["scope"] == {"kind": "library"}
    rows = list(store.connection.execute(
        "SELECT scope FROM prompt_idempotency WHERE key=?", ("k-id",)))
    scopes = [row["scope"] for row in rows]
    assert scopes == ["server-loopback-operator|create|library"], scopes
    assert not any("root" in scope or "another" in scope or "alpha" in scope
                   for scope in scopes)
    # and the declared profileId did not turn a library write into private work
    record = records.get_record(created["id"])
    assert record.scope == PromptScope("library")
    assert isinstance(record, PromptRecord)
    store.close()


def test_the_published_wire_shape_declares_no_identity_parameter(
        plugin_registration):
    _, registration, _handlers = plugin_registration
    identity_words = ("subject", "owner", "caller", "actor", "user", "token")
    for descriptor in registration.methods:
        declared = set(descriptor.required_params) | set(descriptor.optional_params)
        offenders = [name for name in declared
                     if any(word in name.lower() for word in identity_words)]
        assert offenders == [], (
            f"{descriptor.method_id} accepts a client-declared identity field: "
            f"{offenders}")


def test_an_absent_service_context_subject_refuses_dependency(tmp_path):
    store = PromptsStore(tmp_path / "nosubject" / "prompts.db")
    for provider in (lambda: "", lambda: None, lambda: 42):
        service = PromptsService(PromptRecords(store), server_scope="s",
                                 subject_provider=provider)
        with pytest.raises(PromptError) as exc:
            service.create(kind="instruction", scope={"kind": "library"},
                           title="t", description=None, body=b"body",
                           operation_key="k-nosubject")
        assert exc.value.code == "DEPENDENCY_UNAVAILABLE", exc.value
    assert list(store.connection.execute("SELECT * FROM prompt_records")) == []
    store.close()
