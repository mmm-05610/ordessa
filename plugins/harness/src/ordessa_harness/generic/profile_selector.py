from pacthold.extensions import ResourceSelection, SelectorCompatibility, SelectorField
from pacthold_runtime_compat.resource_contracts import AgentBoxProfileV1
class GenericProfileSelector:
    contract_id=AgentBoxProfileV1.contract_id; fields=(SelectorField("profile_id","Profile",kind="select"),); recommended=True
    def __init__(self, store, definition):
        self.store=store; self.definition=definition; self.id=f"{definition.harness_type}-profile-selector"; self.title=f"{definition.display_name} profile"
        self.compatibility=SelectorCompatibility(execution_provider_ids=frozenset({f"{definition.harness_type}-execution"}),harness_types=frozenset({definition.harness_type}),supports_exact_revision=True,recommended=True)
    def prepare(self,parameters,*,execution_id):
        del execution_id
        pid=str(parameters.get("profile_id", "")); value=self.store.get(self.definition.harness_type,pid); ref=self.store.ref(self.definition.harness_type,pid,value["revision"])
        return ResourceSelection(self.contract_id,ref,pid,value["digest"])

    def choices(self, query=None):
        needle = str((query or {}).get("q", "")).lower()
        return tuple({"value": value["profile_id"], "label": f"{value['name']} · r{value['revision']} · {value['digest']}", "description": self.definition.display_name}
                     for value in self.store.list(self.definition.harness_type)
                     if not needle or needle in value["name"].lower() or needle in value["profile_id"].lower())
