package integration

import (
	"os"
	"strings"
	"testing"
	"time"
)

type piListedSession struct {
	SessionID string         `json:"sessionId"`
	CWD       string         `json:"cwd"`
	Title     string         `json:"title"`
	UpdatedAt string         `json:"updatedAt"`
	Meta      map[string]any `json:"_meta"`
}

func listPiSessions(t *testing.T, h *adapterHarness, requestID string, cwd string) []piListedSession {
	t.Helper()

	h.sendRequest(requestID, "session/list", map[string]any{"cwd": cwd})
	resp := h.waitResponse(requestID, responseTimeout)
	var result struct {
		Sessions []piListedSession `json:"sessions"`
	}
	unmarshalResult(t, resp, &result)
	return result.Sessions
}

// findPiSession returns the session/list entry for one ACP session id. Pi names nothing on its own,
// so the entry is the only place a native name can reach the desktop client.
func findPiSession(t *testing.T, sessions []piListedSession, sessionID string) piListedSession {
	t.Helper()
	for _, session := range sessions {
		if session.SessionID == sessionID {
			return session
		}
	}
	t.Fatalf("session %s not found in session/list: %+v", sessionID, sessions)
	return piListedSession{}
}

func promptPiSessionToCompletion(t *testing.T, h *adapterHarness, requestID string, sessionID string, text string) {
	t.Helper()

	h.sendRequest(requestID, "session/prompt", map[string]any{
		"sessionId": sessionID,
		"prompt":    []map[string]any{{"type": "text", "text": text}},
	})
	deadline := time.Now().Add(30 * time.Second)
	for time.Now().Before(deadline) {
		msg, ok := h.reader.poll(time.Until(deadline))
		if !ok {
			break
		}
		if msg.ID != nil && string(*msg.ID) == `"`+requestID+`"` {
			return
		}
	}
	t.Fatalf("prompt %s never completed", requestID)
}

func newPiSession(t *testing.T, h *adapterHarness, requestID string, cwd string) string {
	t.Helper()

	initializePiAdapter(t, h)
	h.sendRequest(requestID, "session/new", map[string]any{"cwd": cwd})
	resp := h.waitResponse(requestID, responseTimeout)
	var result struct {
		SessionID string `json:"sessionId"`
	}
	unmarshalResult(t, resp, &result)
	if result.SessionID == "" {
		t.Fatalf("session/new returned empty sessionId: %s", string(resp.Result))
	}
	return result.SessionID
}

// TestPiNamedSessionSurfacesNativeName pins the supported case: Pi stores a name only when the user
// named the session, and the bridge must report that exact name, never an imitation of it.
func TestPiNamedSessionSurfacesNativeName(t *testing.T) {
	piBin := buildFakePiRPC(t)
	const nativeName = "ordessa-native-name"
	h := startPiAdapter(t, piBin, t.TempDir(), "PI_FAKE_SESSION_NAME="+nativeName)

	sessionID := newPiSession(t, h, "2", repoRoot(t))
	promptPiSessionToCompletion(t, h, "3", sessionID, "Explain the Pi adapter bridge.")

	entry := findPiSession(t, listPiSessions(t, h, "4", repoRoot(t)), sessionID)
	if entry.Title != nativeName {
		t.Fatalf("native name lost from Title: got %q want %q", entry.Title, nativeName)
	}
	if got, _ := entry.Meta["sessionName"].(string); got != nativeName {
		t.Fatalf("_meta.sessionName mismatch: got %#v want %q", entry.Meta["sessionName"], nativeName)
	}
	if got, _ := entry.Meta["preview"].(string); got == nativeName || got == "" {
		t.Fatalf("preview should stay the separate first-message field: %#v", entry.Meta["preview"])
	}
}

// TestPiUnnamedSessionHasNoNativeName is the counterexample against fake naming: real Pi 0.86.1
// writes no session_info and reports no sessionName until one is set, so the bridge must not invent
// a name from the first user message.
func TestPiUnnamedSessionHasNoNativeName(t *testing.T) {
	piBin := buildFakePiRPC(t)
	h := startPiAdapter(t, piBin, t.TempDir())

	const firstMessage = "Explain the Pi adapter bridge."
	sessionID := newPiSession(t, h, "2", repoRoot(t))
	promptPiSessionToCompletion(t, h, "3", sessionID, firstMessage)

	entry := findPiSession(t, listPiSessions(t, h, "4", repoRoot(t)), sessionID)
	if raw, ok := entry.Meta["sessionName"]; ok {
		t.Fatalf("unnamed Pi session reported a native name: %#v", raw)
	}
	if entry.Title != firstMessage {
		t.Fatalf("unnamed session title should fall back to the preview: got %q", entry.Title)
	}
	if got, _ := entry.Meta["preview"].(string); got != firstMessage {
		t.Fatalf("_meta.preview mismatch: got %#v", entry.Meta["preview"])
	}

	// The stored session file must look like real Pi's: header plus messages, no session_info line.
	path, _ := entry.Meta["path"].(string)
	if path == "" {
		t.Fatalf("session/list did not report the session file path: %#v", entry.Meta["path"])
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read stored session: %v", err)
	}
	if strings.Contains(string(data), `"session_info"`) {
		t.Fatalf("unnamed Pi session stored a session_info entry:\n%s", string(data))
	}
}
