"""Run after local installation; no credential, network or native effect."""
import asyncio
from pacthold.decision.offline import run_offline
from decision_runtime.definitions import canonical
if __name__=='__main__':
    print(canonical(asyncio.run(run_offline())).decode())
