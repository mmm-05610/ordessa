/** Controlled Claude ACP route test. Only loopback fake APIs receive model requests. */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:http";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Readable, Writable } from "node:stream";
import { fileURLToPath } from "node:url";

import { PROTOCOL_VERSION, client, methods, ndJsonStream } from "@agentclientprotocol/sdk";

const timeout = (work, label) => {
  let timer;
  return Promise.race([
    work,
    new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`${label} timed out`)), 45_000);
    }),
  ]).finally(() => clearTimeout(timer));
};

const scratch = await mkdtemp(join(tmpdir(), "ordessa-claude-route-"));
const calls = { A: [], B: [], C: [] };
const servers = [];
let adapter;

async function fakeApi(name) {
  const server = createServer(async (request, response) => {
    let raw = "";
    for await (const chunk of request) raw += chunk;
    if (request.url?.startsWith("/v1/messages/count_tokens")) {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ input_tokens: 20 }));
      return;
    }
    if (!request.url?.startsWith("/v1/messages")) {
      response.writeHead(404);
      response.end();
      return;
    }
    const body = JSON.parse(raw);
    calls[name].push(body);
    const id = `msg_${name}_${calls[name].length}`;
    const send = (type, data) =>
      response.write(`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`);
    response.writeHead(200, { "content-type": "text/event-stream" });
    send("message_start", {
      type: "message_start",
      message: {
        id, type: "message", role: "assistant", model: body.model, content: [],
        stop_reason: null, stop_sequence: null,
        usage: { input_tokens: 20, output_tokens: 0 },
      },
    });
    send("content_block_start", {
      type: "content_block_start", index: 0, content_block: { type: "text", text: "" },
    });
    send("content_block_delta", {
      type: "content_block_delta", index: 0,
      delta: { type: "text_delta", text: `route ${name}` },
    });
    send("content_block_stop", { type: "content_block_stop", index: 0 });
    send("message_delta", {
      type: "message_delta", delta: { stop_reason: "end_turn", stop_sequence: null },
      usage: { output_tokens: 3 },
    });
    response.end(`event: message_stop\ndata: {"type":"message_stop"}\n\n`);
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  servers.push(server);
  return `http://127.0.0.1:${server.address().port}`;
}

const route = (url) => ({
  claudeCode: { options: {
    env: {
      ANTHROPIC_BASE_URL: url,
      ANTHROPIC_AUTH_TOKEN: "controlled-local-token",
      CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1",
    },
    // Claude settings override subprocess env, so pin both layers.
    settings: { env: {
      ANTHROPIC_BASE_URL: url,
      ANTHROPIC_AUTH_TOKEN: "controlled-local-token",
    } },
  } },
});

try {
  const [A, B, C] = await Promise.all([fakeApi("A"), fakeApi("B"), fakeApi("C")]);
  const env = {
    ...process.env,
    CLAUDE_CONFIG_DIR: join(scratch, "claude-config"),
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1",
    DISABLE_TELEMETRY: "1",
  };
  for (const key of Object.keys(env)) {
    if (key.startsWith("ANTHROPIC_") || key.startsWith("CLAUDE_CODE_OAUTH")) delete env[key];
  }
  const entry = fileURLToPath(new URL(
    "./node_modules/@agentclientprotocol/claude-agent-acp/dist/index.js", import.meta.url,
  ));
  adapter = spawn(process.execPath, [entry], {
    env, stdio: ["pipe", "pipe", "pipe"],
  });
  let stderr = "";
  adapter.stderr.on("data", (chunk) => { stderr += chunk; });
  const stream = ndJsonStream(
    Writable.toWeb(adapter.stdin), Readable.toWeb(adapter.stdout),
  );
  const connection = client({ name: "ordessa-controlled-route-probe" })
    .onNotification(methods.client.session.update, () => {})
    .onRequest(methods.client.session.requestPermission,
      () => ({ outcome: { outcome: "cancelled" } }))
    .onRequest(methods.client.fs.readTextFile, () => ({ content: "" }))
    .onRequest(methods.client.fs.writeTextFile, () => ({}))
    .connect(stream);
  const agent = connection.agent;
  await timeout(agent.request(methods.agent.initialize, {
    protocolVersion: PROTOCOL_VERSION,
    clientCapabilities: {
      fs: { readTextFile: true, writeTextFile: true }, terminal: false,
    },
  }), "initialize");
  const a = await timeout(agent.request(methods.agent.session.new, {
    cwd: scratch, mcpServers: [], _meta: route(A),
  }), "new A");
  const b = await timeout(agent.request(methods.agent.session.new, {
    cwd: scratch, mcpServers: [], _meta: route(B),
  }), "new B");
  const prompt = (sessionId, text) => timeout(agent.request(methods.agent.session.prompt, {
    sessionId, prompt: [{ type: "text", text }],
  }), `prompt ${text}`);
  assert.equal((await prompt(a.sessionId, "first A")).stopReason, "end_turn");
  assert.equal((await prompt(b.sessionId, "first B")).stopReason, "end_turn");
  const resumed = await timeout(agent.request(methods.agent.session.resume, {
    sessionId: a.sessionId, cwd: scratch, mcpServers: [], _meta: route(C),
  }), "resume A to C");
  assert.equal(resumed.sessionId, a.sessionId);
  assert.equal((await prompt(a.sessionId, "second A")).stopReason, "end_turn");
  assert.equal((await prompt(b.sessionId, "second B")).stopReason, "end_turn");

  // The adapter issues independent title-generation requests. Count only user turns.
  const turns = Object.fromEntries(Object.entries(calls).map(([name, requests]) => [
    name, requests.filter((body) => !JSON.stringify(body.messages).includes(
      "Write the title in the predominant language")),
  ]));
  assert.deepEqual(Object.fromEntries(Object.entries(turns).map(
    ([name, requests]) => [name, requests.length])), { A: 1, B: 2, C: 1 });
  assert.ok(JSON.stringify(turns.C[0].messages).includes("first A"),
    "the resumed A transcript must reach provider C");
  assert.ok(JSON.stringify(turns.B[1].messages).includes("first B"),
    "B must continue on its original provider");
  console.log(JSON.stringify({ result: "GREEN_FAKE_ENDPOINT", turns: { A: 1, B: 2, C: 1 } }));
} catch (error) {
  console.error(String(error));
  process.exitCode = 1;
} finally {
  if (adapter) adapter.kill();
  for (const server of servers) server.close();
  await rm(scratch, { recursive: true, force: true });
}
