"""Concrete Harness credential selections cannot restore generic Work refs."""
import dataclasses
import pytest
from ordessa_agents.harness.configuration.selection import CredentialSelection,SelectorField
from ordessa_agents.harness.definitions import NativeCredentialRef,NativeProfileRef


def test_credential_selection_preserves_original_native_identity_and_metadata():
    ref=NativeCredentialRef('codex-login','codex-login/default',metadata={'revision':'1'})
    result=CredentialSelection('contract',ref,'requested','exact')
    assert result.ref is ref and result.ref.metadata['revision']=='1'
    assert result.requested_summary=='requested' and result.exact_summary=='exact'
    field=SelectorField('mode','Credential',kind='select',default='official',required=False)
    assert dataclasses.asdict(field)=={'key':'mode','label':'Credential','kind':'select',
        'default':'official','required':False,'help':''}
    with pytest.raises(dataclasses.FrozenInstanceError):result.ref=ref


def test_profile_or_untyped_ref_cannot_select_a_credential():
    for ref in (NativeProfileRef('pi','profile'),object(),{'provider':'codex-login'}):
        with pytest.raises(ValueError,match='concrete native credential'):
            CredentialSelection('contract',ref)


def test_kernel_has_no_retired_selection_exports_or_definitions():
    import pacthold.extensions as public
    import pacthold.extensions.api as api
    for name in ('ResourceSelection','SelectorField','ResourceSelector'):
        assert not hasattr(public,name) and not hasattr(api,name)
