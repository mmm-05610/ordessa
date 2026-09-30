"""Product-owned optional edges: Skills consumes this round's Profile and policy."""
from dataclasses import replace

from ordessa_skills.plugin import SkillsServerPlugin
from ordessa_profile.plugin import ProfilePluginServices


class ProductSkillsPlugin(SkillsServerPlugin):
    def descriptor(self):
        return replace(super().descriptor(), requires=("ordessa.workspace", "ordessa.profile"))

    def build(self, context):
        # Resolve on every activation, not once against a disposed old round.
        self._profile_services = ProfilePluginServices(context.ports["profile.core"])
        return super().build(context)
