class GenericProfileManager:
    def __init__(self,store,definition): self.store,self.definition=store,definition; self.harness_id=definition.harness_type
    def descriptor(self): return {"id":self.harness_id,"display_name":self.definition.display_name,"version":self.definition.identity.version,"status":"ready","supported":True}
    def list_profiles(self): return tuple(self.store.list(self.harness_id))
    def get_profile(self,profile_id,revision=None): return self.store.get(self.harness_id,profile_id,revision)
    def create(self,data): return self.store.put(self.harness_id,data)
    def update(self,profile_id,data,expected_revision): return self.store.put(self.harness_id,{**data,"profile_id":profile_id},expected_revision)
    def disable(self,profile_id,revision): return self.update(profile_id,{"disabled":True},revision)
