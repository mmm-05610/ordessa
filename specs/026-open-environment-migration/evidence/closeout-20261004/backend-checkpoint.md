# Backend checkpoint 2026-10-04

cwd: /home/maoqh/projects/ordessa/worktree/026-open-environment-migration
source: this checkpoint commit; parent b9c1b3bbe918f1a825518bea8135d07e2b08ebc4. Python 3.12.14; Node22.22.1; Vitest4.1.10. Only primary tests, serial.

| Command | exit | result | evidence | boundary |
| --- | --- | --- | --- | --- |
| `.venv/bin/python -m pytest packages/backend/pacthold/tests/environment packages/backend/persistence-sqlite/tests plugins/agent/backend/tests products/server/tests/test_closeout_agent_configuration.py products/server/tests/test_closeout_submission_composition.py products/server/tests/test_closeout_configuration_observation.py apps/server/tests/platform/test_closeout_core_binding_environment.py -q -p no:cacheprovider` | 0 | 137P/0F/0E/0skip | backend-controlled-checkpoint.txt | real owners/kernel/wire, external controlled native edge |
| Same plus `products/server/tests/test_closeout_managed_transport.py` after exit/release fixes | 0 | 147P/0F/0E/0skip | backend-owner-exit-final.txt | actual retirement blockers and explicit resource cleanup |
| `.venv/bin/python -m pytest products/server/tests/test_closeout_product_crash.py -q -p no:cacheprovider` | 0 | 5P/0F/0E/0skip | product-five-kill.txt | five real product SIGKILL windows, fresh OS owner, no new native effects |
| `npm ci` | 0 | dependency install only | npm-ci.txt | local workspace assets, not system installation |
| `npm test` | 1 | 37/46 suites green; 9 failed, asset skips remain | npm-aggregate.txt | source/Electron controlled regression, not clean release or real GUI/model |
| `node --test packages/frontend/workbench/tests/` | 0 | 7P/0skip | workbench-token-rerun.txt | corrected moved checkout discovery; original assertions preserved |
| `vitest run --root plugins/agent/contracts --maxWorkers=1` | 1 | 38P1F | contracts-wire-observer-red.txt | real helper + controlled wire/session boundary; generation cleanup red retained |

Earlier red logs are retained. SQL markers are taken over only within the product after the host acquires its exclusive data-root process lock; standalone store behavior and frozen StorePort remain unchanged. Request lookup is separate from effects. RAW pending-resource closures are in-memory and do not claim reliable crash recovery. Frontend durable capture/send and ACP fact-owner migration are still unfinished; five backend windows do not complete all C2 frontend requirements.
