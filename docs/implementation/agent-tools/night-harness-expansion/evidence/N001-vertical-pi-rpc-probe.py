import json, sys
sys.path.insert(0, "/home/maoqh/.codex/worktrees/agent-tools-product/ordessa/products/agent-tools/src")
from ordessa_agent_tools.native_clients import LaunchSpec, ProcessChannel

home = "/tmp/n001-pi-home"
spec = LaunchSpec.build(
    ["/home/maoqh/.pi/agent/install/releases/0.86.1/node_modules/.bin/pi",
     "--mode", "rpc", "--no-session", "--offline",
     "--no-extensions", "--no-skills", "--no-context-files",
     "--no-prompt-templates", "--no-approve"],
    home=home, cwd="/tmp/n001-pi-work",
    extra_env={"PI_TELEMETRY": "0", "PI_OFFLINE": "1"},
)
channel = ProcessChannel.launch(spec, name="pi-evidence")
log = []
def collect(rid, timeout=5):
    msgs = []
    for _ in range(30):
        m = channel.poll_message(timeout=timeout)
        if m is None:
            break
        msgs.append(dict(m.raw))
        if m.raw.get("id") == rid and m.raw.get("type") == "response":
            break
    return msgs

channel.send_raw({"id": "ev-1", "type": "get_state"})
log.append({"step": "get_state", "messages": collect("ev-1")})
channel.send_raw({"id": "ev-2", "type": "get_commands"})
r = collect("ev-2")
log.append({"step": "get_commands", "messages": r})
# counter-example: unknown command
channel.send_raw({"id": "ev-3", "type": "definitely_not_a_command"})
log.append({"step": "unknown-command", "messages": collect("ev-3")})
# counter-example: malformed JSON line -> parse response
import os
os.write(channel._process.stdin.fileno(), b"{not json\n")
log.append({"step": "malformed-json", "messages": collect("no-id", timeout=3)})
print(json.dumps({"probe": "pi-0.86.1-rpc-vertical", "isolation": "unshare -rn + HOME=/tmp/n001-pi-home + --offline + PI_TELEMETRY=0 + no extensions/skills/context/approve", "steps": log}, ensure_ascii=False, indent=1))
print("STDERR_TAIL:", repr(channel.stderr_tail()[-300:]))
print("EXIT:", channel.close())
