# Neutral package locks

The original combined Python 3.12 lock has been partitioned: SDK-only requirements belong to plugins/decision/jev/lockfiles, whose combined files retain the original bytes. Neutral files retain the original versions and hashes of shared/runtime/build/test tools and omit the concrete SDK/HTTP closure. No dependency artifact was rebuilt.

The current W08 offline wheel evidence used the installed nightly test tooling, including iniconfig 2.3.1; the historical lock retains iniconfig 2.3.0. Those are distinct environment receipts. Exact historical hashed-lock installation has not been rerun and is NOT_RUN; the isolated wheel result is not a claim of that lock's reproducibility. See docs/implementation/nightly/evidence/W08.
