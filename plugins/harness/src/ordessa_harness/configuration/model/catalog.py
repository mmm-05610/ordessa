"""Canonical model protocol declarations over the configured Harness directory.

Declarations are not availability evidence: the brand runtime still validates
version, exact live model routing and owner before admitting an application.
"""
from .common import DIALECTS


class ModelConfigurationCatalog:
    def __init__(self, directory):
        if directory is None:
            raise ValueError("Configured Harness directory required")
        self.directory = directory

    def __contains__(self, harness_id):
        return harness_id in self.directory

    def registered(self):
        return self.directory.registered()

    def get(self, harness_id):
        return self.directory.get(harness_id)

    def wire_protocols(self, harness_id):
        if harness_id not in self.directory:
            return {}
        return {protocol: "declared" for protocol in DIALECTS.get(harness_id, {})}
