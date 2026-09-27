import assert from "node:assert/strict";
import test from "node:test";

import {
  ClaudeAcpAgent,
  computeSessionFingerprint,
} from "@agentclientprotocol/claude-agent-acp/dist/acp-agent.js";

const makeParams = (sessionId, port) => ({
  sessionId,
  cwd: "/controlled/project",
  mcpServers: [],
  _meta: {
    claudeCode: {
      options: {
        env: { ANTHROPIC_BASE_URL: `http://127.0.0.1:${port}` },
        settings: {
          env: { ANTHROPIC_BASE_URL: `http://127.0.0.1:${port}` },
        },
      },
    },
  },
});

test("both per-session env and settings changes invalidate only that session fingerprint", () => {
  const original = makeParams("session-A", 18001);
  const envChanged = structuredClone(original);
  envChanged._meta.claudeCode.options.env.ANTHROPIC_BASE_URL = "http://127.0.0.1:18003";
  const settingsChanged = structuredClone(original);
  settingsChanged._meta.claudeCode.options.settings.env.ANTHROPIC_BASE_URL =
    "http://127.0.0.1:18003";
  assert.notEqual(computeSessionFingerprint(original), computeSessionFingerprint(envChanged));
  assert.notEqual(computeSessionFingerprint(original), computeSessionFingerprint(settingsChanged));
});

test("resuming one Claude session with a new route replaces only its Query", async () => {
  const agent = Object.create(ClaudeAcpAgent.prototype);
  const firstA = makeParams("session-A", 18001);
  const firstB = makeParams("session-B", 18002);
  const events = [];
  agent.sessions = {
    "session-A": {
      sessionFingerprint: computeSessionFingerprint(firstA),
      modes: {},
      configOptions: [],
    },
    "session-B": {
      sessionFingerprint: computeSessionFingerprint(firstB),
      modes: {},
      configOptions: [],
    },
  };
  agent.teardownSession = async (sessionId) => {
    events.push(["teardown", sessionId]);
    delete agent.sessions[sessionId];
  };
  agent.createSession = async (params, opts) => {
    events.push(["create", opts.resume, params._meta.claudeCode.options.env.ANTHROPIC_BASE_URL]);
    agent.sessions[opts.resume] = {
      sessionFingerprint: computeSessionFingerprint(params),
      modes: {},
      configOptions: [],
    };
    return { sessionId: opts.resume, modes: {}, configOptions: [] };
  };

  const nextA = makeParams("session-A", 18003);
  assert.notEqual(computeSessionFingerprint(firstA), computeSessionFingerprint(nextA));
  assert.equal(
    (await agent.getOrCreateSession(nextA, { model: "controlled-model" })).sessionId,
    "session-A",
  );
  assert.deepEqual(events, [
    ["teardown", "session-A"],
    ["create", "session-A", "http://127.0.0.1:18003"],
  ]);
  assert.equal(agent.sessions["session-B"].sessionFingerprint, computeSessionFingerprint(firstB));

  await agent.getOrCreateSession(firstB, { model: "controlled-model" });
  assert.equal(events.length, 2, "unchanged sibling must not be rebuilt");
});
