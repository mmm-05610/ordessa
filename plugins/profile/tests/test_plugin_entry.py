"""T20 — pacthold SDK plugin entry (G8).

The distribution loads as a well-formed plugin through the real pacthold
loader; malformed descriptors and duplicate ids are refused by the loader.
"""
from __future__ import annotations

import importlib.metadata
import sys

import pytest
from pacthold.extensions import (
    ExtensionCatalogBuilder,
    PluginCompatibilityError,
    PluginDescriptor,
    PluginRegistration,
    load_installed_plugins,
)
from pacthold.work_core.registry import ExtensionRegistry

from ordessa_profile import ProfilePlugin, create_plugin


def test_descriptor_and_build_are_well_formed(tmp_path):
    plugin = create_plugin()
    descriptor = plugin.descriptor()
    assert isinstance(descriptor, PluginDescriptor)
    assert descriptor.id == "profile"
    assert descriptor.api_version == 1
    registration = plugin.build(type(
        "Ctx", (), {"agent_box_version": "test",
                    "agent_box_home": tmp_path,
                    "plugin_data_dir": tmp_path})())
    assert isinstance(registration, PluginRegistration)


def test_loads_through_pacthold_entry_point_discovery():
    """The installed distribution exposes the real entry point and the
    pacthold loader accepts it (component slots intentionally empty this
    wave; composition is the serial integration dependency)."""
    group = importlib.metadata.entry_points()
    try:
        eps = group.select(group="agent_box.plugins")
    except AttributeError:
        eps = group.get("agent_box.plugins", [])
    profile_eps = [ep for ep in eps if ep.name == "profile"]
    assert profile_eps, "entry point 'profile' missing from agent_box.plugins"
    registry = ExtensionRegistry()
    report = load_installed_plugins(registry, entry_points=tuple(profile_eps))
    assert len(report.ready) == 1 and not report.failed
    assert report.ready[0].descriptor.id == "profile"


def test_loader_refuses_incompatible_api_version():
    class BadApiPlugin(ProfilePlugin):
        def descriptor(self):
            descriptor = super().descriptor()
            return PluginDescriptor(
                id=descriptor.id, display_name=descriptor.display_name,
                version=descriptor.version, api_version=99)

    registry = ExtensionRegistry()
    report = load_installed_plugins(
        registry,
        entry_points=[_static_ep("badapi", BadApiPlugin)],
    )
    assert not report.ready and len(report.failed) == 1


def test_loader_refuses_duplicate_plugin_ids():
    registry = ExtensionRegistry()
    report = load_installed_plugins(
        registry,
        entry_points=[_static_ep("profile", ProfilePlugin),
                      _static_ep("profile2", ProfilePlugin)],
    )
    assert len(report.ready) == 1  # the first registration wins
    assert len(report.failed) == 1  # the duplicate is refused
    assert "duplicate plugin id" in report.failed[0].error


def _static_ep(name: str, plugin_class):
    """A minimal entry-point stand-in loading an in-memory factory."""
    import importlib

    class StaticEntryPoint:
        _module = sys.modules[__name__]
        value = f"{__name__}#factory"

        @property
        def name(self):
            return name

        def load(self, *, group=None):
            return plugin_class

    return StaticEntryPoint()
