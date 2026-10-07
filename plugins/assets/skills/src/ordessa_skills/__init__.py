"""Ordessa Skills: versioned skill content, bounded import, auditable projection.

One domain, per docs/design/skills-v2/plan.md 目标目录: ``api`` (pure types),
``formats.agent_skills`` (the internal kind handler), ``library`` (stores,
catalog, import sessions), ``assignments``, ``native_discovery``,
``profile_contribution``, ``harness_adapters`` and ``plugin`` (registration).
This slice carries ``api`` and ``formats`` only; the remaining areas land with
their own migration tasks. The core never imports Chat, Profile, Harness or
host internals.
"""
