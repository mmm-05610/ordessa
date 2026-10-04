# 013 stage2 partial checkpoint

Source checkpoint follows aa558c8ba9; commands cwd is implementation tree. Tests serial, Python3.12.14/Node22.22.1/Vitest4.1.10. Source SHA fixed by stage commit containing this record; do not confuse with pre-edit baseline.

| command | log | exit/result | scope |
| --- | --- | --- | --- |
| .venv/bin/python -m pytest plugins/agent/backend/tests -q -p no:cacheprovider | agent-backend-stage2.txt | 0,28P | owner/journal isolated/new-root only |
| vitest run --root plugins/agent/contracts --maxWorkers=1 | agent-contracts-stage2.txt | 0,33P | owner projections; not product transport |
| vitest run --root plugins/profile/frontend --maxWorkers=1 | edit-consumer-suite.txt | 0,24P | resource public editor/task/query |
| vitest run --root plugins/chat/frontend --maxWorkers=1 | chat-draft-suite.txt | 1,89P2F | preserved failures |
| same Chat command | chat-draft-suite-rerun.txt | 0,92P | editor actual consumer; fourth pane replacement regression added |
| .venv/bin/python -m pytest packages/backend/pacthold/tests/environment/test_closeout_environment_dispatch.py packages/backend/persistence-sqlite/tests/test_closeout_dispatch_claim.py -q -p no:cacheprovider | red-environment-dispatch.txt | 1,9F1P | primary red-first before kernel implementation |
| npm run typecheck | stage2-typecheck.txt / stage2-typecheck-rerun.txt | 1/1 | two rounds honest unfinished consumer errors |

Original three dirty tracked files preserved and excluded. Domain journal eight tests include real child SIGKILL; native effect witness is a controlled separate file, not installed brand execution. No real models, data, service intervention, system installation or push.
