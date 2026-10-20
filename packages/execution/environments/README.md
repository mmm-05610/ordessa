# Execution Environment API

`ordessa_environments` owns resource identity, observations, recorded Uses, and
provider-neutral process and file interfaces. Concrete behavior belongs to the
selected provider package. The Local provider is a development process runner
and reports `isolation="none"`; it does not provide a security sandbox.

## Managed resource path

Create one manager with an explicit `SQLiteEnvironmentStore` and provider map.
`create(provider_id, reference)` creates a resource through that provider;
`get(identity)` issues a fresh view from that manager and `list()` returns
stored snapshots. Use `instance.inspect()` to ask the provider for a fresh
backend observation. `register(provider_id, backend_id)` is for explicitly
mapping an already existing backend ID into this store after provider
inspection; it does not create a backend resource.

An instance acquires an `EnvironmentUse`. The Use exposes `files` and
`execution.start(ProcessRequest)`. Each returned process handle provides async
`write_stdin`, `read_stdout`, `read_stderr`, and `wait_exit`, plus `observe`,
`cancel`, and synchronous `release`.

The [Local example](examples/local_roundtrip.py) shows the same database opened
by two managers, two explicitly shared Uses, real stdin/stdout/stderr, a
confirmed process exit and resource release. Install the environments package,
its Infrastructure dependency, and the Local provider using the repository's
[Python workspace instructions](../../../docs/reference/baseline.md), then run
it with an absolute state directory:

```sh
python ./packages/execution/environments/examples/local_roundtrip.py /var/tmp/ordessa-environment-example
```

The example leaves its SQLite registry and working files under the supplied
directory after release.

## Lifecycle and refusal rules

- `EnvironmentUse.release()` does not stop or delete the environment. It
  refuses until every process it started has an actual `exited` observation
  and its process transport has been explicitly released.
- `ProcessHandle.cancel()` reports a cancellation request, not proof of exit.
  Observe or wait for `exited` before releasing the process and Use. An
  `unknown` result stays fenced.
- Releasing the Use leaves the resource and files intact. Operations such as
  resource `stop()` and `delete()` are separate explicit operations; Local
  implements neither.
- An instance view belongs to the manager that issued it. Cross-manager views,
  stale generations, and unresolved `UNKNOWN` outcomes are refused at the
  relevant manager/use boundary. Do not reconstruct a Use or retry an unknown
  operation.
- There is no `EnvironmentManager.close()`. The caller owns each process and
  Use handle it acquires and releases.

## OpenShell provider

OpenShell uses the same EnvironmentManager, instance, Use, ProcessRequest, and
process-handle contract. Its configuration requires an explicit workspace,
canonical absolute backend `file_root`, gateway binding reference, and an
already authenticated `SandboxClient` plus its matching same-authority RPC
stub from composition. The create reference must provide `image`, `policy`,
and an independent `main_command`; the provider does not choose defaults,
credentials, or start services. A configured file helper must pass its probe
before file capability is reported.

The existing descriptor reports per-process kill, process reconnect, and a
use-isolation boundary as unavailable. In particular, cancelling an RPC stream
or releasing its transport cannot be treated as confirmed remote process exit.
Current dependency and runtime prerequisites are recorded in the bounded
[OpenShell check](../../../docs/implementation/packages-convergence-20261012/execution/environment-api/OPEN-SHELL-CURRENT-CHECK.md).
The prior read-only history remains at
[`READONLY-STATUS.md`](../../../docs/implementation/packages-convergence-20261012/execution/real-validation/openshell/READONLY-STATUS.md).
