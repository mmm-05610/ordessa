package integration

// Pi mode runs one Pi RPC process per session thread and Pi restarts its extension_ui_request ids
// inside each process, so the raw ids ("approval-1", ...) repeat across sessions. These tests pin
// the cancel/pending-approval guarantees for the desktop chain: a cancelled turn must resolve its
// own pending approval, and no approval decision may be applied to another session's run.

import (
	"bufio"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type piGateTurn struct {
	sessionID  string
	promptID   string
	permission string
}

type gateOutcome struct {
	executed   bool
	blocked    bool
	stopReason string
}

func startPiGateTurn(t *testing.T, h *adapterHarness, newID, promptID string) piGateTurn {
	t.Helper()
	sessionID := createTracedPiSession(t, h, newID)
	h.sendRequest(promptID, "session/prompt", map[string]any{
		"sessionId": sessionID,
		"prompt":    "approval command",
	})
	permissionID := waitForPiPermissionOn(t, h, promptID, 2*responseTimeout)
	return piGateTurn{sessionID: sessionID, promptID: promptID, permission: permissionID}
}

func createTracedPiSession(t *testing.T, h *adapterHarness, requestID string) string {
	t.Helper()
	h.sendRequest(requestID, "session/new", map[string]any{"cwd": repoRoot(t)})
	resp := h.waitResponse(requestID, responseTimeout)
	var result struct {
		SessionID string `json:"sessionId"`
	}
	unmarshalResult(t, resp, &result)
	if result.SessionID == "" {
		t.Fatalf("session/new returned empty sessionId")
	}
	return result.SessionID
}

func waitForPiPermissionOn(t *testing.T, h *adapterHarness, promptID string, deadline time.Duration) string {
	t.Helper()
	end := time.Now().Add(deadline)
	for time.Now().Before(end) {
		msg, ok := h.reader.poll(time.Until(end))
		if !ok {
			t.Fatalf("no permission request for prompt %q before deadline", promptID)
		}
		if msg.Method == "session/request_permission" {
			return messageID(msg)
		}
		if msg.ID != nil && messageID(msg) == promptID {
			t.Fatalf("prompt %q finished before any permission request: %s", promptID, string(msg.Result))
		}
	}
	t.Fatalf("no permission request for prompt %q before deadline", promptID)
	return ""
}

// collectPiGateWindow records, per ACP session, whether its tool ran and how its turn ended.
// `turns` maps the prompt rpc id to the session that prompt belongs to.
func collectPiGateWindow(
	t *testing.T,
	h *adapterHarness,
	window time.Duration,
	turns map[string]string,
) map[string]*gateOutcome {
	t.Helper()
	outcomes := map[string]*gateOutcome{}
	outcomeFor := func(sessionID string) *gateOutcome {
		outcome := outcomes[sessionID]
		if outcome == nil {
			outcome = &gateOutcome{}
			outcomes[sessionID] = outcome
		}
		return outcome
	}

	deadline := time.Now().Add(window)
	for time.Now().Before(deadline) {
		msg, ok := h.reader.poll(100 * time.Millisecond)
		if !ok {
			continue
		}
		if msg.Method == "session/update" {
			update := decodeSessionUpdate(t, msg)
			if update.Type != "message" {
				continue
			}
			outcome := outcomeFor(update.SessionID)
			if strings.Contains(update.Delta, "executed command") {
				outcome.executed = true
			}
			if strings.Contains(update.Delta, "command not executed") {
				outcome.blocked = true
			}
			continue
		}
		if msg.ID == nil {
			continue
		}
		sessionID, tracked := turns[messageID(msg)]
		if !tracked {
			continue
		}
		var result struct {
			StopReason string `json:"stopReason"`
		}
		unmarshalResult(t, msg, &result)
		outcomeFor(sessionID).stopReason = result.StopReason
	}
	return outcomes
}

type piTraceFrame struct {
	TS        string          `json:"ts"`
	Stream    string          `json:"stream"`
	Direction string          `json:"direction"`
	Payload   json.RawMessage `json:"payload"`
}

type tracedPiHarness struct {
	h         *adapterHarness
	tracePath string
}

func startTracedPiAdapter(t *testing.T, piBin string, sessionDir string, extraEnv ...string) *tracedPiHarness {
	t.Helper()

	rootDir := repoRoot(t)
	adapterBin := buildBinary(t, rootDir, "./cmd/acp")
	tracePath := filepath.Join(t.TempDir(), "trace.jsonl")
	if err := os.WriteFile(tracePath, nil, 0o644); err != nil {
		t.Fatalf("prepare trace file: %v", err)
	}

	cmd := exec.Command(adapterBin, "--adapter", "pi", "--trace-json", "--trace-json-file", tracePath)
	cmd.Dir = rootDir
	cmd.Env = append(os.Environ(), append([]string{
		"LOG_LEVEL=debug",
		"PI_BIN=" + piBin,
		"PI_SESSION_DIR=" + sessionDir,
	}, extraEnv...)...)

	stdin, err := cmd.StdinPipe()
	if err != nil {
		t.Fatalf("stdin pipe: %v", err)
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatalf("stdout pipe: %v", err)
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		t.Fatalf("stderr pipe: %v", err)
	}
	if err := cmd.Start(); err != nil {
		t.Fatalf("start adapter: %v", err)
	}
	waitCh := make(chan error, 1)
	go func() { waitCh <- cmd.Wait(); close(waitCh) }()
	go func() { _, _ = bufio.NewReader(stderr).ReadString(0) }()

	h := &adapterHarness{t: t, cmd: cmd, stdin: stdin, reader: newRPCReader(t, stdout), waitCh: waitCh}
	t.Cleanup(h.stop)
	return &tracedPiHarness{h: h, tracePath: tracePath}
}

// piFramesSentToBackend lists the bridge->Pi RPC frames recorded in the trace. The adapter is still
// writing while tests read, so a half-flushed trailing line is skipped rather than being fatal; a frame
// that never lands is caught by the caller's own absence check.
func piFramesSentToBackend(t *testing.T, path string) []string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read trace: %v", err)
	}
	var out []string
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		var frame piTraceFrame
		if err := json.Unmarshal([]byte(line), &frame); err != nil {
			continue
		}
		if frame.Stream != "appserver" || frame.Direction != "send" {
			continue
		}
		out = append(out, string(frame.Payload))
	}
	return out
}

// initializePiAdapter advertises clientCapabilities.session.notices on purpose: benign lifecycle status
// updates (turn_cancelled, turn_completed, ...) only reach the wire for such a client, so the cancel
// assertions here observe the strict connection instead of passing because a frame was gated off.
func initializePiAdapter(t *testing.T, h *adapterHarness) {
	t.Helper()
	h.initializeNoticesClient()
	_ = h.waitResponse("1", responseTimeout)
}

// TestPiApprovalAppliesOnlyToItsOwnSession proves an approval decision is written into the Pi
// process that asked for it, never into whichever session registered last.
func TestPiApprovalAppliesOnlyToItsOwnSession(t *testing.T) {
	piBin := buildFakePiRPC(t)
	h := startTracedPiAdapter(t, piBin, t.TempDir()).h
	initializePiAdapter(t, h)

	first := startPiGateTurn(t, h, "2", "4")
	second := startPiGateTurn(t, h, "3", "7")
	if first.sessionID == second.sessionID {
		t.Fatalf("expected two distinct Pi sessions")
	}

	// Only the first session answers its gate.
	h.sendResultResponse(first.permission, map[string]any{"outcome": "approved"})

	outcomes := collectPiGateWindow(t, h, 10*time.Second, map[string]string{
		first.promptID:  first.sessionID,
		second.promptID: second.sessionID,
	})
	if got := outcomes[first.sessionID]; got == nil || !got.executed || got.stopReason != "end_turn" {
		t.Fatalf("approved session did not run its own tool: %+v", outcomes[first.sessionID])
	}
	if got := outcomes[second.sessionID]; got != nil && (got.executed || got.blocked) {
		t.Fatalf("unanswered session was resolved by another session's approval: %+v", got)
	}
}

// readPiResponsePair collects two rpc responses by id, in either order. The cancelled turn's own
// result can be written before the session/cancel ack, so a helper that waits for one id first
// would silently drop the other.
func readPiResponsePair(
	t *testing.T,
	h *adapterHarness,
	firstID, secondID string,
	window time.Duration,
) map[string]string {
	t.Helper()
	messages := readPiResponses(t, h, firstID, secondID, window, nil)
	seen := map[string]string{}
	for id, msg := range messages {
		seen[id] = string(msg.Result)
	}
	return seen
}

// readPiResponses is readPiResponsePair with the full frames, so a test can tell a result apart from
// an error reply for the same id. onOther sees every message that is not one of the two responses,
// along with the id of the reply that arrived before it (empty when none has), so frame order can be
// pinned too.
func readPiResponses(
	t *testing.T,
	h *adapterHarness,
	firstID, secondID string,
	window time.Duration,
	onOther func(msg rpcMessage, replied string),
) map[string]rpcMessage {
	t.Helper()
	seen := map[string]rpcMessage{}
	replied := ""
	deadline := time.Now().Add(window)
	for time.Now().Before(deadline) && len(seen) < 2 {
		msg, ok := h.reader.poll(time.Until(deadline))
		if !ok {
			break
		}
		if msg.ID != nil {
			switch id := messageID(msg); id {
			case firstID, secondID:
				seen[id] = msg
				replied = id
				continue
			}
		}
		if onOther != nil {
			onOther(msg, replied)
		}
	}
	return seen
}

// TestPiCancelResolvesOnlyItsOwnPendingApproval cancels one gated session while another waits: the
// cancelled turn must end its own gate on the wire and must not consume the other session's answer.
func TestPiCancelResolvesOnlyItsOwnPendingApproval(t *testing.T) {
	piBin := buildFakePiRPC(t)
	p := startTracedPiAdapter(t, piBin, t.TempDir())
	h := p.h
	initializePiAdapter(t, h)

	first := startPiGateTurn(t, h, "2", "4")
	second := startPiGateTurn(t, h, "3", "7")

	h.sendRequest("8", "session/cancel", map[string]any{"sessionId": first.sessionID})
	responses := readPiResponsePair(t, h, "8", first.promptID, 10*time.Second)
	if !strings.Contains(responses["8"], `"cancelled":true`) {
		t.Fatalf("cancel ack mismatch: %q", responses["8"])
	}

	resolved := false
	for _, frame := range piFramesSentToBackend(t, p.tracePath) {
		if strings.Contains(frame, `"type":"extension_ui_response"`) && strings.Contains(frame, `"cancelled":true`) {
			resolved = true
		}
	}
	if !resolved {
		t.Fatalf("cancel left the pending approval unresolved: %v", piFramesSentToBackend(t, p.tracePath))
	}

	// The other session keeps its own pending approval and still answers normally.
	h.sendResultResponse(second.permission, map[string]any{"outcome": "approved"})
	outcomes := collectPiGateWindow(t, h, 10*time.Second, map[string]string{
		first.promptID:  first.sessionID,
		second.promptID: second.sessionID,
	})
	if got := outcomes[second.sessionID]; got == nil || !got.executed || got.stopReason != "end_turn" {
		t.Fatalf("untouched session lost its pending approval: %+v", outcomes[second.sessionID])
	}
	if got := outcomes[first.sessionID]; got != nil && got.executed {
		t.Fatalf("cancelled session executed its tool after cancel: %+v", got)
	}
	if strings.Contains(responses[first.promptID], "end_turn") {
		t.Fatalf("cancelled turn reported a normal end: %q", responses[first.promptID])
	}
}

// TestPiPromptAfterCancelTerminalStateIsAccepted is the counterexample for the cancel teardown race:
// a client that immediately continues the same session, as soon as it sees the cancellation as
// terminal, must not be told the session still has an active run. The cancelled turn's teardown may
// neither reject nor end the follow-up turn, and its abandoned approval may not run later.
func TestPiPromptAfterCancelTerminalStateIsAccepted(t *testing.T) {
	piBin := buildFakePiRPC(t)
	p := startTracedPiAdapter(t, piBin, t.TempDir())
	h := p.h
	initializePiAdapter(t, h)

	gated := startPiGateTurn(t, h, "2", "3")
	h.sendRequest("4", "session/cancel", map[string]any{"sessionId": gated.sessionID})
	responses := readPiResponsePair(t, h, "4", gated.promptID, 10*time.Second)
	if !strings.Contains(responses["4"], `"cancelled":true`) {
		t.Fatalf("cancel ack mismatch: %q", responses["4"])
	}
	if !strings.Contains(responses[gated.promptID], `"stopReason":"cancelled"`) {
		t.Fatalf("cancelled turn never reported its terminal state: %q", responses[gated.promptID])
	}

	h.sendRequest("5", "session/prompt", map[string]any{
		"sessionId": gated.sessionID,
		"prompt":    "Explain the Pi adapter bridge.",
	})
	next := h.waitResponse("5", 15*time.Second)
	if next.Error != nil {
		t.Fatalf("follow-up turn rejected right after the cancellation: %s", next.Error.Message)
	}
	var followUp struct {
		StopReason string `json:"stopReason"`
	}
	unmarshalResult(t, next, &followUp)
	if followUp.StopReason != "end_turn" {
		t.Fatalf("follow-up turn was ended by the cancelled turn's teardown: %q", followUp.StopReason)
	}

	for _, frame := range piFramesSentToBackend(t, p.tracePath) {
		if strings.Contains(frame, `"type":"extension_ui_response"`) && strings.Contains(frame, `"confirmed":true`) {
			t.Fatalf("cancelled approval was answered as approved after the turn ended: %s", frame)
		}
	}
}

// waitPiFrameSentToBackend blocks until the bridge has written a backend frame matching want. Tests
// use it to order their next ACP write after the bridge really reached the wire, instead of guessing
// a delay that a race could still win.
func waitPiFrameSentToBackend(t *testing.T, p *tracedPiHarness, want func(frame string) bool, window time.Duration) {
	t.Helper()
	deadline := time.Now().Add(window)
	for time.Now().Before(deadline) {
		for _, frame := range piFramesSentToBackend(t, p.tracePath) {
			if want(frame) {
				return
			}
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("bridge never wrote the matching frame to the backend")
}

// TestPiCancelLosesToNormalCompletion keeps the terminal the backend actually reached: the tool had
// already been granted and kept running, so the bridge must report the normal end instead of a
// cancellation it did not achieve — and must still deliver the frames that arrived after the
// cancellation, before the reply that closes the turn.
func TestPiCancelLosesToNormalCompletion(t *testing.T) {
	piBin := buildFakePiRPC(t)
	p := startTracedPiAdapter(t, piBin, t.TempDir(), "PI_FAKE_APPROVED_HOLD=1500ms")
	h := p.h
	initializePiAdapter(t, h)

	gated := startPiGateTurn(t, h, "2", "3")
	h.sendResultResponse(gated.permission, map[string]any{"outcome": "approved"})
	// The grant must be on the backend wire before the cancel starts, so the only race left is the
	// one under test: a turn that is already running to completion versus a later cancellation.
	waitPiFrameSentToBackend(t, p, func(frame string) bool {
		return strings.Contains(frame, `"type":"extension_ui_response"`) &&
			strings.Contains(frame, `"confirmed":true`)
	}, 10*time.Second)
	h.sendRequest("4", "session/cancel", map[string]any{"sessionId": gated.sessionID})

	var sawCancelStatus, sawLateText, sawLateUsage, sawClosingStatus bool
	responses := readPiResponses(t, h, "4", gated.promptID, 20*time.Second, func(msg rpcMessage, replied string) {
		if msg.Method != "session/update" {
			return
		}
		if replied == gated.promptID {
			t.Fatalf("a late frame was delivered after the turn was already closed: %s", string(msg.Params))
		}
		update := decodeSessionUpdate(t, msg)
		switch {
		case strings.Contains(string(msg.Params), "turn_cancelled"):
			sawCancelStatus = true
		case update.Type == "message" && strings.Contains(update.Delta, "executed command"):
			sawLateText = true
		case update.Type == "usage_update":
			sawLateUsage = true
		case update.Type == "status" && update.Status == "turn_completed":
			sawClosingStatus = true
		}
	})
	turn := responses[gated.promptID]
	if turn.Error != nil {
		t.Fatalf("a turn that ended normally was answered as an error: %s", turn.Error.Message)
	}
	if !strings.Contains(string(turn.Result), `"stopReason":"end_turn"`) {
		t.Fatalf("normal completion was overwritten by the cancellation: %s", string(turn.Result))
	}
	if sawCancelStatus {
		t.Fatalf("a cancelled status notification was sent for a turn that completed normally")
	}
	// The frames that arrived after the cancellation are the ones the uncancelled path would have
	// sent, in order, and all before the reply: the cancellation must not eat the turn's output.
	if !sawLateText {
		t.Fatalf("the output that arrived after the cancellation was dropped")
	}
	if !sawLateUsage {
		t.Fatalf("the usage that arrived after the cancellation was dropped")
	}
	if !sawClosingStatus {
		t.Fatalf("the completed turn was closed without the status frame the uncancelled path sends")
	}
}

// TestPiUnconfirmedCancelIsNotReportedAsCancelled pins the budget path: a gate that answers neither the
// abort nor the bridge's own cancelled response leaves the turn running, so the bridge must not confirm
// a cancellation on either signal and must not imply the session became reusable.
func TestPiUnconfirmedCancelIsNotReportedAsCancelled(t *testing.T) {
	piBin := buildFakePiRPC(t)
	h := startTracedPiAdapter(t, piBin, t.TempDir(), "PI_FAKE_ABORT_NEVER_ENDS=1").h
	initializePiAdapter(t, h)

	gated := startPiGateTurn(t, h, "2", "3")
	h.sendRequest("4", "session/cancel", map[string]any{"sessionId": gated.sessionID})
	sawCancelStatus := false
	responses := readPiResponses(t, h, "4", gated.promptID, 10*time.Second, func(msg rpcMessage, _ string) {
		if msg.Method == "session/update" && strings.Contains(string(msg.Params), "turn_cancelled") {
			sawCancelStatus = true
		}
	})
	if len(responses) != 2 {
		t.Fatalf("cancel and turn never both answered: %v", responses)
	}
	if sawCancelStatus {
		t.Fatalf("a cancelled status notification was sent for a cancellation that was never confirmed")
	}
	for _, id := range []string{"4", gated.promptID} {
		msg := responses[id]
		if msg.Error == nil {
			t.Fatalf("unconfirmed cancellation was answered as success on %s: %s", id, string(msg.Result))
		}
		if strings.Contains(string(msg.Result), `"cancelled":true`) || strings.Contains(string(msg.Result), `"stopReason"`) {
			t.Fatalf("unconfirmed cancellation reported a terminal state on %s: %s", id, string(msg.Result))
		}
	}

	// The bridge never claimed the turn was over, so the session stays honestly busy instead of
	// pretending the cancellation freed it.
	h.sendRequest("5", "session/prompt", map[string]any{
		"sessionId": gated.sessionID,
		"prompt":    "Explain the Pi adapter bridge.",
	})
	followUp := h.waitResponse("5", 10*time.Second)
	if followUp.Error == nil {
		t.Fatalf("session was declared reusable after an unconfirmed cancellation: %s", string(followUp.Result))
	}
}

// TestPiCancelEndsApprovalGateThatIgnoresAbort uses a peer whose gate is released only by a real
// extension_ui_response, so the test fails if the bridge stops relying on its own cleanup.
func TestPiCancelEndsApprovalGateThatIgnoresAbort(t *testing.T) {
	piBin := buildFakePiRPC(t)
	p := startTracedPiAdapter(t, piBin, t.TempDir(), "PI_FAKE_GATE_IGNORES_ABORT=1")
	h := p.h
	initializePiAdapter(t, h)

	gated := startPiGateTurn(t, h, "2", "3")
	h.sendRequest("4", "session/cancel", map[string]any{"sessionId": gated.sessionID})
	responses := readPiResponsePair(t, h, "4", gated.promptID, 10*time.Second)
	if !strings.Contains(responses["4"], `"cancelled":true`) {
		t.Fatalf("cancel ack mismatch: %q", responses["4"])
	}
	// This gate treats the bridge's own cancelled response as a denial, so the peer really ends the
	// turn normally with its tool blocked. The bridge must report that terminal reason rather than
	// claiming a cancellation the backend never sent.
	if got := responses[gated.promptID]; !strings.Contains(got, `"stopReason":"end_turn"`) {
		t.Fatalf("cancelled turn did not report the backend's own ending: %q", got)
	}

	sawExecuted := false
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		msg, ok := h.reader.poll(100 * time.Millisecond)
		if !ok {
			break
		}
		if msg.Method != "session/update" {
			continue
		}
		update := decodeSessionUpdate(t, msg)
		if update.Type == "message" && strings.Contains(update.Delta, "executed command") {
			sawExecuted = true
		}
	}
	if sawExecuted {
		t.Fatalf("cancelled turn executed the tool anyway")
	}

	resolved := false
	for _, frame := range piFramesSentToBackend(t, p.tracePath) {
		if strings.Contains(frame, `"type":"extension_ui_response"`) && strings.Contains(frame, `"cancelled":true`) {
			resolved = true
		}
	}
	if !resolved {
		t.Fatalf("bridge did not answer its own pending approval on cancel")
	}
}
