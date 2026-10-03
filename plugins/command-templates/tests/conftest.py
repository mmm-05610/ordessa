"""Shared fixtures: a fresh private store, service, and a fake project port.

Every test builds its store from an explicit ``tmp_path`` root — the domain never
reaches for a host data root or HOME on its own.
"""
from __future__ import annotations

import pytest

from ordessa_command_templates.api.dto import Assignment, ParameterSpec, Target
from ordessa_command_templates.expansion.renderer import ProjectRef
from ordessa_command_templates.library import CommandTemplateService, TemplateStore


class FakeProjectResolver:
    """An authorized project port: maps a known reference to a stable display."""

    def __init__(self, known=None):
        self.known = known or {"alpha": ProjectRef(display="Alpha Project", stable_id="proj-alpha")}
        self.calls: "list[tuple[str, str]]" = []

    def resolve(self, principal, reference):
        self.calls.append((principal, reference))
        return self.known.get(reference)


@pytest.fixture
def store(tmp_path):
    st = TemplateStore.for_root(tmp_path / "private-root")
    st.initialize()
    return st


@pytest.fixture
def resolver():
    return FakeProjectResolver()


@pytest.fixture
def service(store, resolver):
    return CommandTemplateService(store, project_resolver=resolver)


@pytest.fixture
def bare_service(store):
    """A service with no project port — project-ref renders must then refuse."""
    return CommandTemplateService(store)


def make_template(svc, *, principal="u1", tid="tmpl.demo", slug="demo",
                  body="Hello {{name}}", parameters=None, approve=True):
    svc.create(principal=principal, template_id=tid, display_name=slug.title(),
               slug=slug, operation_key=f"create:{tid}")
    if parameters is None:
        # Derive one required string parameter per placeholder in the body.
        from ordessa_command_templates.expansion.parser import Placeholder, parse
        names = sorted({s.name for s in parse(body).segments if isinstance(s, Placeholder)})
        parameters = [ParameterSpec(n, "string", True) for n in names]
    svc.save_revision(principal=principal, template_id=tid, body=body, parameters=parameters,
                      expected_version=1, operation_key=f"rev1:{tid}")
    if approve:
        svc.approve(principal=principal, template_id=tid, revision=1,
                    expected_version=2, operation_key=f"app1:{tid}")
    return svc.store.get_template(tid)


def enable(svc, *, principal="u1", tid, revision, scope="user-global", identity=None,
           harness=None):
    assignment = Assignment(
        scope=scope, scope_identity=identity or principal, template_id=tid,
        state="enable", pinned_revision=revision, harness_id=harness)
    return svc.set_assignment(principal=principal, assignment=assignment,
                              expected_version=None, operation_key=f"asg:{scope}:{tid}")
