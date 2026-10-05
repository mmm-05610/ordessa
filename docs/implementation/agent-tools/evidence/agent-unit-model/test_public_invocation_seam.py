"""AU001 public deployment seam; controlled evidence, no native execution."""
import pytest

from pacthold.agents import invocation, public


@pytest.mark.parametrize("name", (
    "InvocationIssuer", "InvocationGrant", "InvocationAuthorityPort",
    "InvocationCurrentState", "InvocationCurrentStatePort",
))
def test_public_authority_types_keep_original_identity(name):
    assert name in public.__all__
    assert getattr(public, name) is getattr(invocation, name)


def test_public_issuer_does_not_supply_missing_authority():
    with pytest.raises(public.InvocationAuthorityRefused):
        public.InvocationIssuer(None, None, None)


def test_public_verifier_does_not_supply_missing_continuation():
    verifier = public.InvocationVerifier(lambda *args: None)
    with pytest.raises(public.InvocationAuthorityRefused):
        verifier.verify_continuation(None, "start", {}, {}, "digest")
    with pytest.raises(public.InvocationAuthorityRefused):
        verifier.verify_claimed_query(None, {}, {}, "digest", operation_kind="prepare")
