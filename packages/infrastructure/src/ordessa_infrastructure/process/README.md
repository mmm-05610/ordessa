# Process mechanisms

`spawn_process(argv, cwd=..., env=...)` starts exactly one native process with
binary stdin/stdout/stderr pipes, without a shell or directory provisioning.
Arguments and environment are copied; owners supply executable resolution,
validation and any directory setup. Start failures propagate native exceptions.

`SubprocessHandle` preserves the real Popen streams, PID and outcome. `wait`
propagates `subprocess.TimeoutExpired` without killing the process or closing
pipes. `terminate`, `kill` and `send_signal` act on that process; owners choose
cancellation/escalation policy and reap it with `wait`. `close_streams` only
closes its three parent pipe objects and is idempotent; it does not reap or
terminate. Owners must drain stdout/stderr (or use `handle.popen.communicate`)
when needed to prevent pipe-capacity deadlocks. There is no asynchronous
cancellation, process-group supervision, timeout policy or business receipt.

`FrameReader` buffers LF-delimited byte frames, decodes complete UTF-8 frames
and refuses oversize/invalid/truncated frames through the single `ChannelFailure`
identity. The limit is 8 MiB of bytes before LF; CR stripping follows the existing
framing behavior. A failure ends the caller's channel; this primitive provides
no recovery/retry protocol. Pi's 1 MiB Python/TS control channel is a separate
owner protocol and is not replaced here. `Message` preserves the raw mapping
and classifies by method/id field presence, without protocol-schema validation.

All modules have no runtime IO at import; no business owner is introduced.
