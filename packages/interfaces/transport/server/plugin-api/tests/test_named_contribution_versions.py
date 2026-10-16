"""Carrier version grammar accepts exact independent owner contracts."""
import pytest
from server_plugin_api import Contribution,ContributionPointSpec,ServerContributionHandler
from server_plugin_api.errors import ContributionDeclarationError

class Handler(ServerContributionHandler):
    def stage(self,*args): pass
    def commit(self,*args): pass
    def rollback(self,*args): pass

@pytest.mark.parametrize('version',['v1','v12','harness-definition/1','resource.material/2'])
def test_opaque_carrier_and_spec_accept_exact_versioned_role(version):
    assert Contribution('execution.harness.definitions',version,()).api_version==version
    assert ContributionPointSpec('execution.harness.definitions',version,Handler()).api_version==version

@pytest.mark.parametrize('version',['','v0','V1','harness-definition/0','harness-definition/01',
    'Harness-definition/1','harness-definition//1','../1','harness-definition/1 ',None])
def test_opaque_carrier_and_spec_refuse_malformed_version(version):
    with pytest.raises(ContributionDeclarationError):
        Contribution('execution.harness.definitions',version,())
    with pytest.raises(ContributionDeclarationError):
        ContributionPointSpec('execution.harness.definitions',version,Handler())
