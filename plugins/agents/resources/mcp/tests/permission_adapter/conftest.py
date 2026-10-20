"""Fixtures/helpers live in pa_shared (unique module name: bare `conftest` imports collide across sibling test dirs)."""
from pa_shared import *  # noqa: F401,F403
