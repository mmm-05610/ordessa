/**
 * Ordessa managed-lane Pi bridge extension (Q4 T10, managed lane).
 *
 * What this is: the ONLY Pi-side half of the Ordessa-managed MCP tool
 * bridge. It is a deliberately minimal, Server-supervised component:
 *
 *  - it registers a tool for each entry the Ordessa Server validated
 *    (the tools carried in the `ready` frame of the loopback control
 *    channel, derived from the Server-side McpToolCatalog observation);
 *  - every tool invocation is forwarded over that channel to the Python
 *    peer (`backend/managed/pi_bridge.py`), which runs the double gate
 *    (frozen catalog subset + PermissionAuthority) before the managed
 *    MCP client is touched;
 *  - it NEVER connects to an MCP server, NEVER holds a secretRef, and
 *    NEVER talks to a non-loopback address. The host is the constant
 *    below - not read from the environment. Only the port and the
 *    one-shot binding token come from the environment the Server set
 *    when it launched this Pi process (precedent: the server-compat
 *    subagent bridge's AGENTBOX_BRIDGE_URL/AGENTBOX_BRIDGE_TOKEN).
 *
 * Trust status: this file is executable code loaded by Pi. Per
 * docs/design/mcp/harness-adapters.md it carries an independent version,
 * license and trust registration (see package.json + manifest emitted by
 * scripts/pack.mjs); loading it is not implied by storing an MCP
 * definition. Runtime injection into the Pi process is a C0 dependency
 * (see specs/011-q4-mcp/api-requests.md G9).
 */
import net from "node:net";
import process from "node:process";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/** The only address this extension may ever dial. Deliberately a literal,
 *  not an env value: a direct connection to a non-loopback target is not
 *  expressible in this source (a scan test pins this). */
const LOOPBACK_HOST = "127.0.0.1";

/** Control-channel protocol version accepted by backend/managed/pi_bridge.py. */
const BRIDGE_PROTOCOL = 1;

/** Upper bound for one channel frame (mirrors the Python peer's cap). */
const MAX_FRAME_BYTES = 1024 * 1024;

/** Time the async factory waits for hello->ready before failing closed. */
const HANDSHAKE_TIMEOUT_MS = 10_000;

type BridgeTool = {
	name: string;
	label?: string;
	description?: string;
	inputSchema?: Record<string, unknown>;
};

type PendingCall = {
	resolve: (value: Record<string, unknown>) => void;
	reject: (reason: Error) => void;
};

/** Env contract with the launching Server (pi_bridge.PiBridgeServer.extension_env). */
function requiredEnv(name: string): string {
	const value = process.env[name];
	if (!value) {
		throw new Error(`PERMISSION_REFUSED: ${name} is not set; the Ordessa Pi bridge has no Server-side registration to bind to`);
	}
	return value;
}

class BridgeChannel {
	private readonly port: number;
	private readonly token: string;
	private socket: net.Socket | null = null;
	private buffer = "";
	private bound = false;
	private dead = false;
	private nextCallId = 1;
	private readonly pending = new Map<string, PendingCall>();
	private ready: ((value: BridgeTool[]) => void) | null = null;
	private readyTools: BridgeTool[] | null = null;

	constructor() {
		const portText = requiredEnv("ORDESSA_PI_BRIDGE_PORT");
		const port = Number.parseInt(portText, 10);
		if (!Number.isInteger(port) || port <= 0 || port > 65535) {
			throw new Error(`PERMISSION_REFUSED: ORDESSA_PI_BRIDGE_PORT is not a valid TCP port: ${portText}`);
		}
		this.port = port;
		this.token = requiredEnv("ORDESSA_PI_BRIDGE_TOKEN");
	}

	/** Opens the control channel, performs the one-shot token-bound hello
	 *  and resolves with the Server-validated tool list once `ready` lands.
	 *  Fails closed on any refusal, malformed frame or timeout. */
	connect(): Promise<BridgeTool[]> {
		return new Promise<BridgeTool[]>((resolve, reject) => {
			const handshakeTimer = setTimeout(() => {
				this.dead = true;
				this.socket?.destroy();
				reject(new Error("PERMISSION_REFUSED: bridge handshake timed out; refusing to start without a validated tool catalog"));
			}, HANDSHAKE_TIMEOUT_MS);
			handshakeTimer.unref?.();

			this.ready = (tools) => {
				clearTimeout(handshakeTimer);
				resolve(tools);
			};

			// The host argument is the LOOPBACK_HOST literal - there is no
			// code path in this file that supplies any other host.
			const socket = net.connect({ host: LOOPBACK_HOST, port: this.port });
			this.socket = socket;
			socket.on("error", (err) => {
				clearTimeout(handshakeTimer);
				this.failAll(new Error(`PERMISSION_REFUSED: bridge control channel error: ${(err as Error).message}`));
				reject(err);
			});
			socket.on("close", () => {
				clearTimeout(handshakeTimer);
				this.failAll(new Error("bridge control channel closed"));
			});
			socket.on("data", (chunk: Buffer) => this.onData(chunk));
			socket.on("connect", () => {
				this.WriteLine({
					type: "hello",
					proto: BRIDGE_PROTOCOL,
					token: this.token,
					pid: process.pid,
				});
			});
		});
	}

	private WriteLine(frame: Record<string, unknown>): void {
		if (!this.socket || this.dead) {
			throw new Error("bridge control channel is not live");
		}
		this.socket.write(`${JSON.stringify(frame)}\n`);
	}

	private onData(chunk: Buffer): void {
		this.buffer += chunk.toString("utf8");
		if (Buffer.byteLength(this.buffer, "utf8") > MAX_FRAME_BYTES) {
			this.failAll(new Error("PERMISSION_REFUSED: bridge frame exceeded the size cap"));
			this.socket?.destroy();
			return;
		}
		let idx: number;
		while ((idx = this.buffer.indexOf("\n")) >= 0) {
			const line = this.buffer.slice(0, idx).replace(/\r$/, "");
			this.buffer = this.buffer.slice(idx + 1);
			if (line.length > 0) this.onFrame(line);
		}
	}

	private onFrame(line: string): void {
		let frame: Record<string, unknown>;
		try {
			frame = JSON.parse(line) as Record<string, unknown>;
		} catch {
			this.failAll(new Error("PERMISSION_REFUSED: malformed frame on the bridge control channel"));
			return;
		}
		if (frame.type === "ready" && this.ready) {
			this.bound = true;
			const tools = (Array.isArray(frame.tools) ? frame.tools : []) as BridgeTool[];
			this.readyTools = tools;
			const cb = this.ready;
			this.ready = null;
			cb(tools);
			return;
		}
		if (frame.type === "error") {
			this.failAll(new Error(`${String(frame.code ?? "PERMISSION_REFUSED")}: ${String(frame.reason ?? "bridge registration refused")}`));
			this.socket?.destroy();
			return;
		}
		if (frame.type === "result") {
			const pending = this.pending.get(String(frame.id));
			if (pending) {
				this.pending.delete(String(frame.id));
				pending.resolve(frame);
			}
			return;
		}
	}

	/** Rejects every in-flight and future call: fail closed, never hang. */
	private failAll(reason: Error): void {
		this.dead = true;
		for (const [, pending] of this.pending) pending.reject(reason);
		this.pending.clear();
	}

	/** One validated tools/call roundtrip over the control channel. */
	call(toolName: string, params: Record<string, unknown>, toolCallId: string): Promise<Record<string, unknown>> {
		if (this.dead || !this.bound) throw new Error("bridge control channel is not bound; refusing to call without a live Server gate");
		const id = `call-${this.nextCallId++}`;
		return new Promise<Record<string, unknown>>((resolve, reject) => {
			this.pending.set(id, { resolve, reject });
			try {
				this.WriteLine({ type: "call", id, tool: toolName, params, toolCallId });
			} catch (err) {
				this.pending.delete(id);
				reject(err as Error);
			}
		});
	}

	close(): void {
		try {
			if (this.socket && !this.dead) this.WriteLine({ type: "bye" });
		} catch {
			// best effort; the close handler fails everything else over.
		}
		this.socket?.end();
		this.socket?.destroy();
	}

	liveTools(): string[] {
		return (this.readyTools ?? []).map((tool) => tool.name);
	}

	isBound(): boolean {
		return this.bound && !this.dead;
	}
}

export default async function (pi: ExtensionAPI): Promise<void> {
	const channel = new BridgeChannel();
	let tools: BridgeTool[];
	try {
		tools = await channel.connect();
	} catch (err) {
		channel.close();
		throw err;
	}

	for (const tool of tools) {
		if (!tool.name) continue;
		pi.registerTool({
			name: tool.name,
			label: tool.label ?? tool.name,
			description: tool.description ?? `Ordessa-managed MCP tool ${tool.name} (executed behind the Server-side permission gate)`,
			// The Server-observed JSON Schema is passed through verbatim; a
			// plain schema object is what TypeBox produces at runtime too.
			parameters: (tool.inputSchema ?? { type: "object", properties: {} }) as never,
			async execute(toolCallId: string, params: Record<string, unknown>) {
				const response = await channel.call(tool.name, params ?? {}, toolCallId);
				if (response.ok !== true) {
					throw new Error(`${String(response.code ?? "PERMISSION_REFUSED")}: ${String(response.reason ?? "the Server refused this tool call")}`);
				}
				const result = (response.result ?? {}) as { content?: unknown[]; details?: unknown };
				return {
					content: Array.isArray(result.content) ? result.content : [{ type: "text", text: "" }],
					details: { ordessaBridge: true, ...(typeof result.details === "object" && result.details !== null ? result.details : {}) },
				};
			},
		});
	}

	// Observability hook: `/ordessa_mcp_status` reports, via ctx.ui.notify
	// (delivered as an `extension_ui_request` event in RPC mode), whether the
	// control channel is bound and which Server-validated tools are live in
	// Pi's own tool registry. It changes nothing and authorizes nothing.
	pi.registerCommand("ordessa_mcp_status", {
		description: "Report the Ordessa managed MCP bridge channel state and registered tools",
		handler: async (_args, ctx) => {
			const registered = pi
				.getAllTools()
				.map((info: { name?: string }) => info.name)
				.filter((name: string | undefined): name is string => typeof name === "string");
			ctx.ui.notify(
				`ordessa-mcp-bridge bound=${channel.isBound()} readyTools=[${channel.liveTools().join(",")}] allTools=[${registered.join(",")}]`,
				"info",
			);
		},
	});

	pi.on("session_shutdown", async () => {
		channel.close();
	});
}
