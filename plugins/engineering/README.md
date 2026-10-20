# Engineering plugin slot

This directory is the confirmed structural home for Engineering business plugins and contributions. It is an extension slot, not an implemented plugin, public API, package, registry, or runtime capability.

When an implementation is authorized, it may depend on public Engineering/plugin contracts and injected capabilities. It must not depend on `apps/*` internals, read a host database directly, or become a coordinator for unrelated domains. Existing Engineering library, methods, workflows, and persistence remain owned by `packages/engineering`; this slot does not move or duplicate them.

Current status: no plugin implementation or registration is present here. Plugin APIs, packaging, and runtime composition are not established.
