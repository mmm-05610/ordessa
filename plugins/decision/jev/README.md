# Jev Decision provider

The sole Jev adapter is this independent ordessa-decision-jev distribution, imported as ordessa_decision_jev. It depends on the public decision_runtime contracts and pinned official TypeSafe SDK0.7.2. Host assembly injects configuration and a secret resolver; tests use fake transport only. There is no retired decision_runtime.providers.jev alias or fallback.

OpenCode Zen is a model provider usable through this adapter; it does not select an OpenCode Harness. The preparation's bounded free HTTP probe does not establish SDK/product wiring or decision quality. Default settings remain explicit historical TypeSafe configuration; Zen requires verified host-selected configuration, no implicit backend/paid switch. No production credential or new persistent access is configured here. Laya remains NOT_ENABLED without an implementation.

Run .venv-nightly/bin/python -m pytest -q plugins/decision/jev/tests from the worktree. Wheel isolation and current acceptance are recorded in docs/implementation/nightly/evidence/W08; do not infer them from this directory's existence.
