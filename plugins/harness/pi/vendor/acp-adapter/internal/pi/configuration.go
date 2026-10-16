package pi

import (
	"context"
	"fmt"
	"strings"

	"github.com/beyond5959/acp-adapter/internal/codex"
)

// configurationSession never uses ensureSession: observation must not spawn or
// resume a process as a hidden side effect of reading a configuration snapshot.
func (c *Client) configurationSession(threadID string) (*rpcSession, error) {
	if c.loggedOut.Load() {
		return nil, fmt.Errorf("pi configuration: logged out")
	}
	sess, ok := c.lookupSession(strings.TrimSpace(threadID))
	if !ok {
		return nil, fmt.Errorf("pi configuration: session %q is not attached", threadID)
	}
	return sess, nil
}

func observeConfiguration(ctx context.Context, sess *rpcSession) (codex.RunOptions, error) {
	state, err := sess.getState(ctx)
	if err != nil {
		return codex.RunOptions{}, fmt.Errorf("pi configuration get_state: %w", err)
	}
	model, effort := modelValue(state.Model), strings.TrimSpace(state.ThinkingLevel)
	if model == "" || effort == "" {
		return codex.RunOptions{}, fmt.Errorf("pi configuration get_state omitted model or thinkingLevel")
	}
	return codex.RunOptions{Model: model, Effort: effort}, nil
}

// SessionConfiguration reads the existing native session, never an adapter cache.
func (c *Client) SessionConfiguration(ctx context.Context, threadID string) (codex.RunOptions, error) {
	sess, err := c.configurationSession(threadID)
	if err != nil {
		return codex.RunOptions{}, err
	}
	sess.configurationMu.Lock()
	defer sess.configurationMu.Unlock()
	return observeConfiguration(ctx, sess)
}

// SetSessionConfigOption issues exactly one setter and verifies its native effect.
// Errors do not imply rollback: the caller's original journal owns uncertainty.
func (c *Client) SetSessionConfigOption(ctx context.Context, threadID, configID, value string) (codex.RunOptions, error) {
	sess, err := c.configurationSession(threadID)
	if err != nil {
		return codex.RunOptions{}, err
	}
	sess.configurationMu.Lock()
	defer sess.configurationMu.Unlock()
	if sess.currentRun() != nil {
		return codex.RunOptions{}, fmt.Errorf("pi configuration: active turn refuses configuration change")
	}
	state, err := sess.getState(ctx)
	if err != nil {
		return codex.RunOptions{}, fmt.Errorf("pi configuration preflight get_state: %w", err)
	}
	if state.IsStreaming || state.IsCompacting {
		return codex.RunOptions{}, fmt.Errorf("pi configuration: native session busy")
	}
	value = strings.TrimSpace(value)
	if value == "" {
		return codex.RunOptions{}, fmt.Errorf("pi configuration: value required")
	}
	expected := value
	switch configID {
	case "model":
		provider, modelID, resolveErr := c.resolveModelSelection(ctx, sess, value)
		if resolveErr != nil {
			return codex.RunOptions{}, resolveErr
		}
		selected := rpcModel{Provider: provider, ID: modelID}
		expected = selected.FullID()
		err = sess.setModel(ctx, provider, modelID)
	case "thought_level":
		// Revalidate against the current native model, not an older ACP menu.
		// An external model change may have removed reasoning capabilities.
		if state.Model == nil || state.Model.FullID() == "" {
			return codex.RunOptions{}, fmt.Errorf("pi configuration: native model capabilities unavailable")
		}
		supported := false
		for _, effort := range supportedEffortsForModel(*state.Model) {
			if effort.Value == value {
				supported = true
				break
			}
		}
		if !supported {
			return codex.RunOptions{}, fmt.Errorf("pi configuration: native model %q does not support thinking level %q", state.Model.FullID(), value)
		}
		err = sess.setThinkingLevel(ctx, value)
	default:
		return codex.RunOptions{}, fmt.Errorf("pi configuration: unsupported option %q", configID)
	}
	if err != nil {
		return codex.RunOptions{}, fmt.Errorf("pi configuration setter unconfirmed: %w", err)
	}
	observed, err := observeConfiguration(ctx, sess)
	if err != nil {
		return codex.RunOptions{}, err
	}
	actual := observed.Effort
	if configID == "model" {
		actual = observed.Model
	}
	if actual != expected {
		return codex.RunOptions{}, fmt.Errorf("pi configuration setter ACK without observed effect: option %s expected %q observed %q", configID, expected, actual)
	}
	return observed, nil
}
