# Engineering84 public receiving contract

The source checkpoint is84; operation registry revision is83. Method policy,
operation input/output schemas and foreign implementation facts did not change.
This checkpoint does not publish candidate2.6 or accept an implementation.

```python
from ordessa_engineering.application.assembly import bind_execution_dispatch
from ordessa_engineering.adapters.native_records import RecordedDispatchExecution
from ordessa_engineering.adapters.native_records.recorded_dispatch import engineering_effect_write_guard_factory
```

Existing public construction remains:

```python
engineering_effect_write_guard_factory(dispatch_owner, context, records, blobs)
RecordedDispatchExecution(records, unit_instance, authorized_lease, blobs,
    query_factory=None, *, effect_write_guard_factory=None)
bind_execution_dispatch(service, *, execution, selection, source_snapshots,
    history_sources)
```

`dispatch_owner` is the original Engineering dispatch instance from its owner
assembly. `records`, `blobs`, factory/access, Unit and lease must remain their
actual original instances. Consumers must obtain those instances from their
owners; they must not extract private Service fields, construct a second
Engineering authority, or substitute the retired dispatch route. A complete
Server production binder/provider caller was not established by this batch.
The interfaces group retains that explicit actual-instance receiving task.

The fixed factory retains the original owner and stores no construction-time
CommandContext. The existing constructor `context` argument carries no cached
permission and may be None during trusted composition. Each send must provide
the actual currently issued context to:

```python
execution.guard_effect_handoff(context, binding, *, access, timeout=60)
```

The Engineering application enters this context manager around the original
`execution.send`. Consumers do not move, serialize, inspect or choose its
token. The adapter uses only the public original Unit property
`unit_instance.effect_write_thread`. The original Unit fixed callback verifies
exact native Unit/operation/input and returns its original EffectWriteGuard.
The SDK cut calls:

```python
ImplementationDispatch.acquire_effect_write(context, binding, identity,
    deadline, *, handoff)
```

The handoff keyword is mandatory. The implementation consumes the exact opaque
Interfaces token before the original access, selection, intent/evidence,
control, action-consumption and SQLite byte-write guards. The token binds the
exact32-byte DispatchBinding digest, action-instance tuples, original command
operation/scope/credential epoch, actual Thread and admission lifetime. Its
pending expiry is at most60 seconds; the original byte deadline remains at
most10 seconds. No entire Context is copied or thread check removed.

Authority and Engineering write locks end before model/response wait. The
original caller admission is revalidated before canonical receipt COMMIT.
Canonical dispatch uses an internal receipt continuation; independent public
reconcile still checks its own original operation. If access is revoked during
wait, the owner refuses the post-send write and retains possibly_written and
consumed budget. UNKNOWN never refunds or replays. Native completion continues
to report accepted=false and engineering_completed=false until the method's
actual acceptance constraints succeed.

Qualification: eight current source receiving cases,35 installed contract and
handoff cases, and two installed Engineering/actual original LocalUnit+SDK
controlled-peer cases passed, with no failures or skips. Source and installed
cases overlap. All266 source/stage/wheel/private-install Python+JSON payloads
match; inspected Engineering origins were inside the private installation.
These controlled cases include explicit business/selection/approval fixtures
and a synthetic successful receipt/history in the continuation case. They
are not a real-model or whole-product method chain. No Pi/JEV/model call ran.

Engineering84 wheel SHA256:
`a1ab22f9def0522bd079418e4b4b39ade505cf2f03a3f1edddc7fdb4fb0172f0`.
Source fingerprint:
`ea8cd341714f00b3c671e13be6888b9768f0bac6c7dabe6d06e0b9c121eec2d7`.
Registry digest:
`sha256:5611a731511392d9ada9c44813f467cd6ac67d6e77c8279283c5564eefc1b176`.
Engineering83 preliminary wheel is superseded and must not be adopted as84.

Remaining verification belongs to the coordinated formal product case: matched
fresh consumer dependencies, actual Server canonical binder and business Work
instances, independent reviewer role/trust, actual Pi/JEV and acceptance.
An explicit inherited delegated child-coroutine inertness case remains with
Interfaces; its inactive-first cleanup is preserved. Pre-send refusal after
the two durable commits remains conservative and creates no never-sent proof.
