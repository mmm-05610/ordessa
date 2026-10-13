"""Original official SDK compatibility cases; fake HTTP, no credentials or network."""
import httpx2
import pytest
from typesafe_sdk import AsyncTypeSafeClient, Choice, RetryPolicy

@pytest.mark.asyncio
@pytest.mark.parametrize('status',[200,429,500])
async def test_T33_T37_sdk_http_count(status):
    calls=[]
    async def transport(req):
        calls.append(req)
        return httpx2.Response(status,json={'model':'jev-1.13.0','usage':{},'answers':{'q':{'type':'choice','choice':'pass','confidence':0.9,'probabilities':{'pass':0.9,'fail':0.1}}}})
    async with AsyncTypeSafeClient(api_key='offline-only',model='jev-1.13.0',retry=RetryPolicy(max_retries=0),transport=httpx2.MockTransport(transport)) as client:
        if status==200:
            res=await client.system_one({'task':'data'},{'q':Choice(criteria={'pass':'yes','fail':'no'})})
            assert res.choices['q'].choice=='pass'
            assert abs(sum(res.choices['q'].probabilities.values())-1)<1e-6
        else:
            with pytest.raises(Exception): await client.system_one({}, {'q':Choice(criteria={'a':None,'b':None})})
    assert len(calls)==1
