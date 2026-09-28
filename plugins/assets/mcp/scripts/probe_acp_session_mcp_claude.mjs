#!/usr/bin/env node
/**
 * Q4 T00/V00 controlled probe (Claude brand): does the pinned
 * `@agentclientprotocol/claude-agent-acp` adapter consume
 * `session/new.mcpServers`, and how does it hand them to the Claude backend?
 *
 * Companion to probe_acp_session_mcp.mjs (Codex brand). Same isolation rules:
 * everything under an isolated --work dir, fake HOME, no registry/network
 * except the script's own 127.0.0.1 fake MCP server, process-group teardown.
 *
 * Materials must be supplied offline (tree tgz or npm cache extraction):
 *   --tgz-acp       @agentclientprotocol/claude-agent-acp-0.81.2.tgz
 *   --tgz-sdk       @agentclientprotocol/sdk-1.5.0.tgz
 *   --tgz-agent-sdk @anthropic-ai/claude-agent-sdk-0.3.280.tgz
 *   --tgz-zod       zod-4.6.5.tgz
 *
 * First-hand injection surface (claude-agent-acp 0.81.2 dist/acp-agent.js):
 *   - backend binary: env CLAUDE_CODE_EXECUTABLE (515-517, used at 6416).
 *   - session/new.mcpServers -> SDK options.mcpServers dict (6214-6236, 6390-6393);
 *     sdk.mjs then spawns the CLI with argv `--mcp-config {"mcpServers":{...}}`
 *     (and the CLI-side `--strict-mcp-config` flag exists in the SDK arg builder
 *     but the adapter does not set it -- witness proves per-run presence/absence).
 * Exit codes: 0 all grids observed, 1 assertion failure, 2 infra error.
 */
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";

const argvList = process.argv.slice(2);
function argOf(flag, dflt) {
  const i = argvList.indexOf(flag);
  return i >= 0 ? argvList[i + 1] : dflt;
}
const tgzAcp = argOf("--tgz-acp");
const tgzSdk = argOf("--tgz-sdk");
const tgzAgentSdk = argOf("--tgz-agent-sdk");
const tgzZod = argOf("--tgz-zod");
if (!tgzAcp || !tgzSdk || !tgzAgentSdk || !tgzZod) {
  console.error("missing --tgz-acp/--tgz-sdk/--tgz-agent-sdk/--tgz-zod");
  process.exit(2);
}
const KEEP = argvList.includes("--keep");
const SETTLE_MS = Number(argOf("--settle", 1500));
const RPC_TIMEOUT = Number(argOf("--per-rpc-timeout", 20000));
const work = argOf("--work", fs.mkdtempSync(path.join(os.tmpdir(), "q4-acp-probe-claude-")));
for (const sub of ["src/package", "home", "ws", "witness", "bin"]) {
  fs.mkdirSync(path.join(work, sub), { recursive: true });
}
const witnessCli = path.join(work, "witness", "fake-cli.jsonl");
const witnessMcp = path.join(work, "witness", "mcp-servers.jsonl");
fs.writeFileSync(witnessCli, "");
fs.writeFileSync(witnessMcp, "");
const summary = { probe: "acp-session-new-mcpServers-claude", work, node: process.version, grids: [], failures: [], startedAt: new Date().toISOString() };
function grid(id, verdict, evidence) {
  summary.grids.push({ id, verdict, evidence });
  if (verdict !== "observed" && verdict !== "observed-negative") summary.failures.push(id);
}

// ---------------------------------------------- 1. assemble isolated package tree
function untar(tgz, destParent) {
  const d = path.join(work, destParent);
  fs.mkdirSync(d, { recursive: true });
  const r = spawnSync("tar", ["-xzf", path.resolve(tgz), "-C", d], { encoding: "utf8" });
  if (r.status !== 0) throw new Error(`tar failed for ${tgz}: ${r.stderr}`);
  return path.join(d, "package");
}
const acpDir = untar(tgzAcp, "src");
const pkgJson = JSON.parse(fs.readFileSync(path.join(acpDir, "package.json"), "utf8"));
const nm = path.join(acpDir, "node_modules");
fs.mkdirSync(path.join(nm, "@agentclientprotocol"), { recursive: true });
fs.mkdirSync(path.join(nm, "@anthropic-ai"), { recursive: true });
fs.renameSync(untar(tgzSdk, "deps/sdk"), path.join(nm, "@agentclientprotocol", "sdk"));
fs.renameSync(untar(tgzAgentSdk, "deps/agent-sdk"), path.join(nm, "@anthropic-ai", "claude-agent-sdk"));
fs.renameSync(untar(tgzZod, "deps/zod"), path.join(nm, "zod"));
summary.adapter = { name: pkgJson.name, version: pkgJson.version, entry: path.join(acpDir, "dist", "index.js") };

const entry = path.join(acpDir, "dist", "index.js");
function isolatedEnv(extra) {
  return {
    PATH: "/usr/bin:/bin",
    HOME: path.join(work, "home"),
    CLAUDE_CODE_EXECUTABLE: path.join(work, "bin", "claude"),
    PROBE_CLI_WITNESS: witnessCli,
    ...extra,
  };
}

// ----------------------------------------------------- 2. static reachability
{
  const r = spawnSync(process.execPath, [entry, "--version"], { encoding: "utf8", env: isolatedEnv({}), timeout: 15000 });
  const out = (r.stdout || "").trim();
  grid("S0-static", r.status === 0 && out.includes(pkgJson.version) ? "observed" : "failed", {
    cmd: "node dist/index.js --version", exit: r.status, stdout: out.slice(0, 200), stderr: (r.stderr || "").slice(0, 400),
  });
}

// ------------------------------------------------------- 3. fake Claude CLI
const FAKE_CLI = `#!${process.execPath}
// Fake Claude Code CLI: witnesses argv + every stdin frame; answers the SDK
// control protocol ({"type":"control_request",...}) with success and emits a
// stream-json system init line (shape: sdk.mjs readMessages / init transport).
const fs = require("node:fs");
const WITNESS = process.env.PROBE_CLI_WITNESS;
function witness(o) { fs.appendFileSync(WITNESS, JSON.stringify(Object.assign({ ts: Date.now() }, o)) + "\\n"); }
witness({ dir: "spawn", argv: process.argv.slice(1), cwd: process.cwd() });
process.stdout.write(JSON.stringify({ type: "system", subtype: "init", session_id: "fake-cli-" + process.pid, model: "fake-claude", cwd: process.cwd(), tools: [], slash_commands: [], apiKeySource: "none", permissionMode: "default" }) + "\\n");
let buf = "";
process.stdin.on("data", (c) => {
  buf += c.toString();
  let i;
  while ((i = buf.indexOf("\\n")) >= 0) {
    const line = buf.slice(0, i).trim();
    buf = buf.slice(i + 1);
    if (!line) continue;
    let msg; try { msg = JSON.parse(line); } catch { continue; }
    witness({ dir: "in", frame: msg });
    if (msg.type === "control_request") {
      const sub = msg.request && msg.request.subtype;
      const body = sub === "initialize" ? {
        commands: [],
        output_style: "default",
        permissionMode: "default",
        agents: [],
        // ModelInfo shape consumed by dist/session-model.js getAvailableModels
        // (value/displayName/description; models[0] is the default).
        models: [{ value: "fake-claude", displayName: "Fake Claude", description: "fake probe model" }],
        // Account that passes hide-claude-auth.js predicates
        // (holdsNonSubscriptionCredential true via non-firstParty apiProvider).
        account: { apiProvider: "probe-fake", tokenSource: "oauth", subscriptionType: null },
      } : {};
      const out = { type: "control_response", response: { subtype: "success", request_id: msg.request_id, response: body } };
      witness({ dir: "out", frame: out });
      process.stdout.write(JSON.stringify(out) + "\\n");
    }
  }
});
process.on("SIGTERM", () => process.exit(0));
`;
const fakeCliPath = path.join(work, "bin", "claude");
fs.writeFileSync(fakeCliPath, FAKE_CLI, { mode: 0o755 });

// ---------------------------------------------------- 4. fake loopback MCP server
const mcpHits = { total: 0, byPath: {} };
const mcpServer = http.createServer((req, res) => {
  let body = "";
  req.on("data", (c) => (body += c));
  req.on("end", () => {
    mcpHits.total += 1;
    mcpHits.byPath[req.url] = (mcpHits.byPath[req.url] || 0) + 1;
    fs.appendFileSync(witnessMcp, JSON.stringify({ ts: Date.now(), url: req.url, body: body || null }) + "\n");
    res.setHeader("content-type", "application/json");
    let msg = null;
    try { msg = JSON.parse(body); } catch {}
    if (!msg || msg.method === undefined) { res.statusCode = 202; res.end(""); return; }
    if (msg.method === "initialize") {
      res.end(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: { protocolVersion: msg.params?.protocolVersion ?? "2025-03-26", capabilities: { tools: {} }, serverInfo: { name: "probe-fake-mcp", version: "0" } } }));
    } else if (msg.method === "tools/list") {
      res.end(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: { tools: [] } }));
    } else {
      res.end(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: {} }));
    }
  });
});
await new Promise((r) => mcpServer.listen(0, "127.0.0.1", r));
const mcpPort = mcpServer.address().port;
{
  const r = await fetch(`http://127.0.0.1:${mcpPort}/mcp-selftest`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-03-26", clientInfo: { name: "selftest", version: "0" }, capabilities: {} } }),
  });
  const j = await r.json();
  grid("S1-fakeMcp-selftest", j?.result?.serverInfo?.name === "probe-fake-mcp" ? "observed" : "failed", { status: r.status });
}

// -------------------------------------------- 5. adapter + minimal ACP client
const adapter = spawn(process.execPath, [entry], {
  cwd: path.join(work, "home"),
  env: isolatedEnv({}),
  stdio: ["pipe", "pipe", "pipe"],
  detached: true,
});
const stderrLog = fs.openSync(path.join(work, "witness", "adapter-stderr.log"), "a");
adapter.stderr.on("data", (c) => fs.writeSync(stderrLog, c));
adapter.on("exit", (code, sig) => { summary.adapterExit = { code, sig }; });

let rpcId = 0;
const pending = new Map();
adapter.stdout.on("data", (chunk) => {
  for (const line of String(chunk).split("\n")) {
    const t = line.trim();
    if (!t) continue;
    let msg;
    try { msg = JSON.parse(t); } catch { continue; }
    if (msg.id !== undefined && msg.method !== undefined) {
      adapter.stdin.write(JSON.stringify({ jsonrpc: "2.0", id: msg.id, error: { code: -32601, message: "probe: unhandled agent request" } }) + "\n");
    } else if (msg.id !== undefined) {
      const p = pending.get(msg.id);
      if (p) { pending.delete(msg.id); p.resolve(msg); }
    }
  }
});
function rpc(method, params) {
  const id = ++rpcId;
  const promise = new Promise((resolve, reject) => {
    const to = setTimeout(() => { pending.delete(id); reject(new Error(`timeout on ${method}`)); }, RPC_TIMEOUT);
    pending.set(id, { resolve: (m) => { clearTimeout(to); resolve(m); } });
  });
  adapter.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
  return promise.then((m) => {
    if (m.error) { const e = new Error(`${method} error ${m.error.code}: ${m.error.message}`); e.response = m; throw e; }
    return m;
  });
}

try {
  const init = await rpc("initialize", {
    protocolVersion: 1,
    clientCapabilities: { fs: { readTextFile: false, writeTextFile: false }, terminal: false },
    clientInfo: { name: "q4-acp-probe-claude", version: "0.0.0" },
  });
  grid("S2-acp-initialize", "observed", {
    agentInfo: init.result?.agentInfo,
    mcpCapabilities: init.result?.agentCapabilities?.mcpCapabilities ?? null,
  });

  const ws = path.join(work, "ws");
  const a = await rpc("session/new", {
    cwd: ws,
    mcpServers: [{ name: "probe", type: "http", url: `http://127.0.0.1:${mcpPort}/mcp`, headers: [{ name: "X-Probe-Key", value: "probe-secret" }] }],
  });
  const b = await rpc("session/new", {
    cwd: ws,
    mcpServers: [{ name: "probe-b", type: "http", url: `http://127.0.0.1:${mcpPort}/mcpb`, headers: [{ name: "X-Probe-Key", value: "probe-b-secret" }] }],
  });
  const c = await rpc("session/new", { cwd: ws, mcpServers: [] });

  await new Promise((r) => setTimeout(r, SETTLE_MS));

  const allSpawns = fs.readFileSync(witnessCli, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l)).filter((f) => f.dir === "spawn");
  // The adapter also shells out `claude auth status --json`; the stream-json
  // query processes are the per-session backend instances.
  const spawns = allSpawns.filter((s) => s.argv.includes("--input-format"));
  summary.authStatusProbes = allSpawns.filter((s) => !s.argv.includes("--input-format")).map((s) => s.argv);
  const mcpConfigs = spawns.map((s) => {
    const i = s.argv.indexOf("--mcp-config");
    if (i < 0) return null;
    try { return JSON.parse(s.argv[i + 1]); } catch { return { PARSE_ERROR: s.argv[i + 1] }; }
  });
  const hasStrict = spawns.map((s) => s.argv.includes("--strict-mcp-config"));
  summary.sessionIds = { A: a.result?.sessionId, B: b.result?.sessionId, C: c.result?.sessionId };

  grid("C1-spawn-observed", spawns.length >= 1 ? "observed" : "failed", { spawnCount: spawns.length, sessionCount: 3, argv0: spawns[0]?.argv?.slice(0, 8) });
  const expectA = { probe: { type: "http", url: `http://127.0.0.1:${mcpPort}/mcp`, headers: { "X-Probe-Key": "probe-secret" } } };
  const expectB = { "probe-b": { type: "http", url: `http://127.0.0.1:${mcpPort}/mcpb`, headers: { "X-Probe-Key": "probe-b-secret" } } };
  const match = (cfg, want) => cfg && cfg.mcpServers && JSON.stringify(Object.keys(cfg.mcpServers).sort()) === JSON.stringify(Object.keys(want).sort())
    && Object.entries(want).every(([n, w]) => {
      const g = cfg.mcpServers[n];
      return g && g.url === w.url && (g.headers?.["X-Probe-Key"] || g.http_headers?.["X-Probe-Key"]) === w.headers["X-Probe-Key"];
    });
  grid("C2-injection-A", mcpConfigs.some((x) => match(x, expectA)) ? "observed" : "failed", { mcpConfigs: mcpConfigs.map((x) => x?.mcpServers ?? null) });
  grid("C3-injection-B-disjoint", mcpConfigs.some((x) => match(x, expectB)) ? "observed" : "failed", { note: "second spawn carries only probe-b" });
  const neg = spawns.length >= 3 ? mcpConfigs[spawns.length - 1] : null;
  grid("C4-negative-empty-list", !neg ? "observed-negative" : "failed", { lastConfig: neg, note: "session/new with mcpServers=[] -> no --mcp-config flag in that spawn" });
  grid("C5-strict-mcp-config-absent", hasStrict.every((x) => x === false) ? "observed-negative" : "observed", {
    perSpawn: hasStrict,
    note: "false = SDK did NOT pass --strict-mcp-config, so CLI-side native MCP discovery (user/project config) is not suppressed -- V04 surface stays open",
  });
  grid("C6-adapter-does-not-connect", mcpHits.total === 1 && mcpHits.byPath["/mcp-selftest"] === 1 ? "observed-negative" : "failed", { byPath: mcpHits.byPath });
} catch (err) {
  grid("RUN", "failed", { error: String(err?.stack || err), response: err?.response ?? null });
} finally {
  try { process.kill(-adapter.pid, "SIGTERM"); } catch {}
  await new Promise((r) => setTimeout(r, 300));
  try { process.kill(-adapter.pid, "SIGKILL"); } catch {}
  mcpServer.close();
  fs.closeSync(stderrLog);
  summary.finishedAt = new Date().toISOString();
  const out = JSON.stringify(summary, null, 2);
  if (!summary.failures.length && !KEEP) {
    const persisted = path.join(os.tmpdir(), `q4-acp-probe-claude-summary-${Date.now()}.json`);
    fs.writeFileSync(persisted, out + "\n");
    summary.summarySavedTo = persisted;
    fs.rmSync(work, { recursive: true, force: true });
  } else {
    fs.writeFileSync(path.join(work, "summary.json"), out + "\n");
    summary.summarySavedTo = path.join(work, "summary.json");
  }
  console.log(JSON.stringify(summary, null, 2));
  process.exit(summary.failures.length ? 1 : 0);
}
