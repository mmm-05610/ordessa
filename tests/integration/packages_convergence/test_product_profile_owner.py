"""Product Profile fixture now calls the actual formal public service/ports.

This qualifies only Profile creation/pin/replay, not legacy staged Unit assembly.
"""
import importlib.util
from pathlib import Path
import pytest
from ordessa_execution_agents.profiles import ProfileService,ProfileValidationError


def test_product_profile_owner_uses_public_store_admission_and_pinned_validator(tmp_path):
    root=Path(__file__).resolve().parents[3]
    spec=importlib.util.spec_from_file_location('product_profile_fixture',root/'apps/cli/tests/integration/profile_test_owner.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    class Policy:
        def admit_invoke(self,*args):return True
        def admit_object_access(self,*args):return True
    definition={'environmentNamespace':'env','definitionId':'fixture','revision':'1'}
    original=module.profile_owner(tmp_path/'profiles.sqlite','env','principal',Policy(),definition)
    body={'schemaVersion':'1','harnessDefinitionRef':definition,'declarations':[]}
    try:
        assert type(original.service) is ProfileService
        request=original.service.request_key('create-profile')
        first=original.service.create(profile_id='profile',name='Profile',content=body,request=request)
        assert original.service.create(profile_id='profile',name='Profile',content=body,request=request)==first
        assert original.service.get_revision(first.current_revision).ref==first.current_revision
        changed={**body,'harnessDefinitionRef':{**definition,'revision':'2'}}
        with pytest.raises(ProfileValidationError):
            original.service.create(profile_id='other',name='Other',content=changed,request=original.service.request_key('foreign-pin'))
        assert len(original.service.list())==1
    finally:original.close()
