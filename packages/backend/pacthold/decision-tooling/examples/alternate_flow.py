import asyncio
from pacthold.decision.offline import run_offline
from pacthold.decision.contracts import canonical
if __name__=='__main__':
    print(canonical(asyncio.run(run_offline(alternate=True,action='create'))).decode())
